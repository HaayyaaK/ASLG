import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..config import settings
from ..database import get_db
from ..deps import get_current_user, get_permission_level, require_module
from ..escalation import notify_document_reviewed
from ..models import Case, Document, DocumentUploadGrant, Role, User, UserCaseLink
from ..schemas import DocumentOut, DocumentReviewRequest, GrantUploadRequest, UploadGrantOut

router = APIRouter(prefix="/api/documents", tags=["documents"])

ALLOWED_TYPES = {"pdf", "docx", "doc", "jpg", "jpeg", "png"}


def _linked_case_ids(db: Session, user: User) -> set[int]:
    return {
        row.case_id
        for row in db.query(UserCaseLink.case_id)
        .filter(UserCaseLink.user_id == user.id, UserCaseLink.status == "active")
        .all()
    }


def _scope_query(db: Session, user: User):
    q = db.query(Document).options(joinedload(Document.case), joinedload(Document.uploader))
    level = get_permission_level(db, user.role_id, "documents")
    if level == "own":
        # Same union-of-ids approach as cases.py's _scope_query, for the same
        # reason: filtering by Document.case_id.in_(...) against a plain id
        # set can never return a document twice, where joining user_case_links
        # directly into this query could.
        civil_ids = (
            {c.id for c in db.query(Case.id).filter(Case.civil_id == user.civil_id).all()}
            if user.civil_id
            else set()
        )
        allowed_case_ids = civil_ids | _linked_case_ids(db, user)
        return q.filter(Document.case_id.in_(allowed_case_ids)) if allowed_case_ids else q.filter(False)
    return q


def _to_out(d: Document) -> DocumentOut:
    return DocumentOut(
        id=d.id, case_id=d.case_id, case_number=f"{d.case.case_number}/{d.case.case_year}", file_name=d.file_name,
        file_type=d.file_type, file_size=d.file_size, status=d.status, uploaded_by=d.uploaded_by,
        uploaded_by_name_ar=d.uploader.name_ar, uploaded_by_name_en=d.uploader.name_en, uploaded_at=d.uploaded_at,
    )


def _grant_to_out(g: DocumentUploadGrant) -> UploadGrantOut:
    return UploadGrantOut(
        id=g.id, case_id=g.case_id, case_number=f"{g.case.case_number}/{g.case.case_year}",
        client_user_id=g.client_user_id, client_name_ar=g.client.name_ar, client_name_en=g.client.name_en,
        granted_by=g.granted_by, granted_by_name_ar=g.granter.name_ar, granted_by_name_en=g.granter.name_en,
        granted_at=g.granted_at, expires_at=g.expires_at, used_at=g.used_at, status=g.status, source="grant",
    )


