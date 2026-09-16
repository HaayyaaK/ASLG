"""The scheduler hook — fixes the "no scheduler in this app" gap (Phase 1
blueprint L1) WITHOUT adding an in-process scheduler under IIS's
httpPlatformHandler, which recycles the worker process and would silently
drop any in-memory scheduled job.

Instead: a Windows Scheduled Task (documented in description.md's
Production Deployment section) hits this one endpoint every ~15 minutes.
Every check this endpoint runs is already idempotent (escalation.py's
`_notify_once`, procedures.py's UNIQUE-keyed deadlines) — see each
module's own docstring — so calling it on a schedule is exactly as safe as
the existing opportunistic calls from dashboard/reminders/notifications
requests, just no longer dependent on someone happening to load a page.

There is no logged-in user driving this call, so it cannot use
get_current_user — it is instead gated on a single shared-secret header
compared against ASLG_INTERNAL_TASK_TOKEN (config.py). Unset token means
the endpoint refuses every request; there is no fallback value.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..escalation import run_reminder_escalations
from ..models import Case, CaseDeadline, ProcedureRule
from ..procedures import mark_missed_deadlines, sync_deadlines_for_case

router = APIRouter(prefix="/api/internal", tags=["internal"])


def _require_task_token(x_internal_task_token: str | None = Header(default=None)) -> None:
    if not settings.internal_task_token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "ASLG_INTERNAL_TASK_TOKEN is not configured")
    if not x_internal_task_token or x_internal_task_token != settings.internal_task_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing internal task token")


def _procedural_tables_exist(db: Session) -> bool:
    """Whether db/migration_procedural_intelligence.sql has been applied.

    This matters because the two halves of this endpoint have different
    prerequisites. `run_reminder_escalations` works against tables that
    have always existed; the deadline sweep needs tables the migration
    creates. Without this check, running the task on a server where the
    migration has NOT been applied would send the escalation notifications
    (a real, committed write) and only THEN raise (1146, "Table ... doesn't
    exist") — a half-completed run, repeated every 15 minutes, with the
    error surfacing as a bare 500 to a Scheduled Task nobody is watching.

    Checked per call rather than once at import: the migration is applied
    to a running system, and the endpoint should start doing the extra work
    on the next tick without needing an app-pool recycle.
    """
    names = set(inspect(db.get_bind()).get_table_names())
    return {ProcedureRule.__tablename__, CaseDeadline.__tablename__} <= names


@router.post("/run-escalations", status_code=status.HTTP_204_NO_CONTENT)
def run_escalations(_: None = Depends(_require_task_token), db: Session = Depends(get_db)):
    """Runs every proactive check firm-wide, not scoped to any one user's
    visibility — the Scheduled Task has no user context, and every write
    here is the same idempotent insert a real request would have triggered.

    Degrades rather than failing before the Procedural Intelligence
    migration is applied: the reminder escalations still run (they are the
    pre-existing behaviour and depend on nothing new), and the deadline
    sweep is skipped until its tables exist. See `_procedural_tables_exist`.
    """
    run_reminder_escalations(db)

    if not _procedural_tables_exist(db):
        return

    now = datetime.utcnow()
    for case in db.query(Case).filter(Case.status == "active").all():
        sync_deadlines_for_case(db, case)
    mark_missed_deadlines(db, now)
