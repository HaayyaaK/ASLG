"""Admin-only system maintenance: Factory Reset (wipe + reseed the database)
and a full downloadable backup (SQL dump + uploaded files).

Deliberately separate from the per-device "clear local app data" reset,
which is pure client-side JS (localStorage/sessionStorage) and never calls
the server at all — see js/pages/users.js.
"""

import io
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..audit import log_activity
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import require_roles
from ..models import AuditLog, Case, Court, ImportedRecord, Module, Role, User
from ..schemas import DatabaseResetRequest
from seed import run_seed

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_roles("Admin"))])

logger = logging.getLogger("aslg.admin")

CONFIRM_PHRASE = "RESET DATABASE"
RESTORE_CONFIRM_PHRASE = "RESTORE DATABASE"

# Bumped only if a future change makes an old backup's database.sql
# structurally incompatible with restore-database's expectations (e.g. a
# renamed/removed core table). Written into every new backup's
# backup_meta.json; restore-database refuses a backup whose version doesn't
# match rather than attempting an import that might partially apply.
BACKUP_SCHEMA_VERSION = 1

# Guards all three destructive/heavy endpoints below (reset, backup, restore)
# against running concurrently with each other or with themselves — a second
# click while one is in flight gets a 409 instead of racing mysqldump/mysql
# processes or delete statements against each other.
_maintenance_lock = threading.Lock()


@router.post("/reset-database")
def reset_database(
    payload: DatabaseResetRequest,
    user: User = Depends(require_roles("Admin")),
    db: Session = Depends(get_db),
):
    if payload.confirm_phrase != CONFIRM_PHRASE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Confirmation phrase does not match. Type exactly: {CONFIRM_PHRASE}",
        )

    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "A reset or backup operation is already in progress")

    performed_by_username = user.username
    try:
        # Deletion order matters: these are plain bulk DELETEs (not ORM
        # session.delete()), so cascading to child rows happens via the
        # database's own ON DELETE CASCADE constraints (db/schema.sql), not
        # SQLAlchemy relationship cascades. imported_records.imported_by and
        # audit_log.user_id both reference users with no CASCADE (RESTRICT /
        # SET NULL respectively), so they're cleared before users regardless.
        #
        # 1. imported_records — fk_imported_user has no ON DELETE clause
        #    (defaults to RESTRICT), so this must go before users.
        db.query(ImportedRecord).delete(synchronize_session=False)
        # 2. cases — cascades to case_timeline, case_notes, court_sessions,
        #    experts, execution_files, documents, case_watchers,
        #    case_reminders, document_upload_grants.
        db.query(Case).delete(synchronize_session=False)
        # 3. audit_log — ON DELETE SET NULL from users, so it would NOT be
        #    cleared automatically; wiped explicitly for a genuinely clean
        #    slate (a fresh "database_reset" entry is written after success).
        db.query(AuditLog).delete(synchronize_session=False)
        # 4. users — cascades to notifications(user_id) and user_sessions.
        db.query(User).delete(synchronize_session=False)
        # 5-7. reference/lookup tables. courts has no dependents left at this
        #    point; roles cascades to role_permissions and
        #    notifications(target_role_id); modules cascades to
        #    role_permissions (redundant with the roles cascade, harmless).
        db.query(Court).delete(synchronize_session=False)
        db.query(Role).delete(synchronize_session=False)
        db.query(Module).delete(synchronize_session=False)

        # Uploaded files are on disk, not in the DB — the documents table
        # rows are already gone via the cases cascade above, but the actual
        # files under backend/uploads/<case_id>/... are not, and would
        # become orphaned (and collide with new case_id directories created
        # by the reseed) if left behind.
        upload_root = settings.upload_path
        if upload_root.exists():
            for child in upload_root.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)

        run_seed(db)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Database reset failed; transaction rolled back")
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Database reset failed — no changes were committed. See server logs for details.",
        )
    finally:
        _maintenance_lock.release()

    # user_id is intentionally omitted: the admin row that existed when this
    # request started no longer exists post-reseed (it was deleted along with
    # every other user, then recreated with a new id if present in seed
    # data) — recording the stale id would violate audit_log's own FK.
    log_activity(
        db, None, "database_reset",
        meta={"performed_by_username": performed_by_username},
    )
    return {
        "status": "ok",
        "message": "Database reset to seed data. All users must sign in again.",
    }