def _link_to_grant_out(link: "UserCaseLink") -> UploadGrantOut:
    """Renders a standing UserCaseLink.can_upload permission through the same
    UploadGrantOut shape the client's dropzone banner already reads, so the
    frontend has one response shape for both upload-access sources."""
    return UploadGrantOut(
        id=link.id, case_id=link.case_id, case_number=f"{link.case.case_number}/{link.case.case_year}",
        client_user_id=link.user_id, client_name_ar=link.user.name_ar, client_name_en=link.user.name_en,
        granted_by=link.linked_by, granted_by_name_ar=link.linker.name_ar if link.linker else "",
        granted_by_name_en=link.linker.name_en if link.linker else "",
        granted_at=link.linked_at, expires_at=link.can_upload_until, used_at=None, status="active",
        source="link",
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(user: User = Depends(require_module("documents")), db: Session = Depends(get_db)):
    docs = _scope_query(db, user).order_by(Document.uploaded_at.desc()).all()
    return [_to_out(d) for d in docs]


# ---------------- Upload grants (clients are blocked from uploading by default) ----------------


@router.post("/grants", response_model=UploadGrantOut, status_code=status.HTTP_201_CREATED)
def grant_upload_access(
    payload: GrantUploadRequest,
    user: User = Depends(require_module("documents", "full", "edit")),
    db: Session = Depends(get_db),
):
    case = db.get(Case, payload.case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if not case.civil_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This case has no linked client civil ID")
    client = (
        db.query(User).join(Role).filter(Role.code == "User", User.civil_id == case.civil_id).first()
    )
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No client account is linked to this case")
    if payload.duration_minutes < 1 or payload.duration_minutes > 24 * 60:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "duration_minutes must be between 1 and 1440")

    # Superseding any still-active grant for this case+client keeps exactly one live window.
    db.query(DocumentUploadGrant).filter(
        DocumentUploadGrant.case_id == case.id,
        DocumentUploadGrant.client_user_id == client.id,
        DocumentUploadGrant.status == "active",
    ).update({DocumentUploadGrant.status: "revoked"}, synchronize_session=False)

    grant = DocumentUploadGrant(
        case_id=case.id, client_user_id=client.id, granted_by=user.id,
        expires_at=datetime.utcnow() + timedelta(minutes=payload.duration_minutes),
    )
    db.add(grant)
    db.commit()
    db.refresh(grant)
    log_activity(
        db, user.id, "document_grant_access", entity_type="case", entity_id=case.id,
        meta={"client_user_id": client.id, "duration_minutes": payload.duration_minutes},
    )
    return _grant_to_out(grant)


@router.get("/grants", response_model=list[UploadGrantOut])
def list_upload_grants(
    case_id: int | None = Query(None),
    user: User = Depends(require_module("documents", "full", "edit")),
    db: Session = Depends(get_db),
):
    q = db.query(DocumentUploadGrant).options(
        joinedload(DocumentUploadGrant.case), joinedload(DocumentUploadGrant.client), joinedload(DocumentUploadGrant.granter)
    )
    if case_id is not None:
        q = q.filter(DocumentUploadGrant.case_id == case_id)
    rows = q.order_by(DocumentUploadGrant.granted_at.desc()).limit(50).all()
    return [_grant_to_out(g) for g in rows]


@router.get("/my-upload-access", response_model=list[UploadGrantOut])
def my_upload_access(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Lets a client's UI know which of their case(s), if any, they may
    currently upload to — combines the one-time grant window an
    Admin/Lawyer/Consultant opened (source="grant") with any standing
    UserCaseLink.can_upload permission (source="link"). A client can have
    both kinds active on different cases at once, so this returns every row
    that currently allows an upload, not just one."""
    grants = (
        db.query(DocumentUploadGrant)
        .options(joinedload(DocumentUploadGrant.case), joinedload(DocumentUploadGrant.client), joinedload(DocumentUploadGrant.granter))
        .filter(
            DocumentUploadGrant.client_user_id == user.id,
            DocumentUploadGrant.status == "active",
            DocumentUploadGrant.expires_at > datetime.utcnow(),
        )
        .all()
    )
    links = (
        db.query(UserCaseLink)
        .options(joinedload(UserCaseLink.case), joinedload(UserCaseLink.user), joinedload(UserCaseLink.linker))
        .filter(
            UserCaseLink.user_id == user.id,
            UserCaseLink.status == "active",
            UserCaseLink.can_upload == True,  # noqa: E712
            (UserCaseLink.can_upload_until.is_(None)) | (UserCaseLink.can_upload_until > datetime.utcnow()),
        )
        .all()
    )
    return [_grant_to_out(g) for g in grants] + [_link_to_grant_out(l) for l in links]


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    case_id: int = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")

    level = get_permission_level(db, user.role_id, "documents")
    consumed_grant: DocumentUploadGrant | None = None

    if level in ("full", "edit"):
        pass  # staff — always allowed
    elif level == "own":
        # Clients are blocked by default. Two independent ways through:
        # a one-time grant (consumed below), or a standing can_upload link
        # (never consumed — stays usable until an Admin/Lawyer revokes it or
        # its own can_upload_until passes). Checked in this order only
        # because the grant is the one that needs to be marked "used"; a
        # standing link needs no bookkeeping on a successful upload at all.
        consumed_grant = (
            db.query(DocumentUploadGrant)
            .filter(
                DocumentUploadGrant.case_id == case_id,
                DocumentUploadGrant.client_user_id == user.id,
                DocumentUploadGrant.status == "active",
                DocumentUploadGrant.expires_at > datetime.utcnow(),
            )
            .first()
        )
        if consumed_grant is None:
            has_standing_link = (
                db.query(UserCaseLink)
                .filter(
                    UserCaseLink.case_id == case_id,
                    UserCaseLink.user_id == user.id,
                    UserCaseLink.status == "active",
                    UserCaseLink.can_upload == True,  # noqa: E712
                    (UserCaseLink.can_upload_until.is_(None)) | (UserCaseLink.can_upload_until > datetime.utcnow()),
                )
                .first()
                is not None
            )
            if not has_standing_link:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "You don't have upload permission for this case. Ask your lawyer to grant access.",
                )
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to 'documents'")

    ext = (file.filename.rsplit(".", 1)[-1] if "." in file.filename else "").lower()
    if ext not in ALLOWED_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported file type")

    contents = await file.read()
    max_bytes = settings.max_upload_mb * 1024 * 1024
    if len(contents) > max_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File exceeds {settings.max_upload_mb}MB limit")

    case_dir = settings.upload_path / str(case_id)
    case_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    dest = case_dir / stored_name
    dest.write_bytes(contents)

    doc = Document(
        case_id=case_id, file_name=file.filename, file_type=ext, file_size=len(contents),
        storage_path=str(dest), uploaded_by=user.id, status="pending",
    )
    db.add(doc)

    if consumed_grant is not None:
        # One successful upload spends the grant — access reverts to blocked automatically.
        consumed_grant.status = "used"
        consumed_grant.used_at = datetime.utcnow()

    db.commit()
    db.refresh(doc)
    log_activity(
        db, user.id, "document_upload", entity_type="document", entity_id=doc.id,
        meta={"file_name": doc.file_name, "case_id": case_id},
    )
    return _to_out(doc)


@router.get("/{doc_id}/download")
def download_document(doc_id: int, user: User = Depends(require_module("documents")), db: Session = Depends(get_db)):
    doc = _scope_query(db, user).filter(Document.id == doc_id).first()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = Path(doc.storage_path)
    if not path.exists():
        raise HTTPException(status.HTTP_410_GONE, "File missing from storage")
    log_activity(db, user.id, "document_download", entity_type="document", entity_id=doc.id, meta={"file_name": doc.file_name})
    return FileResponse(path, filename=doc.file_name)


REVIEW_STATUSES = ("approved", "rejected")


@router.put("/{doc_id}/status", response_model=DocumentOut)
def review_document(
    doc_id: int,
    payload: DocumentReviewRequest,
    # "full" is deliberately narrower than the "full"/"edit" used for upload and
    # delete: only Admin and Lawyer hold documents="full". Consultants and
    # Delegates can put documents in and take them out, but signing a document
    # off as reviewed is the case owner's call, not support staff's.
    user: User = Depends(require_module("documents", "full")),
    db: Session = Depends(get_db),
):
    if payload.status not in REVIEW_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"status must be one of {REVIEW_STATUSES}")

    doc = _scope_query(db, user).filter(Document.id == doc_id).first()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    # Re-applying the status a document already has is a no-op, not an error:
    # two reviewers clicking Approve on the same row must not produce two audit
    # entries and two notifications for one real decision.
    if doc.status == payload.status:
        return _to_out(doc)

    reason = (payload.reason or "").strip()[:300] or None
    previous = doc.status
    doc.status = payload.status
    case_label = f"{doc.case.case_number}/{doc.case.case_year}"
    file_name = doc.file_name
    uploader_id = doc.uploaded_by
    db.commit()
    db.refresh(doc)

    log_activity(
        db, user.id,
        "document_approve" if payload.status == "approved" else "document_reject",
        entity_type="document", entity_id=doc.id,
        meta={"file_name": file_name, "case": case_label, "from": previous, "to": payload.status, "reason": reason},
    )

    # Reviewing your own upload notifies nobody — you already know.
    if uploader_id != user.id:
        notify_document_reviewed(
            db,
            recipient_id=uploader_id,
            file_name=file_name,
            case_label=case_label,
            new_status=payload.status,
            reviewer_name=user.name_en or user.name_ar,
            reason=reason,
        )

    return _to_out(doc)


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(doc_id: int, user: User = Depends(require_module("documents", "full", "edit")), db: Session = Depends(get_db)):
    doc = _scope_query(db, user).filter(Document.id == doc_id).first()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = Path(doc.storage_path)
    if path.exists():
        path.unlink()
    file_name = doc.file_name
    db.delete(doc)
    db.commit()
    log_activity(db, user.id, "document_delete", entity_type="document", entity_id=doc_id, meta={"file_name": file_name})
