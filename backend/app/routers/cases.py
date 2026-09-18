from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from datetime import datetime

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user, get_permission_level, require_module
from ..escalation import notify_case_note_added, notify_case_stage_changed
from ..models import Case, CaseNote, CaseTimeline, CaseWatcher, Court, Role, User, UserCaseLink
from ..schemas import (
    AssignableUserOut,
    CaseCreateRequest,
    CaseDetailOut,
    CaseNoteCreateRequest,
    CaseNoteOut,
    CaseOut,
    CaseStageUpdateRequest,
    CaseTimelineOut,
    CourtOut,
    LinkUserRequest,
    UserCaseLinkOut,
)

router = APIRouter(prefix="/api/cases", tags=["cases"])

STAGES = ("new", "prep", "pleading", "judgment", "execution", "closed")


def _linked_case_ids(db: Session, user: User) -> set[int]:
    return {
        row.case_id
        for row in db.query(UserCaseLink.case_id)
        .filter(UserCaseLink.user_id == user.id, UserCaseLink.status == "active")
        .all()
    }


def _scope_query(db: Session, user: User):
    q = db.query(Case).options(joinedload(Case.court), joinedload(Case.assigned_lawyer))
    level = get_permission_level(db, user.role_id, "cases")
    if level == "own":
        # Union, computed as plain id sets, of the original civil_id match and
        # any explicit user_case_links — then filtered with a single
        # `Case.id.in_(...)` against the base `cases` table. Deliberately not
        # a JOIN against user_case_links: joining it here would return a
        # case's row once per matching link, duplicating it for anyone linked
        # more than one way (civil_id AND an explicit link).
        civil_ids = (
            {c.id for c in db.query(Case.id).filter(Case.civil_id == user.civil_id).all()}
            if user.civil_id
            else set()
        )
        allowed_ids = civil_ids | _linked_case_ids(db, user)
        return q.filter(Case.id.in_(allowed_ids)) if allowed_ids else q.filter(False)
    return q


def _to_out(c: Case, watching_ids: set[int]) -> CaseOut:
    return CaseOut(
        id=c.id, case_number=c.case_number, automated_number=c.automated_number,
        case_year=c.case_year,
        court_name_ar=c.court.name_ar, court_name_en=c.court.name_en,
        category_ar=c.category_ar, category_en=c.category_en,
        parties_ar=c.parties_ar, parties_en=c.parties_en, civil_id=c.civil_id,
        status=c.status, stage=c.stage, assigned_lawyer_id=c.assigned_lawyer_id,
        assigned_lawyer_name_ar=c.assigned_lawyer.name_ar if c.assigned_lawyer else None,
        assigned_lawyer_name_en=c.assigned_lawyer.name_en if c.assigned_lawyer else None,
        summary_ar=c.summary_ar, summary_en=c.summary_en, next_hearing_at=c.next_hearing_at,
        is_watching=c.id in watching_ids, created_at=c.created_at,
    )


def _watching_ids(db: Session, user: User) -> set[int]:
    rows = db.query(CaseWatcher.case_id).filter(CaseWatcher.user_id == user.id).all()
    return {r[0] for r in rows}


