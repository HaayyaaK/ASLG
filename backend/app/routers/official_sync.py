"""Assisted Manual Sync against real Kuwait official sources.

Every official channel researched (Sept 2026 — Phase 1 blueprint section
2.1) is either login+CAPTCHA gated (MOJ e-services) or, at minimum, requires
the caller's own personal authentication (Sahel / Sahel Business), and none
publish an API. This router therefore NEVER scrapes, authenticates against,
or automates anything on an official site — it only:

  1. tells the lawyer/staff member exactly what to look up and where
     (`GET /sources` + the case's own number/year/court), so they open the
     real portal in their own browser tab and sign in as themselves;
  2. records what they saw once they're done looking (`POST
     /case/{case_id}/check`), optionally attaching evidence and creating a
     real CaseProcedure row from it.

This is "official-source synchronisation" in the honest sense: a human
did the syncing, and the row `checked_by` names them. `official_sources.
access_mode`/`requires_captcha` are themselves the recorded REASON no
automated path is offered.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user, get_permission_level
from ..procedures import OFFICIAL_SYNC_STALENESS_DAYS, stale_official_sync_case_ids
from ..models import Case, CaseProcedure, Document, OfficialSource, OfficialSourceCheck, ProcedureType, User
from ..schemas import OfficialSourceCheckOut, OfficialSourceCheckRequest, OfficialSourceOut
from .cases import _scope_query

router = APIRouter(prefix="/api/official-sync", tags=["official_sync"])


def _require_level(db: Session, user: User, *levels: str) -> str:
    level = get_permission_level(db, user.role_id, "official_sync")
    if level == "none" or (levels and level not in levels):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to Official Source Sync")
    return level


def _get_case_or_404(db: Session, user: User, case_id: int) -> Case:
    case = _scope_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def _check_to_out(c: OfficialSourceCheck) -> OfficialSourceCheckOut:
    return OfficialSourceCheckOut(
        id=c.id, case_id=c.case_id, source_id=c.source_id, source_code=c.source.code,
        checked_by=c.checked_by, checked_by_name_ar=c.checker.name_ar, checked_by_name_en=c.checker.name_en,
        checked_at=c.checked_at, outcome=c.outcome, evidence_document_id=c.evidence_document_id,
        resulting_procedure_id=c.resulting_procedure_id, raw_note=c.raw_note,
    )


@router.get("/sources", response_model=list[OfficialSourceOut])
def list_sources(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Powers the "Check official portal" deep-link panel. Not permission
    gated beyond authentication — this is a catalogue of public information
    about which government channels exist, not case data."""
    return db.query(OfficialSource).filter(OfficialSource.is_enabled == True).all()  # noqa: E712


@router.get("/case/{case_id}/checks", response_model=list[OfficialSourceCheckOut])
def list_case_checks(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_level(db, user)
    case = _get_case_or_404(db, user, case_id)
    rows = (
        db.query(OfficialSourceCheck)
        .options(joinedload(OfficialSourceCheck.source), joinedload(OfficialSourceCheck.checker))
        .filter(OfficialSourceCheck.case_id == case.id)
        .order_by(OfficialSourceCheck.checked_at.desc())
        .all()
    )
    return [_check_to_out(c) for c in rows]


@router.get("/stale")
def list_stale_cases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Cases the CALLER can see that have not been Assisted-Manual-Sync
    checked within OFFICIAL_SYNC_STALENESS_DAYS — feeds an ordinary
    dashboard counter. `last_official_check_at IS NULL` (never checked) is
    included, not exempted."""
    _require_level(db, user)
    visible_ids = {c.id for c in _scope_query(db, user).all()}
    stale_ids = set(stale_official_sync_case_ids(db, datetime.utcnow())) & visible_ids
    if not stale_ids:
        return {"stale_case_ids": [], "staleness_days": OFFICIAL_SYNC_STALENESS_DAYS}
    return {"stale_case_ids": sorted(stale_ids), "staleness_days": OFFICIAL_SYNC_STALENESS_DAYS}


@router.post("/case/{case_id}/check", response_model=OfficialSourceCheckOut, status_code=status.HTTP_201_CREATED)
def record_check(
    case_id: int, payload: OfficialSourceCheckRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Record what a human just saw on an official portal. Never called by
    anything automated in this application — there is no scraper, no
    CAPTCHA-solving code, and no stored government credential anywhere in
    this codebase to call it on a human's behalf."""
    _require_level(db, user, "edit", "full")
    case = _get_case_or_404(db, user, case_id)

    source = db.get(OfficialSource, payload.source_id)
    if source is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown source_id")
    if payload.outcome not in ("no_change", "change_recorded", "not_found", "blocked"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid outcome")
    if payload.outcome == "change_recorded" and payload.new_procedure is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "change_recorded requires new_procedure")
    if payload.evidence_document_id is not None:
        doc = db.query(Document).filter(Document.id == payload.evidence_document_id, Document.case_id == case.id).first()
        if doc is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "evidence_document_id must belong to this case")

    resulting_procedure_id = None
    if payload.outcome == "change_recorded":
        np = payload.new_procedure
        ptype = db.get(ProcedureType, np.procedure_type_id)
        if ptype is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown procedure_type_id")
        procedure = CaseProcedure(
            case_id=case.id, procedure_type_id=ptype.id, occurred_at=np.occurred_at,
            recorded_by=user.id, source="official_manual", source_tier="official_verified",
            observed_at=datetime.utcnow(), observed_by=user.id,
            official_ref=np.official_ref, evidence_document_id=np.evidence_document_id or payload.evidence_document_id,
            notes_ar=np.notes_ar, notes_en=np.notes_en,
        )
        db.add(procedure)
        db.flush()
        resulting_procedure_id = procedure.id

        from ..procedures import close_deadlines_for_procedure, sync_deadlines_for_case

        close_deadlines_for_procedure(db, case, procedure)
        sync_deadlines_for_case(db, case)

    check = OfficialSourceCheck(
        case_id=case.id, source_id=source.id, checked_by=user.id, outcome=payload.outcome,
        evidence_document_id=payload.evidence_document_id, resulting_procedure_id=resulting_procedure_id,
        raw_note=payload.raw_note,
    )
    db.add(check)
    case.last_official_check_at = datetime.utcnow()
    db.commit()
    db.refresh(check)

    log_activity(
        db, user.id, "official_source_check", entity_type="case", entity_id=case.id,
        meta={"case": f"{case.case_number}/{case.case_year}", "source": source.code, "outcome": payload.outcome},
    )
    return _check_to_out(check)
