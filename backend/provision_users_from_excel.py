"""Safe validator/report generator for provisioning application users from
DB.xlsx (project root).

WHAT THIS SCRIPT DOES:
  - Reads DB.xlsx and the live `users`/`roles` tables (read-only queries only).
  - Classifies every spreadsheet row as EXISTING / INVALID / NEW_NEEDS_REVIEW /
    NEW_READY.
  - For EXISTING rows, also detects "credential change requests": the sheet
    may supply a username and/or password that differ from what's already in
    the database for that same person. This is reported separately and never
    applied automatically (see CREDENTIAL_CHANGES below).
  - Writes a human-readable Markdown report and, only where applicable, a
    ready-to-review SQL preview — INSERTs for NEW_READY rows, and a clearly
    separate, clearly-labeled UPDATE-preview block for EXISTING rows whose
    sheet-supplied credentials differ from the database. All password values
    in any SQL are bcrypt hashes, generated with this app's own
    hash_password() (app/security.py) — the exact mechanism the real
    POST /api/users and POST /api/users/{id}/reset-password endpoints use.

WHAT THIS SCRIPT NEVER DOES:
  - Never writes to the database. Every DB query here is a SELECT.
  - Never applies a username or password change automatically — a sheet row
    that proposes different credentials for an existing user is reported as
    a "credential change request" with a ready-to-review (not auto-run) SQL
    statement. Nothing is executed.
  - Never invents an Arabic name. name_ar is a required, NOT NULL column
    (models.py) with no safe way to derive it from an English name, so any
    new row missing it is held at NEW_NEEDS_REVIEW rather than guessed.
  - Never prints a plaintext password anywhere this script's own output goes
    (stdout, the Markdown report, or any SQL file) — not for passwords the
    sheet supplies, and not for the ones this script itself generates for
    brand-new users lacking a sheet password (those go ONLY into a separate
    'TEMP_PASSWORDS_*.txt' file, gitignored, never echoed back).

USAGE:
    cd backend
    "C:\\Program Files\\Python311\\python.exe" provision_users_from_excel.py [--excel PATH]

Output files land next to this script, all gitignored:
    provisioning_report_<timestamp>.md
    provisioning_preview_<timestamp>.sql   (created if there's at least one
                                             NEW_READY row or credential
                                             change request)
    TEMP_PASSWORDS_<timestamp>.txt         (created only if this script had
                                             to invent a password itself,
                                             i.e. a NEW_READY row with no
                                             sheet-supplied password)

This script only ever produces files for a human to review. It has no
"--apply" mode by design — applying the result is a separate, explicit,
later step (either by running the reviewed SQL by hand, or, preferably, by
using the existing admin UI, which is wired to the same hashing/validation/
audit-log path).
"""

import re
import secrets
import string
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import openpyxl  # noqa: E402
from sqlalchemy.orm import joinedload  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Role, User  # noqa: E402
from app.security import hash_password  # noqa: E402

DEFAULT_EXCEL_PATH = Path(__file__).parent.parent / "DB.xlsx"
MIN_PASSWORD_LENGTH = 6  # matches the only length convention this app already has (js/pages/users.js reset-password inputs use minlength="6")

# Recognized header aliases -> canonical field name. Matching is
# case-insensitive and whitespace-trimmed. Unrecognized columns are not
# dropped silently — they're listed in the report so nothing is missed.
HEADER_ALIASES = {
    "name_en": {"name", "full name", "name (english)", "name_en", "english name"},
    "name_ar": {"name (arabic)", "arabic name", "name_ar", "الاسم"},
    "occupation": {"occupation", "job title", "occupation "},
    "role_code": {"role", "role_code", "role code"},
    "username": {"username", "login", "user name"},
    "password": {"password", "pass", "pwd"},
    "email": {"email", "e-mail"},
    "civil_id": {"civil id", "civilid", "civil_id"},
    "is_owner": {"owner", "is owner", "is_owner"},
}


def _normalize_header(h) -> str:
    return str(h or "").strip().lower()


def _normalize_name(n) -> str:
    return re.sub(r"\s+", " ", str(n or "").strip()).lower()


def _suggest_username(name_en: str) -> str:
    parts = re.sub(r"[^A-Za-z\s]", "", name_en).split()
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0]}.{parts[-1]}".lower()


