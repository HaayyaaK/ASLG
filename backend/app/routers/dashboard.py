from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from ..database import get_db
from ..deps import get_current_user, get_permission_level
from ..escalation import run_reminder_escalations
from ..kuwait_time import kuwait_today_utc_range
from ..models import Case, CaseReminder, CourtSession, Document, Notification, User, UserCaseLink
from ..schemas import DashboardStats, DashboardTaskStats, UpcomingHearingOut

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _my_case_ids(db: Session, user: User) -> list[int] | None:
    level = get_permission_level(db, user.role_id, "cases")
    if level != "own":
        return None
    # Union of civil_id match and explicit user_case_links, as a plain id
    # list — same dedup-safe shape used in cases.py/documents.py, so a case
    # connected both ways is still counted once in every stat below.
    civil_ids = (
        {c.id for c in db.query(Case.id).filter(Case.civil_id == user.civil_id).all()} if user.civil_id else set()
    )
    linked_ids = {
        row.case_id
        for row in db.query(UserCaseLink.case_id)
        .filter(UserCaseLink.user_id == user.id, UserCaseLink.status == "active")
        .all()
    }
    return list(civil_ids | linked_ids)


@router.get("/stats", response_model=DashboardStats)
def stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    run_reminder_escalations(db)
    case_ids = _my_case_ids(db, user)

    case_q = db.query(Case).filter(Case.status == "active")
    if case_ids is not None:
        case_q = case_q.filter(Case.id.in_(case_ids)) if case_ids else case_q.filter(False)
    # .with_entities(Case.id) before .count() is load-bearing, not a style
    # choice: Query.count() wraps the FULL entity SELECT (every mapped
    # column) in a `SELECT count(*) FROM (...)` subquery regardless of any
    # column's `deferred=True` -- deferred only skips a column when the
    # ORM is populating real Case objects (.all()/.first()), not when
    # counting. Case now carries columns (case_type_id, procedural_status_id,
    # last_official_check_at) that don't exist on the live `cases` table
    # until db/migration_procedural_intelligence.sql is applied, so the
    # unqualified `case_q.count()` 500'd here in production (confirmed via
    # backend/logs/uvicorn-stdout.log_13956_2026916125625.log:
    # "Unknown column 'cases.case_type_id' in 'field list'"). Narrowing to
    # just the id column avoids selecting any of them, independent of
    # whether the migration has landed.
    active_cases = case_q.with_entities(Case.id).count()

    # "Today" is the firm's Kuwait business date, not the server's UTC date.
    # Stored values are naive UTC, so the Kuwait day is expressed as the
    # half-open UTC window that covers it (00:00-02:59 Kuwait falls on the
    # previous UTC day, which is exactly what the old utcnow().date() bounds
    # got wrong). Half-open >= / < rather than BETWEEN, so a hearing in the
    # final microsecond of the day is not silently dropped.
    today_start, today_end = kuwait_today_utc_range()
    sess_q = db.query(CourtSession).join(Case).filter(
        CourtSession.session_at >= today_start, CourtSession.session_at < today_end,
        CourtSession.status == "scheduled",
    )
    if case_ids is not None:
        sess_q = sess_q.filter(Case.id.in_(case_ids)) if case_ids else sess_q.filter(False)
    today_hearings = sess_q.count()

    doc_level = get_permission_level(db, user.role_id, "documents")
    doc_q = db.query(Document).filter(Document.status == "pending")
    if doc_level == "own":
        doc_q = doc_q.join(Case).filter(Case.id.in_(case_ids)) if case_ids else doc_q.filter(False)
    # Same reason as active_cases above: Document now carries a deferred
    # doc_class_id column that doesn't exist on the live `documents` table
    # yet, and Query.count() ignores `deferred` -- confirmed 500ing with
    # "Unknown column 'documents.doc_class_id' in 'field list'" until this
    # was narrowed to just the id column.
    pending_documents = doc_q.with_entities(Document.id).count()

    notif_q = db.query(Notification).filter(
        Notification.is_read == False,  # noqa: E712
        (Notification.user_id == user.id) | (Notification.target_role_id == user.role_id),
    )
    unread_notifications = notif_q.count()

    return DashboardStats(
        active_cases=active_cases, today_hearings=today_hearings,
        pending_documents=pending_documents, unread_notifications=unread_notifications,
    )


@router.get("/upcoming-hearings", response_model=list[UpcomingHearingOut])
def upcoming_hearings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    case_ids = _my_case_ids(db, user)
    q = (
        db.query(CourtSession)
        .join(Case)
        .options(joinedload(CourtSession.case))
        .filter(CourtSession.status == "scheduled", CourtSession.session_at >= datetime.utcnow())
    )
    if case_ids is not None:
        q = q.filter(Case.id.in_(case_ids)) if case_ids else q.filter(False)
    rows = q.order_by(CourtSession.session_at.asc()).limit(5).all()
    return [
        UpcomingHearingOut(
            case_id=s.case_id, case_number=s.case.case_number, case_year=s.case.case_year,
            parties_ar=s.case.parties_ar, parties_en=s.case.parties_en,
            circuit_ar=s.circuit_ar, circuit_en=s.circuit_en, session_at=s.session_at,
        )
        for s in rows
    ]


@router.get("/task-stats", response_model=DashboardTaskStats)
def task_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Second dashboard row — open task/assignment metrics.

    Gated on the caller's `reminders` permission being anything other than
    'none', which today means Admin, Lawyer, Consultant *and* Delegate
    (delegates hold 'view': they cannot create tasks but are assigned them, so
    the counts are meaningful to them). Only the Client role, at 'none', is
    refused. The comparisons below are instant-vs-instant in UTC, which is
    timezone-independent — no Kuwait calendar conversion applies here.
    """
    if get_permission_level(db, user.role_id, "reminders") == "none":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Task stats are not available for this role")

    run_reminder_escalations(db)
    now = datetime.utcnow()

    my_open_tasks = (
        db.query(CaseReminder)
        .filter(CaseReminder.assigned_to == user.id, CaseReminder.status == "open")
        .count()
    )
    overdue_tasks = (
        db.query(CaseReminder)
        .filter(CaseReminder.assigned_to == user.id, CaseReminder.status == "open", CaseReminder.due_at < now)
        .count()
    )
    pending_status_requests = (
        db.query(CaseReminder)
        .filter(
            CaseReminder.assigned_to == user.id,
            CaseReminder.status == "open",
            CaseReminder.type == "status_update_request",
        )
        .count()
    )
    tasks_i_assigned = (
        db.query(CaseReminder)
        .filter(CaseReminder.created_by == user.id, CaseReminder.status == "open")
        .count()
    )

    return DashboardTaskStats(
        my_open_tasks=my_open_tasks, overdue_tasks=overdue_tasks,
        pending_status_requests=pending_status_requests, tasks_i_assigned=tasks_i_assigned,
    )
