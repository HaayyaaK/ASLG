"""Procedural Intelligence — the event log and "what's next" preview.

    Current Status -> Latest Event -> Required Next Procedure -> ...

This router owns recording procedural events (the append-only
`case_procedures` log) and previewing the engine's next-action candidates.
Deadline materialisation/confirmation lives in routers/deadlines.py; the
rule catalogue itself lives in routers/rules.py — kept separate because
each has a different permission shape (rules_admin is far more
restricted than procedures).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user, get_permission_level
from ..procedures import close_deadlines_for_procedure, next_actions as engine_next_actions, sync_deadlines_for_case
from ..models import CaseProcedure, CaseType, ProcedureType, User
from ..schemas import CaseProcedureOut, CaseTypeOut, NextActionOut, ProcedureRecordRequest, ProcedureTypeOut
from .cases import _scope_query

router = APIRouter(prefix="/api/procedures", tags=["procedures"])


def _get_case_or_404(db: Session, user: User, case_id: int):
    """Case-level visibility follows the SAME rule as the Cases module
    itself (own vs. full/etc via `cases`, not `procedures`) — a user must be
    allowed to see the case at all before this feature's own `procedures`
    permission is even consulted. Mirrors search.py's `_cases_scope`
    defence-in-depth pattern."""
    from ..models import Case

    case = _scope_query(db, user).filter(Case.id == case_id).first()
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def _require_procedures_level(db: Session, user: User, *levels: str) -> str:
    level = get_permission_level(db, user.role_id, "procedures")
    if level == "none" or (levels and level not in levels):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to Procedural Intelligence")
    return level


def _procedure_to_out(p: CaseProcedure) -> CaseProcedureOut:
    return CaseProcedureOut(
        id=p.id, case_id=p.case_id, procedure_type_id=p.procedure_type_id,
        procedure_code=p.procedure_type.code, procedure_name_ar=p.procedure_type.name_ar,
        procedure_name_en=p.procedure_type.name_en,
        occurred_at=p.occurred_at, recorded_by=p.recorded_by,
        recorded_by_name_ar=p.recorder.name_ar, recorded_by_name_en=p.recorder.name_en,
        source=p.source, source_tier=p.source_tier,
        observed_at=p.observed_at, observed_by=p.observed_by, official_ref=p.official_ref,
        evidence_document_id=p.evidence_document_id, notes_ar=p.notes_ar, notes_en=p.notes_en,
        supersedes_id=p.supersedes_id, created_at=p.created_at,
    )


@router.get("/types", response_model=list[ProcedureTypeOut])
def list_procedure_types(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Powers the "Record Procedure" dropdown. Deliberately not permission
    gated beyond authentication — this is a label catalogue, not case data."""
    return db.query(ProcedureType).order_by(ProcedureType.sort_order, ProcedureType.name_en).all()


@router.get("/case-types", response_model=list[CaseTypeOut])
def list_case_types(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(CaseType).filter(CaseType.is_enabled == True).order_by(CaseType.sort_order, CaseType.name_en).all()  # noqa: E712


@router.get("/{case_id}", response_model=list[CaseProcedureOut])
def list_case_procedures(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """The full event log for one case — this IS "Latest Event" plus its
    history. `own`-level (Client) access is intentionally read-only: it is
    granted by simply not being blocked below, since this endpoint never
    writes anything."""
    _require_procedures_level(db, user)
    case = _get_case_or_404(db, user, case_id)
    rows = (
        db.query(CaseProcedure)
        .options(joinedload(CaseProcedure.procedure_type), joinedload(CaseProcedure.recorder))
        .filter(CaseProcedure.case_id == case.id)
        .order_by(CaseProcedure.occurred_at.desc(), CaseProcedure.id.desc())
        .all()
    )
    return [_procedure_to_out(p) for p in rows]


@router.get("/{case_id}/next-actions", response_model=list[NextActionOut])
def preview_next_actions(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Read-only preview of what procedures.next_actions() currently
    computes for this case — does NOT persist anything. The UI's "Record
    Procedure" flow calls POST /{case_id} to actually materialise deadlines;
    this exists so a lawyer can see what WOULD happen before committing to
    it, and so the case-detail Procedure tab has something to show even
    before any deadline has been created."""
    _require_procedures_level(db, user)
    case = _get_case_or_404(db, user, case_id)
    candidates = engine_next_actions(db, case)
    return [
        NextActionOut(
            rule_id=c["rule"].id, rule_code=c["rule"].code,
            expected_procedure_type_id=c["rule"].expected_procedure_type_id,
            expected_procedure_code=c["rule"].expected_procedure_type.code,
            expected_procedure_name_ar=c["rule"].expected_procedure_type.name_ar,
            expected_procedure_name_en=c["rule"].expected_procedure_type.name_en,
            due_at=c["due_at"], confidence=c["confidence"], source_tier=c["rule"].source_tier,
            legal_citation=c["rule"].legal_citation, legal_basis_ar=c["rule"].legal_basis_ar,
            legal_basis_en=c["rule"].legal_basis_en, responsible_user_id=c["responsible_user_id"],
        )
        for c in candidates
    ]


@router.post("/{case_id}", response_model=CaseProcedureOut, status_code=status.HTTP_201_CREATED)
def record_procedure(
    case_id: int, payload: ProcedureRecordRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Record a new procedural event — this IS "Latest Event" moving
    forward, and triggers "Completion" (closing any deadline this event
    satisfies) and the next round of "Required Next Procedure" /
    "Deadline" materialisation, all through the same engine functions the
    read-only preview above calls."""
    _require_procedures_level(db, user, "edit", "full")
    case = _get_case_or_404(db, user, case_id)

    ptype = db.get(ProcedureType, payload.procedure_type_id)
    if ptype is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown procedure_type_id")
    if payload.occurred_at > datetime.utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "occurred_at cannot be in the future")
    if payload.evidence_document_id is not None:
        from ..models import Document

        doc = db.query(Document).filter(Document.id == payload.evidence_document_id, Document.case_id == case.id).first()
        if doc is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "evidence_document_id must belong to this case")

    procedure = CaseProcedure(
        case_id=case.id,
        procedure_type_id=ptype.id,
        occurred_at=payload.occurred_at,
        recorded_by=user.id,
        source="official_manual" if payload.observed_official else "firm_entered",
        source_tier="official_verified" if payload.observed_official else "firm_entered",
        observed_at=datetime.utcnow() if payload.observed_official else None,
        observed_by=user.id if payload.observed_official else None,
        official_ref=payload.official_ref,
        evidence_document_id=payload.evidence_document_id,
        notes_ar=payload.notes_ar, notes_en=payload.notes_en,
    )
    db.add(procedure)
    db.commit()
    db.refresh(procedure)

    close_deadlines_for_procedure(db, case, procedure)
    sync_deadlines_for_case(db, case)

    log_activity(
        db, user.id, "procedure_record", entity_type="case", entity_id=case.id,
        meta={"case": f"{case.case_number}/{case.case_year}", "procedure_type": ptype.code, "source": procedure.source},
    )
    db.refresh(procedure)
    return _procedure_to_out(procedure)