def _mysqldump_bytes() -> bytes:
    mysqldump = shutil.which("mysqldump") or r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysqldump.exe"
    if not Path(mysqldump).exists() and shutil.which("mysqldump") is None:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "mysqldump was not found on this server")

    # Credentials go in a --defaults-extra-file, not -p<password> on the
    # command line — the latter is visible to any other user/process that
    # can list running processes on the machine for as long as mysqldump runs.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False, encoding="utf-8") as cnf:
        cnf.write(
            "[client]\n"
            f"user={settings.db_user}\n"
            f"password={settings.db_password}\n"
            f"host={settings.db_host}\n"
            f"port={settings.db_port}\n"
        )
        cnf_path = cnf.name

    try:
        result = subprocess.run(
            [
                mysqldump,
                f"--defaults-extra-file={cnf_path}",
                "--single-transaction",
                "--routines",
                "--triggers",
                settings.db_name,
            ],
            capture_output=True,
            timeout=180,
            # IIS's httpPlatformHandler gives this process no real console, so
            # its own stdin handle is invalid; subprocess.run's default
            # inherit-stdin behavior tries to duplicate that handle and fails
            # with "OSError: [WinError 6] The handle is invalid" before
            # mysqldump ever runs. mysqldump doesn't read stdin, so redirect
            # it explicitly instead of inheriting.
            stdin=subprocess.DEVNULL,
        )
    finally:
        Path(cnf_path).unlink(missing_ok=True)

    if result.returncode != 0:
        logger.error("mysqldump failed (exit %s): %s", result.returncode, result.stderr.decode(errors="replace"))
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Database dump failed — see server logs for details")

    return result.stdout


@router.get("/backup")
def download_backup(user: User = Depends(require_roles("Admin")), db: Session = Depends(get_db)):
    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "A reset or backup operation is already in progress")

    try:
        sql_bytes = _mysqldump_bytes()

        meta = {
            "app": "ASLG",
            "backup_schema_version": BACKUP_SCHEMA_VERSION,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "created_by": user.username,
            "db_name": settings.db_name,
        }

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("backup_meta.json", json.dumps(meta, indent=2))
            zf.writestr("database.sql", sql_bytes)
            upload_root = settings.upload_path
            if upload_root.exists():
                for f in upload_root.rglob("*"):
                    if f.is_file():
                        zf.write(f, arcname=str(Path("uploads") / f.relative_to(upload_root)))
        buf.seek(0)
    finally:
        _maintenance_lock.release()

    log_activity(db, user.id, "database_backup_download")

    filename = f"aslg-backup-{datetime.utcnow():%Y%m%d-%H%M%S}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------- Restore (import a backup produced by /backup above) ----------------

REQUIRED_TABLE_MARKERS = (b"`users`", b"`cases`", b"`roles`")


def _safe_extract_path(member_name: str, dest_root: Path) -> Path:
    """Resolves a zip member's target path under dest_root, raising ValueError
    for anything that would escape it. A zip's internal filenames are
    attacker-controlled input — trusting them directly as filesystem paths
    (the classic "zip slip" bug) would let a crafted archive write files
    anywhere the app process can reach, including outside dest_root."""
    name = member_name.replace("\\", "/")
    if not name or name.startswith("/") or ":" in name or ".." in Path(name).parts:
        raise ValueError(f"Unsafe path in backup archive: {member_name!r}")
    root = dest_root.resolve()
    target = (root / name).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"Unsafe path in backup archive: {member_name!r}")
    return target


def _validate_sql_dump(sql_bytes: bytes):
    """Rejects obviously-wrong input before it ever reaches the mysql client
    running with full database privileges. Not a full SQL parse — just enough
    to catch "wrong file", "empty file", or "corrupted download", which are
    the realistic failure modes for a file a human selected from disk."""
    if not sql_bytes.strip():
        raise ValueError("database.sql is empty")
    head = sql_bytes[:4096]
    if b"-- MySQL dump" not in head and b"-- Host:" not in head:
        raise ValueError("database.sql does not look like mysqldump output (missing its standard header)")
    missing = [t.decode() for t in REQUIRED_TABLE_MARKERS if t not in sql_bytes]
    if missing:
        raise ValueError(f"database.sql is missing expected table definitions: {', '.join(missing)} — refusing to restore")


def _mysql_restore(sql_path: Path):
    mysql_client = shutil.which("mysql") or r"C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe"
    if shutil.which("mysql") is None and not Path(mysql_client).exists():
        raise RuntimeError("mysql client was not found on this server")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cnf", delete=False, encoding="utf-8") as cnf:
        cnf.write(
            "[client]\n"
            f"user={settings.db_user}\n"
            f"password={settings.db_password}\n"
            f"host={settings.db_host}\n"
            f"port={settings.db_port}\n"
        )
        cnf_path = cnf.name

    try:
        # Unlike mysqldump (which never reads stdin, so DEVNULL sidesteps
        # IIS's invalid-stdin-handle issue), mysql here needs the dump file
        # AS its stdin. Passing an explicit, real file handle rather than
        # inheriting the parent process's own handle avoids the same
        # WinError 6 class of bug the backup endpoint hit — this file handle
        # is valid regardless of what httpPlatformHandler gave the process.
        with open(sql_path, "rb") as sql_file:
            result = subprocess.run(
                [mysql_client, f"--defaults-extra-file={cnf_path}", settings.db_name],
                stdin=sql_file,
                capture_output=True,
                timeout=300,
            )
    finally:
        Path(cnf_path).unlink(missing_ok=True)

    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace"))