def _gen_temp_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _sql_str(v) -> str:
    if v is None:
        return "NULL"
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def load_excel_rows(path: Path) -> tuple[list[dict], list[str], list[str]]:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter)

    col_map: dict[int, str] = {}
    unrecognized_headers: list[str] = []
    for idx, h in enumerate(raw_headers):
        norm = _normalize_header(h)
        if not norm:
            continue
        mapped = None
        for canonical, aliases in HEADER_ALIASES.items():
            if norm in aliases:
                mapped = canonical
                break
        if mapped:
            col_map[idx] = mapped
        else:
            unrecognized_headers.append(str(h))

    records = []
    for row in rows_iter:
        if row is None or all(v is None or str(v).strip() == "" for v in row):
            continue
        rec = {}
        for idx, canonical in col_map.items():
            rec[canonical] = row[idx] if idx < len(row) else None
        records.append(rec)

    return records, list(col_map.values()), unrecognized_headers


def main():
    excel_path = DEFAULT_EXCEL_PATH
    if "--excel" in sys.argv:
        excel_path = Path(sys.argv[sys.argv.index("--excel") + 1])

    if not excel_path.exists():
        print(f"ERROR: Excel file not found at {excel_path}")
        sys.exit(1)

    records, detected_fields, unrecognized_headers = load_excel_rows(excel_path)

    db = SessionLocal()
    try:
        valid_role_codes = {r.code for r in db.query(Role).all()}
        existing_users = db.query(User).options(joinedload(User.role)).all()
        existing_by_name = {_normalize_name(u.name_en): u for u in existing_users}
        existing_by_username = {u.username.lower(): u for u in existing_users}
    finally:
        db.close()

    seen_names_in_sheet: dict[str, int] = {}
    seen_usernames_in_sheet: dict[str, int] = {}

    results = {"EXISTING": [], "INVALID": [], "NEW_NEEDS_REVIEW": [], "NEW_READY": []}
    # Existing users whose sheet row proposes a different username, password,
    # role, and/or occupation than what's currently in the database. Covers
    # both "credential" changes (username/password) and "profile" changes
    # (role/occupation) — kept in one list since a single sheet row commonly
    # proposes more than one at once, and they end up as one UPDATE statement.
    proposed_changes = []

    for i, rec in enumerate(records, start=2):  # row 2 = first data row (1 = header)
        name_en = str(rec.get("name_en") or "").strip()
        role_code = str(rec.get("role_code") or "").strip()
        occupation = str(rec.get("occupation") or "").strip() or None
        name_ar = str(rec.get("name_ar") or "").strip() or None
        sheet_username = str(rec.get("username") or "").strip() or None
        sheet_password = rec.get("password")
        sheet_password = str(sheet_password).strip() if sheet_password not in (None, "") else None
        email = str(rec.get("email") or "").strip() or None
        civil_id = str(rec.get("civil_id") or "").strip() or None

        row_ref = f"row {i}"
        password_issue = None
        if sheet_password is not None and len(sheet_password) < MIN_PASSWORD_LENGTH:
            password_issue = f"password is only {len(sheet_password)} chars (minimum {MIN_PASSWORD_LENGTH}, matching this app's existing reset-password convention)"

        if not name_en:
            results["INVALID"].append({"row": row_ref, "reason": "missing Name"})
            continue
        if not role_code:
            results["INVALID"].append({"row": row_ref, "name_en": name_en, "reason": "missing Role"})
            continue
        if role_code not in valid_role_codes:
            results["INVALID"].append({
                "row": row_ref, "name_en": name_en,
                "reason": f"unknown role '{role_code}' — not one of the application's real role codes: {sorted(valid_role_codes)}",
            })
            continue

        norm_name = _normalize_name(name_en)
        if norm_name in seen_names_in_sheet:
            results["INVALID"].append({
                "row": row_ref, "name_en": name_en,
                "reason": f"duplicate of row {seen_names_in_sheet[norm_name]} within DB.xlsx itself",
            })
            continue
        seen_names_in_sheet[norm_name] = i

        # Existing-user match is by NAME, deliberately — matching by the
        # sheet's own username column would be circular here, since the
        # whole point of this run is that the sheet's usernames may not be
        # the ones already on file for these people.
        existing = existing_by_name.get(norm_name)

        if existing:
            username_changes = bool(sheet_username) and sheet_username.lower() != existing.username.lower()
            password_change_requested = sheet_password is not None
            role_changes = role_code != existing.role.code
            occupation_changes = bool(occupation) and existing.occupation is not None and occupation != existing.occupation

            results["EXISTING"].append({
                "row": row_ref, "name_en": name_en, "existing_id": existing.id,
                "existing_username": existing.username,
                "drift": (
                    ([f"username differs (sheet: '{sheet_username}', db: '{existing.username}')"] if username_changes else [])
                    + (["password change requested"] if password_change_requested else [])
                    + ([f"occupation differs (sheet: '{occupation}', db: '{existing.occupation}')"] if occupation_changes else [])
                    + ([f"role differs (sheet: '{role_code}', db: '{existing.role.code}')"] if role_changes else [])
                ),
            })

            if username_changes or password_change_requested or role_changes or occupation_changes:
                # A username collision check only matters if the sheet is
                # actually proposing to change it to something new.
                collision = None
                if username_changes:
                    other = existing_by_username.get(sheet_username.lower())
                    if other and other.id != existing.id:
                        collision = f"'{sheet_username}' is already the username of a DIFFERENT existing user (id={other.id}, {other.name_en})"
                    other_in_sheet = seen_usernames_in_sheet.get(sheet_username.lower())
                    if other_in_sheet and other_in_sheet != i:
                        collision = f"'{sheet_username}' is also proposed at row {other_in_sheet} in this same sheet"
                proposed_changes.append({
                    "row": row_ref, "name_en": name_en, "existing_id": existing.id,
                    "current_username": existing.username,
                    "proposed_username": sheet_username if username_changes else None,
                    "password_change_requested": password_change_requested,
                    "password_issue": password_issue,
                    "collision": collision,
                    "sheet_password": sheet_password,  # kept in memory only; never printed/written raw
                    "proposed_role_code": role_code if role_changes else None,
                    "current_role_code": existing.role.code,
                    "proposed_occupation": occupation if occupation_changes else None,
                    "current_occupation": existing.occupation,
                })
            if sheet_username:
                seen_usernames_in_sheet.setdefault(sheet_username.lower(), i)
            continue

        # Genuinely new candidate (no existing user matches this name).
        if sheet_username:
            norm_username = sheet_username.lower()
            if norm_username in seen_usernames_in_sheet:
                results["INVALID"].append({
                    "row": row_ref, "name_en": name_en,
                    "reason": f"duplicate username '{sheet_username}' also used at row {seen_usernames_in_sheet[norm_username]}",
                })
                continue
            if norm_username in existing_by_username:
                results["INVALID"].append({
                    "row": row_ref, "name_en": name_en,
                    "reason": f"username '{sheet_username}' already belongs to a different existing user",
                })
                continue
            seen_usernames_in_sheet[norm_username] = i

        if not name_ar:
            results["NEW_NEEDS_REVIEW"].append({
                "row": row_ref, "name_en": name_en, "role_code": role_code, "occupation": occupation,
                "reason": "no Arabic name column in the sheet — name_ar is required (NOT NULL) and cannot be safely guessed from the English name",
            })
            continue

        if password_issue:
            results["NEW_NEEDS_REVIEW"].append({
                "row": row_ref, "name_en": name_en, "role_code": role_code, "occupation": occupation,
                "reason": password_issue,
            })
            continue

        username = sheet_username
        username_note = "from sheet"
        if not username:
            username = _suggest_username(name_en)
            username_note = "auto-suggested (firstname.lastname convention used by backend/seed.py) — please confirm before use"
            if username.lower() in existing_by_username or username.lower() in seen_usernames_in_sheet:
                suffix = 2
                while f"{username}{suffix}".lower() in existing_by_username or f"{username}{suffix}".lower() in seen_usernames_in_sheet:
                    suffix += 1
                username = f"{username}{suffix}"
                username_note += " (disambiguated to avoid collision with an existing/other-new username)"
        seen_usernames_in_sheet[username.lower()] = i

        results["NEW_READY"].append({
            "row": row_ref, "name_en": name_en, "name_ar": name_ar, "role_code": role_code,
            "occupation": occupation, "email": email, "civil_id": civil_id,
            "username": username, "username_note": username_note,
            "sheet_password": sheet_password,  # in memory only
        })

    # ---- write report ----
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(__file__).parent
    report_path = out_dir / f"provisioning_report_{ts}.md"

    lines = []
    lines.append(f"# User Provisioning Report — {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(f"Source: `{excel_path}`")
    lines.append(f"Detected/mapped columns: {', '.join(sorted(set(detected_fields))) or '(none)'}")
    if unrecognized_headers:
        lines.append(f"Unrecognized columns (ignored, not silently mapped): {', '.join(unrecognized_headers)}")
    lines.append(f"Valid role codes in the live database: {sorted(valid_role_codes)}")
    lines.append(f"Current user count in the database: {len(existing_users)}")
    lines.append("")

    lines.append(f"## EXISTING ({len(results['EXISTING'])}) — matched by name; nothing changed automatically")
    for r in results["EXISTING"]:
        drift_note = f" ⚠ {'; '.join(r['drift'])}" if r["drift"] else ""
        lines.append(f"- {r['row']}: **{r['name_en']}** matches existing user id={r['existing_id']} (`{r['existing_username']}`){drift_note}")
    lines.append("")

    lines.append(f"## PROPOSED CHANGES — CREDENTIALS/PROFILE/ROLE ({len(proposed_changes)}) — NOT applied; review the SQL preview and apply manually if intended")
    if proposed_changes:
        lines.append("The sheet proposes different username/password/role/occupation values for these already-existing users. Nothing has been changed — this is a proposal only.")
        for r in proposed_changes:
            parts = []
            if r["proposed_username"]:
                parts.append(f"username `{r['current_username']}` → `{r['proposed_username']}`")
            if r["password_change_requested"]:
                parts.append("password change requested (hash-only preview in .sql; plaintext never written anywhere by this script)")
            if r["proposed_role_code"]:
                parts.append(f"role `{r['current_role_code']}` → `{r['proposed_role_code']}`")
            if r["proposed_occupation"]:
                parts.append(f"occupation `{r['current_occupation']}` → `{r['proposed_occupation']}`")
            note = "; ".join(parts)
            warn = ""
            if r["collision"]:
                warn += f" ⚠ COLLISION: {r['collision']} — this row's username change is EXCLUDED from the SQL preview."
            if r["password_issue"]:
                warn += f" ⚠ {r['password_issue']} — this row's password change is EXCLUDED from the SQL preview."
            lines.append(f"- {r['row']}: **{r['name_en']}** (id={r['existing_id']}) — {note}{warn}")
    else:
        lines.append("(none)")
    admin_username_rows = [r for r in proposed_changes if r["proposed_username"] and r["proposed_username"].lower() == "admin"]
    if admin_username_rows:
        lines.append("")
        lines.append(
            f"⚠ NAMING AMBIGUITY (not changed, flagged only): {admin_username_rows[0]['row']} proposes the literal "
            f"username `{admin_username_rows[0]['proposed_username']}`, which is also this application's role code for "
            "administrators. This works technically (usernames and role codes are unrelated columns) but is confusing "
            "and worth reconsidering — left exactly as supplied in the sheet."
        )
    lines.append("")

    lines.append(f"## INVALID ({len(results['INVALID'])})")
    for r in results["INVALID"]:
        lines.append(f"- {r['row']}" + (f" ({r['name_en']})" if "name_en" in r else "") + f": {r['reason']}")
    lines.append("")

    lines.append(f"## NEW — NEEDS REVIEW ({len(results['NEW_NEEDS_REVIEW'])}) — not in the database, but missing/invalid data this script will not guess")
    for r in results["NEW_NEEDS_REVIEW"]:
        lines.append(f"- {r['row']}: **{r['name_en']}** (role: {r['role_code']}) — {r['reason']}")
    lines.append("")

    lines.append(f"## NEW — READY ({len(results['NEW_READY'])}) — see the accompanying .sql preview")
    for r in results["NEW_READY"]:
        pw_note = "password from sheet (hashed in SQL)" if r["sheet_password"] else "no sheet password — a temporary one will be generated"
        lines.append(f"- {r['row']}: **{r['name_en']}** → username `{r['username']}` ({r['username_note']}), role `{r['role_code']}`, {pw_note}")
    lines.append("")

    needs_temp_passwords = any(not r["sheet_password"] for r in results["NEW_READY"])
    if results["NEW_READY"] and needs_temp_passwords:
        lines.append(f"A temporary password was generated for any NEW-READY row with no sheet-supplied password. Plaintext values are written ONLY to `TEMP_PASSWORDS_{ts}.txt` (gitignored) — never to this report or to chat. Distribute out-of-band and have each user change it on first login.")
    if not results["NEW_READY"] and not proposed_changes:
        lines.append("Nothing to insert or update this run.")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    sql_lines = []
    pw_lines = []
    if results["NEW_READY"] or proposed_changes:
        sql_lines = [
            "-- Ready-to-review SQL, generated by provision_users_from_excel.py.",
            "-- Do NOT run this automatically. Review every statement, then execute",
            "-- manually if you choose this path — or, preferably, apply each change",
            "-- through the existing admin UI (Users & Permissions page), which",
            "-- exercises the exact same validation/hashing/audit-log path.",
            "-- All password values below are bcrypt hashes (app/security.py's own",
            "-- hash_password()) — never plaintext.",
            "",
        ]

        db2 = SessionLocal()
        try:
            role_id_by_code = {r.code: r.id for r in db2.query(Role).all()}
        finally:
            db2.close()

        if results["NEW_READY"]:
            sql_lines.append("-- ===== NEW USERS (INSERT) =====")
            sql_lines.append("")
            for r in results["NEW_READY"]:
                if r["sheet_password"]:
                    plain_pw, pw_source = r["sheet_password"], "from sheet"
                else:
                    plain_pw, pw_source = _gen_temp_password(), "generated"
                    pw_lines.append(f"{r['username']}: {plain_pw}")
                pw_hash = hash_password(plain_pw)
                role_id = role_id_by_code[r["role_code"]]
                sql_lines.append(f"-- {r['row']}: {r['name_en']} ({r['username']}) — password {pw_source}")
                sql_lines.append(
                    "INSERT INTO users (name_en, name_ar, username, email, occupation, role_id, civil_id, is_owner, password_hash, is_active) VALUES ("
                    f"{_sql_str(r['name_en'])}, {_sql_str(r['name_ar'])}, {_sql_str(r['username'])}, "
                    f"{_sql_str(r['email'])}, {_sql_str(r['occupation'])}, {role_id}, {_sql_str(r['civil_id'])}, 0, "
                    f"{_sql_str(pw_hash)}, 1);"
                )
                sql_lines.append("")

        applicable_changes = [
            r for r in proposed_changes
            if (r["proposed_username"] and not r["collision"])
            or (r["password_change_requested"] and not r["password_issue"])
            or r["proposed_role_code"]
            or r["proposed_occupation"]
        ]
        if applicable_changes:
            sql_lines.append("-- ===== EXISTING USERS — PROPOSED CHANGES (review before running!) =====")
            sql_lines.append("-- Each statement only touches the field(s) actually proposed by the sheet.")
            sql_lines.append("")
            for r in applicable_changes:
                sets = []
                if r["proposed_username"] and not r["collision"]:
                    sets.append(f"username = {_sql_str(r['proposed_username'])}")
                if r["password_change_requested"] and not r["password_issue"]:
                    sets.append(f"password_hash = {_sql_str(hash_password(r['sheet_password']))}")
                if r["proposed_role_code"]:
                    sets.append(f"role_id = {role_id_by_code[r['proposed_role_code']]}")
                if r["proposed_occupation"]:
                    sets.append(f"occupation = {_sql_str(r['proposed_occupation'])}")
                sql_lines.append(f"-- {r['row']}: {r['name_en']} (id={r['existing_id']}, currently `{r['current_username']}`)")
                sql_lines.append(f"UPDATE users SET {', '.join(sets)} WHERE id = {r['existing_id']};")
                sql_lines.append("")

        sql_path = out_dir / f"provisioning_preview_{ts}.sql"
        sql_path.write_text("\n".join(sql_lines), encoding="utf-8")
        print(f"Wrote {sql_path}")

        if pw_lines:
            pw_path = out_dir / f"TEMP_PASSWORDS_{ts}.txt"
            pw_path.write_text(
                "\n".join([
                    f"Temporary passwords generated {datetime.now().isoformat(timespec='seconds')} — DO NOT COMMIT.",
                    "These are for NEW_READY rows that had no password in the sheet.",
                    "Distribute out-of-band; delete this file once distributed.",
                    "",
                    *pw_lines,
                ]),
                encoding="utf-8",
            )
            print(f"Wrote {pw_path} (plaintext temp passwords — do not commit, distribute out-of-band)")

    print(f"Wrote {report_path}")
    print()
    print(f"EXISTING: {len(results['EXISTING'])}  PROPOSED_CHANGES: {len(proposed_changes)}  "
          f"INVALID: {len(results['INVALID'])}  NEW_NEEDS_REVIEW: {len(results['NEW_NEEDS_REVIEW'])}  "
          f"NEW_READY: {len(results['NEW_READY'])}")
    print("SQL executed against the database: NO (this script never writes to the database)")


if __name__ == "__main__":
    main()