@router.get("", response_model=list[CaseOut])
def list_cases(user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    cases = _scope_query(db, user).order_by(Case.next_hearing_at.is_(None), Case.next_hearing_at).all()
    watching = _watching_ids(db, user)
    return [_to_out(c, watching) for c in cases]


@router.get("/courts", response_model=list[CourtOut])
def list_courts(user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    """Powers the court dropdown on the New Case form."""
    return db.query(Court).order_by(Court.name_en).all()


@router.get("/assignable-lawyers", response_model=list[AssignableUserOut])
def list_case_lawyers(user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    """Powers the "Assigned Lawyer" dropdown on the New Case form. Deliberately
    broader than reminders.py's assignable-users list (which is restricted to
    firm owners) — anyone who can create/edit a case should be able to see
    which lawyers exist to assign it to."""
    rows = (
        db.query(User)
        .join(Role)
        .filter(Role.code == "Lawyer", User.is_active == True)  # noqa: E712
        .order_by(User.name_en)
        .all()
    )
    return [AssignableUserOut(id=u.id, name_ar=u.name_ar, name_en=u.name_en, role_code=u.role.code) for u in rows]


@router.get("/linkable-clients", response_model=list[AssignableUserOut])
def list_linkable_clients(user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    """Powers the "Link a user" picker in the Case Details modal. Narrow and
    purpose-built like `list_case_lawyers` above, rather than gated behind the
    full Users module (`users: none` for the Lawyer role, who must still be
    able to link their own case's clients)."""
    rows = (
        db.query(User)
        .join(Role)
        .filter(Role.code == "User", User.is_active == True)  # noqa: E712
        .order_by(User.name_en)
        .all()
    )
    return [AssignableUserOut(id=u.id, name_ar=u.name_ar, name_en=u.name_en, role_code=u.role.code) for u in rows]


@router.post("", response_model=CaseOut, status_code=status.HTTP_201_CREATED)
def create_case(payload: CaseCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _assert_can_edit(db, user)

    court = db.get(Court, payload.court_id)
    if court is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid court")

    # Always present now (CaseCreateRequest makes it required). The active
    # check makes this match its own message: it used to accept a
    # deactivated lawyer, which the New Case dropdown never offers.
    lawyer = db.get(User, payload.assigned_lawyer_id)
    if lawyer is None or lawyer.role.code != "Lawyer" or not lawyer.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "assigned_lawyer_id must reference an active Lawyer")

    if payload.stage not in STAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid stage '{payload.stage}'")

    # `payload.case_year` is not the client's copy: CaseCreateRequest's
    # model validator re-derives it from automated_number's first four
    # digits and rejects a mismatch, so by the time it reaches here it is
    # the server's own value. Both duplicate checks below therefore run
    # against trusted data.
    existing = (
        db.query(Case)
        .filter(Case.case_number == payload.case_number, Case.case_year == payload.case_year)
        .first()
    )
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "A case with this number and year already exists")

    # Checked explicitly rather than left to uq_cases_automated_number: the
    # bare IntegrityError from the database surfaces as a 500, and "this
    # Automated Number is already on another case" is a routine, correctable
    # user mistake that deserves a 409 with a message naming the field.
    duplicate_auto = (
        db.query(Case).filter(Case.automated_number == payload.automated_number).first()
    )
    if duplicate_auto:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Automated Number {payload.automated_number} is already used by case "
            f"{duplicate_auto.case_number}/{duplicate_auto.case_year}",
        )

    case = Case(
        case_number=payload.case_number,
        automated_number=payload.automated_number,
        case_year=payload.case_year,
        court_id=payload.court_id,
        category_ar=payload.category_ar,
        category_en=payload.category_en,
        parties_ar=payload.parties_ar,
        parties_en=payload.parties_en,
        civil_id=payload.civil_id,
        assigned_lawyer_id=payload.assigned_lawyer_id,
        status="active",
        stage=payload.stage,
        summary_ar=payload.summary_ar,
        summary_en=payload.summary_en,
        next_hearing_at=payload.next_hearing_at,
    )
    db.add(case)
    db.flush()
    db.add(CaseTimeline(
        case_id=case.id,
        step_title_ar="تسجيل الدعوى",
        step_title_en="Case Filed",
        step_date=datetime.utcnow(),
        is_done=True,
        sort_order=0,
    ))
    db.commit()
    db.refresh(case)

    log_activity(
        db, user.id, "case_create",
        entity_type="case", entity_id=case.id,
        meta={"case_number": f"{case.case_number}/{case.case_year}"},
    )

    court_reloaded = db.query(Case).options(joinedload(Case.court), joinedload(Case.assigned_lawyer)).filter(Case.id == case.id).first()
    return _to_out(court_reloaded, set())


@router.get("/{case_id}", response_model=CaseDetailOut)
def get_case(case_id: int, user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    case = _scope_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    watching = _watching_ids(db, user)
    out = _to_out(case, watching).model_dump()
    out["timeline"] = [CaseTimelineOut.model_validate(t) for t in case.timeline]
    out["notes"] = [
        CaseNoteOut(
            id=n.id, author_id=n.author_id, author_name_ar=n.author.name_ar, author_name_en=n.author.name_en,
            note_text=n.note_text, created_at=n.created_at,
        )
        for n in case.notes
    ]
    return CaseDetailOut(**out)


def _assert_can_edit(db: Session, user: User):
    level = get_permission_level(db, user.role_id, "cases")
    if level not in ("full", "limited"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot modify cases")


@router.post("/{case_id}/notes", response_model=CaseNoteOut, status_code=status.HTTP_201_CREATED)
def add_note(case_id: int, payload: CaseNoteCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _assert_can_edit(db, user)
    case = _scope_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    note = CaseNote(case_id=case_id, author_id=user.id, note_text=payload.note_text)
    db.add(note)
    db.commit()
    db.refresh(note)
    # The note text itself isn't logged — it can contain sensitive legal
    # commentary; the audit trail records that a note was added, not its content.
    log_activity(db, user.id, "case_note_add", entity_type="case", entity_id=case_id)
    notify_case_note_added(db, case)
    return CaseNoteOut(
        id=note.id, author_id=user.id, author_name_ar=user.name_ar, author_name_en=user.name_en,
        note_text=note.note_text, created_at=note.created_at,
    )


@router.put("/{case_id}/stage", response_model=CaseOut)
def update_stage(case_id: int, payload: CaseStageUpdateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _assert_can_edit(db, user)
    if payload.stage not in STAGES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid stage '{payload.stage}'")
    case = _scope_query(db, user).options(joinedload(Case.court), joinedload(Case.assigned_lawyer)).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    old_stage = case.stage
    case.stage = payload.stage
    if payload.stage == "closed":
        case.status = "closed"
    db.commit()
    db.refresh(case)
    log_activity(db, user.id, "case_stage_update", entity_type="case", entity_id=case_id, meta={"new_stage": payload.stage})
    notify_case_stage_changed(db, case, old_stage, payload.stage)
    return _to_out(case, _watching_ids(db, user))


@router.post("/{case_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def watch_case(case_id: int, user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    case = _scope_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    existing = db.get(CaseWatcher, (case_id, user.id))
    # Logged inside the guard, so pressing Watch on a case you already watch
    # changes nothing and records nothing — the endpoint was already
    # idempotent and the audit trail now matches that.
    if existing is None:
        db.add(CaseWatcher(case_id=case_id, user_id=user.id, source="manual"))
        db.commit()
        log_activity(
            db, user.id, "case_watch", entity_type="case", entity_id=case_id,
            meta={"case": f"{case.case_number}/{case.case_year}", "source": "manual"},
        )


@router.delete("/{case_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
def unwatch_case(case_id: int, user: User = Depends(require_module("cases")), db: Session = Depends(get_db)):
    existing = db.get(CaseWatcher, (case_id, user.id))
    # Same rule in reverse: only a watch that actually existed and was removed
    # produces a record. A user can only ever delete their own watcher row, so
    # this cannot be used to probe cases they may not see.
    if existing:
        source = existing.source
        db.delete(existing)
        db.commit()
        case = db.get(Case, case_id)
        log_activity(
            db, user.id, "case_unwatch", entity_type="case", entity_id=case_id,
            meta={
                "case": f"{case.case_number}/{case.case_year}" if case else None,
                "was_added_by": source,
            },
        )


# ---------------- Explicit client links (independent of civil_id match) ----------------

def _assert_can_link(db: Session, user: User, case: Case):
    """Who may manage a case's client links: Admin for any case, or the
    Lawyer that case is actually assigned to for their own case. Mirrors
    `_assert_can_edit`'s role check but additionally scopes a Lawyer to cases
    they own, since linking a client is a case-specific action, not a
    module-wide "can edit cases" permission."""
    if user.role.code == "Admin":
        return
    if user.role.code == "Lawyer" and case.assigned_lawyer_id == user.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "You cannot manage client links for this case")


def _link_to_out(link: UserCaseLink) -> UserCaseLinkOut:
    return UserCaseLinkOut(
        id=link.id, case_id=link.case_id, user_id=link.user_id,
        user_name_ar=link.user.name_ar, user_name_en=link.user.name_en,
        can_upload=link.can_upload, can_upload_until=link.can_upload_until,
        linked_by=link.linked_by,
        linked_by_name_ar=link.linker.name_ar if link.linker else None,
        linked_by_name_en=link.linker.name_en if link.linker else None,
        linked_at=link.linked_at, status=link.status,
        revoked_by=link.revoked_by,
        revoked_by_name_ar=link.revoker.name_ar if link.revoker else None,
        revoked_by_name_en=link.revoker.name_en if link.revoker else None,
        revoked_at=link.revoked_at,
    )


@router.get("/{case_id}/links", response_model=list[UserCaseLinkOut])
def list_case_links(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    _assert_can_link(db, user, case)
    rows = (
        db.query(UserCaseLink)
        .options(joinedload(UserCaseLink.user), joinedload(UserCaseLink.linker), joinedload(UserCaseLink.revoker))
        .filter(UserCaseLink.case_id == case_id, UserCaseLink.status == "active")
        .order_by(UserCaseLink.linked_at.desc())
        .all()
    )
    return [_link_to_out(r) for r in rows]


@router.post("/{case_id}/links", response_model=UserCaseLinkOut, status_code=status.HTTP_201_CREATED)
def link_user_to_case(case_id: int, payload: LinkUserRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    _assert_can_link(db, user, case)

    client = db.get(User, payload.user_id)
    if client is None or client.role.code != "User":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user_id must reference an active Client account")

    # Re-linking the same pair supersedes any existing active link rather than
    # stacking a second one, mirroring document_upload_grants' own "supersede,
    # don't stack" rule — the DB-level functional unique index (see the
    # migration) makes this the only possible outcome even under a race
    # between two admins linking the same pair at once.
    db.query(UserCaseLink).filter(
        UserCaseLink.case_id == case_id,
        UserCaseLink.user_id == payload.user_id,
        UserCaseLink.status == "active",
    ).update(
        {UserCaseLink.status: "revoked", UserCaseLink.revoked_by: user.id, UserCaseLink.revoked_at: datetime.utcnow()},
        synchronize_session=False,
    )

    link = UserCaseLink(
        case_id=case_id, user_id=payload.user_id, can_upload=payload.can_upload, linked_by=user.id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    log_activity(
        db, user.id, "case_link_user", entity_type="case", entity_id=case_id,
        meta={"linked_user_id": payload.user_id, "can_upload": payload.can_upload},
    )
    return _link_to_out(link)


@router.delete("/{case_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_user_from_case(case_id: int, link_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    _assert_can_link(db, user, case)

    link = db.query(UserCaseLink).filter(UserCaseLink.id == link_id, UserCaseLink.case_id == case_id).first()
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    if link.status == "active":
        link.status = "revoked"
        link.revoked_by = user.id
        link.revoked_at = datetime.utcnow()
        db.commit()
        log_activity(
            db, user.id, "case_unlink_user", entity_type="case", entity_id=case_id,
            meta={"linked_user_id": link.user_id},
        )
