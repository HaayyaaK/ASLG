"""Procedural Intelligence — the materialised deadline list.

    ... -> Deadline -> Reminder/Notification -> Completion

Deadlines are produced by backend/app/procedures.py from the ProcedureRule
catalogue; this router lists/confirms/waives them. A 'confirmed' deadline
already has its CaseReminder bridged in by the engine at creation time — see
procedures.sync_deadlines_for_case — so nothing here talks to
escalation.py directly.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import get_current_user, get_permission_level
from ..escalation import notify_task_assigned
from ..procedures import mark_missed_deadlines, sync_deadlines_for_case
from ..models import Case, CaseDeadline, CaseReminder, User
from ..schemas import CaseDeadlineOut, DeadlineConfirmRequest, DeadlineWaiveRequest
from .cases import _scope_query

router = APIRouter(prefix="/api/deadlines", tags=["deadlines"])


def _require_deadlines_level(db: Session, user: User, *levels: str) -> str:
    level = get_permission_level(db, user.role_id, "deadlines")
    if level == "none" or (levels and level not in levels):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to Deadlines")
    return level


def _to_out(d: CaseDeadline) -> CaseDeadlineOut:
    return CaseDeadlineOut(
        id=d.id, case_id=d.case_id, case_number=d.case.case_number, case_year=d.case.case_year,
        triggered_by_procedure_id=d.triggered_by_procedure_id,
        rule_id=d.rule_id, rule_code=d.rule.code if d.rule else None,
        deadline_type_code=d.deadline_type_code, due_at=d.due_at,
        responsible_user_id=d.responsible_user_id,
        responsible_user_name_ar=d.responsible_user.name_ar if d.responsible_user else None,
        responsible_user_name_en=d.responsible_user.name_en if d.responsible_user else None,
        confidence=d.confidence, confirmed_by=d.confirmed_by, confirmed_at=d.confirmed_at,
        status=d.status, legal_citation=d.rule.legal_citation if d.rule else None,
        created_at=d.created_at,
    )


def _visible_case_ids(db: Session, user: User) -> set[int]:
    return {c.id for c in _scope_query(db, user).all()}


@router.get("", response_model=list[CaseDeadlineOut])
def list_deadlines(
    status_filter: str | None = None,
    case_id: int | None = None,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Firm-wide (scoped) deadline list — powers the Deadlines page and the
    dashboard's third row. Scoped through the SAME case-visibility rule as
    everything else in the app: a Client only ever sees deadlines on cases
    `cases` permission already lets them see, matching the defence-in-depth
    pattern search.py established (`_cases_scope`)."""
    _require_deadlines_level(db, user)
    case_ids = _visible_case_ids(db, user)
    q = db.query(CaseDeadline).options(
        joinedload(CaseDeadline.case), joinedload(CaseDeadline.rule), joinedload(CaseDeadline.responsible_user)
    )
    q = q.filter(CaseDeadline.case_id.in_(case_ids)) if case_ids else q.filter(False)
    if case_id is not None:
        q = q.filter(CaseDeadline.case_id == case_id)
    if status_filter:
        q = q.filter(CaseDeadline.status == status_filter)
    # A Client (module level 'own') must never see a provisional/AI-suggested
    # deadline or the internal rule machinery behind it — only what a lawyer
    # has actually confirmed. Every other role level sees everything so staff
    # can act on provisional items and confirm them.
    if get_permission_level(db, user.role_id, "deadlines") == "own":
        q = q.filter(CaseDeadline.confidence == "confirmed")
    rows = q.order_by(CaseDeadline.status.asc(), CaseDeadline.due_at.asc()).all()
    return [_to_out(d) for d in rows]


@router.post("/sync", status_code=status.HTTP_204_NO_CONTENT)
def sync_deadlines(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """On-demand refresh, mirroring escalation.run_reminder_escalations()'s
    own on-request contract (there is no scheduler in this app — see
    routers/internal.py for the scheduled-task alternative). Idempotent:
    safe to call on every Deadlines-page load."""
    _require_deadlines_level(db, user)
    case_ids = _visible_case_ids(db, user)
    if not case_ids:
        return
    cases = db.query(Case).filter(Case.id.in_(case_ids), Case.status == "active").all()
    for case in cases:
        sync_deadlines_for_case(db, case)
    mark_missed_deadlines(db, datetime.utcnow())


@router.put("/{deadline_id}/confirm", response_model=CaseDeadlineOut)
def confirm_deadline(
    deadline_id: int, payload: DeadlineConfirmRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """A lawyer manually confirms a 'provisional' deadline (one produced by
    a rule that is not yet official_verified + lawyer-verified) after their
    own review — this does NOT enable the underlying ProcedureRule (see
    routers/rules.py for that, a separate and more consequential action);
    it only asserts that THIS ONE deadline, on THIS ONE case, is correct.
    Confirming bridges it into a CaseReminder if one doesn't already exist,
    exactly like an engine-confirmed deadline would have been."""
    _require_deadlines_level(db, user, "edit", "full")
    deadline = db.query(CaseDeadline).options(joinedload(CaseDeadline.case)).filter(CaseDeadline.id == deadline_id).first()
    if deadline is None or deadline.case_id not in _visible_case_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deadline not found")
    if deadline.status != "open":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only an open deadline can be confirmed")

    if payload.due_at is not None:
        deadline.due_at = payload.due_at
    deadline.confidence = "confirmed"
    deadline.confirmed_by = user.id
    deadline.confirmed_at = datetime.utcnow()

    if deadline.reminder_id is None and deadline.responsible_user_id:
        reminder = CaseReminder(
            case_id=deadline.case_id, type="procedural_deadline", due_at=deadline.due_at,
            note=f"Confirmed deadline: {deadline.deadline_type_code}",
            created_by=user.id, assigned_to=deadline.responsible_user_id,
        )
        db.add(reminder)
        db.flush()
        deadline.reminder_id = reminder.id
        db.commit()
        notify_task_assigned(db, reminder, user.name_en)
    else:
        db.commit()
    db.refresh(deadline)
    log_activity(
        db, user.id, "deadline_confirm", entity_type="case_deadline", entity_id=deadline.id,
        meta={"case_id": deadline.case_id, "due_at": deadline.due_at.isoformat()},
    )
    return _to_out(deadline)


@router.put("/{deadline_id}/waive", response_model=CaseDeadlineOut)
def waive_deadline(
    deadline_id: int, payload: DeadlineWaiveRequest,
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """A lawyer marks a deadline as no longer applicable (e.g. the matter
    settled, or the rule was a false match) with a mandatory reason, kept
    only in the audit trail — mirrors DocumentReviewRequest's own
    "reason kept in the Activity Log, not on the row" pattern."""
    _require_deadlines_level(db, user, "edit", "full")
    deadline = db.query(CaseDeadline).filter(CaseDeadline.id == deadline_id).first()
    if deadline is None or deadline.case_id not in _visible_case_ids(db, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deadline not found")
    if deadline.status not in ("open", "missed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only an open or missed deadline can be waived")

    deadline.status = "waived"
    if deadline.reminder_id:
        reminder = db.get(CaseReminder, deadline.reminder_id)
        if reminder is not None and reminder.status == "open":
            reminder.status = "dismissed"
            reminder.resolved_at = datetime.utcnow()
    db.commit()
    db.refresh(deadline)
    log_activity(
        db, user.id, "deadline_waive", entity_type="case_deadline", entity_id=deadline.id,
        meta={"case_id": deadline.case_id, "reason": payload.reason},
    )
    return _to_out(deadline)