@router.post("/restore-database")
async def restore_database(
    file: UploadFile = File(...),
    confirm_phrase: str = Form(...),
    user: User = Depends(require_roles("Admin")),
):
    if confirm_phrase != RESTORE_CONFIRM_PHRASE:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Confirmation phrase does not match. Type exactly: {RESTORE_CONFIRM_PHRASE}",
        )

    contents = await file.read()
    if not zipfile.is_zipfile(io.BytesIO(contents)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Uploaded file is not a valid ZIP archive")

    if not _maintenance_lock.acquire(blocking=False):
        raise HTTPException(status.HTTP_409_CONFLICT, "A reset, backup, or restore operation is already in progress")

    tmp_dir: Path | None = None
    pre_restore_path: Path | None = None
    backup_meta: dict | None = None
    try:
        try:
            with zipfile.ZipFile(io.BytesIO(contents)) as zf:
                names = zf.namelist()
                if "database.sql" not in names:
                    raise ValueError("Archive does not contain database.sql — this doesn't look like an ASLG backup")

                if "backup_meta.json" in names:
                    try:
                        backup_meta = json.loads(zf.read("backup_meta.json"))
                    except Exception:
                        raise ValueError("backup_meta.json is present but is not valid JSON")
                    found_version = backup_meta.get("backup_schema_version")
                    if found_version != BACKUP_SCHEMA_VERSION:
                        raise ValueError(
                            f"Backup schema version {found_version!r} does not match this "
                            f"application's version ({BACKUP_SCHEMA_VERSION}) — refusing to restore "
                            "a backup that may be structurally incompatible"
                        )
                # No backup_meta.json at all means this predates the
                # versioning field — allowed, since every backup taken
                # before this feature existed would otherwise be permanently
                # unrestorable, but it's called out in the response so the
                # admin knows compatibility wasn't verified.

                tmp_dir = Path(tempfile.mkdtemp(prefix="aslg_restore_"))
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    target = _safe_extract_path(member.filename, tmp_dir)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst)

            sql_path = tmp_dir / "database.sql"
            _validate_sql_dump(sql_path.read_bytes())

            # Safety net: MySQL DDL statements (CREATE/DROP TABLE, which a
            # mysqldump file is full of) auto-commit and are NOT rolled back
            # by a surrounding transaction, so a mid-import failure can't be
            # undone with a simple db.rollback(). Take a fresh dump of the
            # about-to-be-overwritten database first so there's always an
            # immediate way back — restoring THIS file undoes the restore.
            pre_restore_dir = Path(__file__).resolve().parent.parent.parent / "pre_restore_backups"
            pre_restore_dir.mkdir(exist_ok=True)
            pre_restore_path = pre_restore_dir / f"pre-restore-{datetime.utcnow():%Y%m%d-%H%M%S}.sql"
            pre_restore_path.write_bytes(_mysqldump_bytes())

            _mysql_restore(sql_path)

            # Uploaded files mirror the same wipe-then-replace approach
            # reset-database uses for backend/uploads/ — the restored
            # database.sql's `documents` rows reference storage_path values
            # that only resolve correctly if the files on disk match exactly.
            uploads_src = tmp_dir / "uploads"
            upload_root = settings.upload_path
            if upload_root.exists():
                for child in upload_root.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
            if uploads_src.exists():
                for item in uploads_src.rglob("*"):
                    if item.is_file():
                        dest = upload_root / item.relative_to(uploads_src)
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest)

        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
        except Exception:
            logger.exception("Database restore failed")
            detail = "Restore failed — see server logs for details."
            if pre_restore_path is not None:
                detail += f" A pre-restore safety backup was saved at {pre_restore_path}."
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail)
    finally:
        _maintenance_lock.release()
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # A fresh session, not one carried over from before the restore: the
    # actual data change happened via an external `mysql` process, so any
    # session opened earlier in this request has a stale view of the
    # database. user_id is omitted for the same reason it is in
    # reset-database — the restored users table may not contain this admin's
    # original id at all.
    log_db = SessionLocal()
    try:
        log_activity(
            log_db, None, "database_restore",
            meta={
                "performed_by_username": user.username,
                "uploaded_filename": file.filename,
                "backup_meta": backup_meta,
                "pre_restore_backup": str(pre_restore_path) if pre_restore_path else None,
            },
        )
    finally:
        log_db.close()

    return {
        "status": "ok",
        "message": "Database restored from backup. All users must sign in again.",
        "pre_restore_backup": str(pre_restore_path) if pre_restore_path else None,
        "backup_meta": backup_meta,
    }
