from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import require_module
from ..escalation import notify_task_assigned, run_reminder_escalations
from ..models import Case, CaseReminder, Role, User
from ..schemas import AssignableUserOut, ReminderCreateRequest, ReminderOut, ReminderResolveRequest

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

STAFF_ROLES = ("Admin", "Lawyer", "consultant", "delegate")


def _to_out(r: CaseReminder) -> ReminderOut:
    return ReminderOut(
        id=r.id, case_id=r.case_id, case_number=f"{r.case.case_number}/{r.case.case_year}",
        type=r.type, requested_stage=r.requested_stage, due_at=r.due_at, note=r.note,
        created_by=r.created_by, created_by_name_ar=r.creator.name_ar, created_by_name_en=r.creator.name_en,
        assigned_to=r.assigned_to, assigned_to_name_ar=r.assignee.name_ar, assigned_to_name_en=r.assignee.name_en,
        status=r.status, escalation_level=r.escalation_level, resolved_at=r.resolved_at, created_at=r.created_at,
    )


def _can_assign_freely(user: User) -> bool:
    """Admins and owner-lawyers (the firm's owners) may assign a reminder to
    any staff member. Everyone else may only target the case's own lawyer."""
    return user.role.code == "Admin" or (user.role.code == "Lawyer" and user.is_owner)


@router.get("/assignable-users", response_model=list[AssignableUserOut])
def list_assignable_users(user: User = Depends(require_module("reminders", "full", "edit")), db: Session = Depends(get_db)):
    """Staff a reminder can be assigned to. Only owners (Admin / owner-lawyers)
    get this broader roster — used to power the assignee picker in their UI."""
    if not _can_assign_freely(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only firm owners can assign tasks to other staff")
    rows = (
        db.query(User)
        .join(Role)
        .filter(Role.code.in_(STAFF_ROLES), User.is_active == True)  # noqa: E712
        .order_by(User.name_en)
        .all()
    )
    return [AssignableUserOut(id=u.id, name_ar=u.name_ar, name_en=u.name_en, role_code=u.role.code) for u in rows]


@router.get("", response_model=list[ReminderOut])
def list_reminders(user: User = Depends(require_module("reminders")), db: Session = Depends(get_db)):
    run_reminder_escalations(db)
    rows = (
        db.query(CaseReminder)
        .options(joinedload(CaseReminder.case), joinedload(CaseReminder.creator), joinedload(CaseReminder.assignee))
        .filter(or_(CaseReminder.assigned_to == user.id, CaseReminder.created_by == user.id))
        .order_by(CaseReminder.status.asc(), CaseReminder.due_at.asc())
        .all()
    )
    return [_to_out(r) for r in rows]


@router.post("", response_model=ReminderOut, status_code=status.HTTP_201_CREATED)
def create_reminder(payload: ReminderCreateRequest, user: User = Depends(require_module("reminders", "full", "edit")), db: Session = Depends(get_db)):
    case = db.get(Case, payload.case_id)
    if case is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    if payload.type not in ("follow_up", "status_update_request"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid reminder type")

    if _can_assign_freely(user):
        assignee = db.get(User, payload.assigned_to)
        if assignee is None or assignee.role.code not in STAFF_ROLES:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignee not found")
    else:
        # Consultants (and anyone without owner rights) may only send a
        # reminder to the case's own lawyer — matches the existing case-bound flow.
        if not case.assigned_lawyer_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "This case has no assigned lawyer to remind")
        payload.assigned_to = case.assigned_lawyer_id

    reminder = CaseReminder(
        case_id=payload.case_id, type=payload.type, requested_stage=payload.requested_stage,
        due_at=payload.due_at, note=payload.note, created_by=user.id, assigned_to=payload.assigned_to,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    # Logged only after the commit, so a rejected request (unknown case,
    # invalid type, unknown assignee — all raised above) never leaves a record
    # claiming a task was created. The client IP is filled in automatically
    # from the request context; see backend/app/client_ip.py.
    log_activity(
        db, user.id, "reminder_create",
        entity_type="reminder", entity_id=reminder.id,
        meta={
            "case": f"{case.case_number}/{case.case_year}",
            "case_id": case.id,
            "type": reminder.type,
            "requested_stage": reminder.requested_stage,
            "assigned_to": reminder.assigned_to,
            "due_at": reminder.due_at.isoformat() if reminder.due_at else None,
        },
    )
    # The assignee is told immediately rather than discovering the task on
    # their next visit to the Reminders page.
    notify_task_assigned(db, reminder, user.name_en)
    return _to_out(reminder)


@router.put("/{reminder_id}/resolve", response_model=ReminderOut)
def resolve_reminder(reminder_id: int, payload: ReminderResolveRequest, user: User = Depends(require_module("reminders")), db: Session = Depends(get_db)):
    reminder = (
        db.query(CaseReminder)
        .options(joinedload(CaseReminder.case), joinedload(CaseReminder.creator), joinedload(CaseReminder.assignee))
        .filter(CaseReminder.id == reminder_id)
        .first()
    )
    if reminder is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Reminder not found")
    if reminder.assigned_to != user.id and reminder.created_by != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your reminder to resolve")
    if payload.status not in ("done", "dismissed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "status must be 'done' or 'dismissed'")

    previous_status = reminder.status
    reminder.status = payload.status
    reminder.resolved_at = datetime.utcnow()

    # Marking a status-update request Done also advances the case. That is a
    # change to a case, not just to a task, so the audit entry has to say so —
    # otherwise the Activity Log shows a stage moving with nothing explaining
    # why.
    advanced_stage = None
    if payload.status == "done" and reminder.type == "status_update_request" and reminder.requested_stage:
        reminder.case.stage = reminder.requested_stage
        advanced_stage = reminder.requested_stage
        if reminder.requested_stage == "closed":
            reminder.case.status = "closed"

    db.commit()
    db.refresh(reminder)

    # Only when the status genuinely changed. Re-resolving an already-resolved
    # task is a no-op in effect, and writing a second "resolved" row for it
    # would make the log imply work that did not happen. Behaviour of the
    # endpoint itself is unchanged.
    if previous_status != payload.status:
        log_activity(
            db, user.id, "reminder_resolve",
            entity_type="reminder", entity_id=reminder.id,
            meta={
                "case": f"{reminder.case.case_number}/{reminder.case.case_year}",
                "case_id": reminder.case_id,
                "type": reminder.type,
                "from": previous_status,
                "to": payload.status,
                "case_stage_advanced_to": advanced_stage,
            },
        )
    return _to_out(reminder)
