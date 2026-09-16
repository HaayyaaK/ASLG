"""Procedural Intelligence engine.

Implements the chain the firm actually needs:

    Current Status -> Latest Event -> Required Next Procedure ->
    Responsible User -> Deadline -> Reminder/Notification -> Completion

WHAT THIS MODULE DELIBERATELY DOES NOT DO
------------------------------------------
It never invents a legal deadline. Every date produced here traces back to
one specific `ProcedureRule` row, which itself is data (not code) carrying a
`legal_citation`, a `source_tier`, and an `is_enabled` flag that a named
lawyer must have flipped on together with `verified_by_user_id` +
`verified_at` (see routers/rules.py). If no enabled rule matches a case's
latest event, `next_actions()` returns an empty list — the caller (the UI)
is expected to say so plainly and invite a lawyer to set the next action by
hand, not to guess on the engine's behalf.

IDEMPOTENCY
-----------
`case_deadlines` carries a UNIQUE key on
(triggered_by_procedure_id, rule_id, rule_version) — see
db/migration_procedural_intelligence.sql. `sync_deadlines_for_case()` below
relies on that: it is safe to call on every page load (mirroring how
escalation.run_reminder_escalations() already works), and re-running it
after a rule's wording changes (a new `version`) creates the new deadline
without touching or duplicating the old one.

BRIDGE TO THE EXISTING NOTIFICATION ENGINE
-------------------------------------------
This module creates at most one `CaseReminder` per confirmed `CaseDeadline`
and otherwise does nothing notification-related — escalation.py's existing
`_run_task_alerts` already fires 7/3/1 pre-due layers for every open
CaseReminder regardless of its `type`, so a procedural deadline rides that
unchanged machinery with zero new escalation code.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from .escalation import notify_task_assigned
from .kuwait_time import is_kuwait_weekend
from .models import (
    Case,
    CaseDeadline,
    CaseProcedure,
    CaseReminder,
    ProcedureRule,
    ProcedureType,
)

# How many days without an Assisted Manual Sync check before a case is
# considered stale (Phase 1 blueprint 4.5.4). A case that has never been
# checked at all (last_official_check_at IS NULL) is treated as maximally
# stale from the moment it exists, not exempted.
OFFICIAL_SYNC_STALENESS_DAYS = 21


def _shift_off_weekend_forward(moment: datetime) -> datetime:
    """A legal deadline may never silently become *earlier* than the
    statute allows, so — unlike escalation.py's own `_shift_off_weekend`,
    which pulls reminder alerts EARLIER — a due date that lands on the
    Kuwaiti weekend is pushed to the NEXT working day. That is the standard
    civil-procedure convention (a deadline expiring on a non-working day
    rolls to the next working day) and the opposite direction from how this
    codebase already treats pre-event *reminders*, so it is a separate
    function rather than a reuse of `escalation._shift_off_weekend`.
    """
    while is_kuwait_weekend(moment):
        moment += timedelta(days=1)
    return moment


def _add_days(base: datetime, days: int, day_basis: str) -> datetime:
    if day_basis == "kuwait_business":
        remaining = days
        cursor = base
        step = timedelta(days=1)
        while remaining > 0:
            cursor += step
            if not is_kuwait_weekend(cursor):
                remaining -= 1
        return cursor
    return base + timedelta(days=days)


def latest_procedure(db: Session, case_id: int) -> CaseProcedure | None:
    """The current procedural position of a case — this IS "Latest Event".

    A row that has been superseded (corrected) is never the latest: its
    replacement is ordered after it by occurred_at/id and this simply picks
    the most recent row overall, which is always the replacement once one
    exists (corrections are always inserted with occurred_at >= the row they
    correct, and are never used to rewrite history to an earlier point).
    """
    return (
        db.query(CaseProcedure)
        .filter(CaseProcedure.case_id == case_id)
        .order_by(CaseProcedure.occurred_at.desc(), CaseProcedure.id.desc())
        .first()
    )


def _matching_rules(db: Session, case: Case, trigger_type_id: int, on_date: date) -> list[ProcedureRule]:
    q = db.query(ProcedureRule).filter(
        ProcedureRule.is_enabled == True,  # noqa: E712
        ProcedureRule.trigger_procedure_type_id == trigger_type_id,
    )
    rows = q.all()
    matched = []
    # getattr(..., None), not case.case_type_id: Case.case_type_id is
    # temporarily commented out on the ORM class pending
    # db/migration_procedural_intelligence.sql (see models.py) -- this
    # whole function is unreachable pre-migration anyway (ProcedureRule's
    # own table doesn't exist yet either), but this keeps that degradation
    # graceful (no case-type scoping possible) rather than an
    # AttributeError, and needs no further change once the column returns.
    case_type_id = getattr(case, "case_type_id", None)
    for rule in rows:
        if rule.case_type_id is not None and rule.case_type_id != case_type_id:
            continue
        if rule.court_level_code is not None and case.court and rule.court_level_code != case.court.level_code:
            continue
        if rule.effective_from is not None and on_date < rule.effective_from:
            continue
        if rule.effective_to is not None and on_date >= rule.effective_to:
            continue
        matched.append(rule)
    return matched


def _counts_from_date(procedure: CaseProcedure, rule: ProcedureRule) -> datetime:
    """Which date a rule's day-count starts from. 'notification' and
    'judgment_date' both currently resolve to the event's own occurred_at —
    they are kept distinct in the schema because a future rule may need to
    count from `observed_at` (when the firm actually learned of it) instead,
    without a migration to add that capability."""
    if rule.counts_from == "notification" and procedure.observed_at is not None:
        return procedure.observed_at
    return procedure.occurred_at


def next_actions(db: Session, case: Case) -> list[dict]:
    """What is required next for this case, per every enabled rule matching
    its latest event — this IS "Required Next Procedure" + "Deadline".

    Returns plain dicts (not ORM rows) since these are computed candidates,
    not necessarily persisted yet; callers that want them persisted call
    `sync_deadlines_for_case()` instead, which uses this function internally.
    Never returns a fabricated entry: an empty list means exactly what it
    says — no verified rule currently covers this case's position.
    """
    latest = latest_procedure(db, case.id)
    if latest is None:
        return []

    today = datetime.utcnow().date()
    rules = _matching_rules(db, case, latest.procedure_type_id, today)
    results = []
    for rule in rules:
        start = _counts_from_date(latest, rule)
        due = _add_days(start, rule.deadline_days, rule.day_basis)
        due = _shift_off_weekend_forward(due)
        confidence = "confirmed" if (rule.source_tier == "official_verified" and rule.verified_by_user_id) else "provisional"
        responsible_user_id = case.assigned_lawyer_id
        results.append(
            {
                "rule": rule,
                "triggered_by": latest,
                "due_at": due,
                "confidence": confidence,
                "responsible_user_id": responsible_user_id,
            }
        )
    return results


def sync_deadlines_for_case(db: Session, case: Case) -> list[CaseDeadline]:
    """Persist `next_actions()` as real, idempotent CaseDeadline rows and
    bridge every 'confirmed' one into a CaseReminder so it rides the
    existing escalation engine. Safe to call repeatedly (mirrors
    escalation.run_reminder_escalations()'s own contract) — the UNIQUE key
    on (triggered_by_procedure_id, rule_id, rule_version) makes a repeat
    call a no-op for anything already materialised.
    """
    created: list[CaseDeadline] = []
    for candidate in next_actions(db, case):
        rule: ProcedureRule = candidate["rule"]
        triggered_by: CaseProcedure = candidate["triggered_by"]
        existing = (
            db.query(CaseDeadline)
            .filter(
                CaseDeadline.triggered_by_procedure_id == triggered_by.id,
                CaseDeadline.rule_id == rule.id,
                CaseDeadline.rule_version == rule.version,
            )
            .first()
        )
        if existing is not None:
            continue

        deadline = CaseDeadline(
            case_id=case.id,
            triggered_by_procedure_id=triggered_by.id,
            rule_id=rule.id,
            rule_version=rule.version,
            deadline_type_code=rule.code,
            due_at=candidate["due_at"],
            responsible_user_id=candidate["responsible_user_id"],
            confidence=candidate["confidence"],
        )
        db.add(deadline)
        db.flush()  # need deadline.id before creating/linking a CaseReminder

        if deadline.confidence == "confirmed" and deadline.responsible_user_id:
            reminder = CaseReminder(
                case_id=case.id,
                type="procedural_deadline",
                due_at=deadline.due_at,
                note=_deadline_note(rule),
                # There is no "system" user in this schema's `users` table,
                # and case_reminders.created_by is NOT NULL — attributing the
                # generated task to whoever recorded the triggering
                # procedure is the honest choice: they are the person whose
                # action caused this follow-up to exist.
                created_by=triggered_by.recorded_by,
                assigned_to=deadline.responsible_user_id,
            )
            db.add(reminder)
            db.flush()
            deadline.reminder_id = reminder.id

        created.append(deadline)
    if created:
        db.commit()
        for deadline in created:
            if deadline.reminder_id:
                reminder = db.get(CaseReminder, deadline.reminder_id)
                # Best-effort, like every other hand-off notice in
                # escalation.py — the deadline itself is already committed
                # and must not be undone by a notification hiccup.
                notify_task_assigned(db, reminder, reminder.creator.name_en)
    return created


def _deadline_note(rule: ProcedureRule) -> str:
    expected = rule.expected_procedure_type
    label = expected.name_en if expected else rule.code
    if rule.legal_citation:
        return f"{label} (per {rule.legal_citation})"
    return label


def close_deadlines_for_procedure(db: Session, case: Case, new_procedure: CaseProcedure) -> int:
    """When a new procedural event is recorded, close every OPEN deadline on
    this case whose expected procedure type it satisfies — this IS
    "Completion". Does not touch reminders belonging to unrelated,
    still-open deadlines. Returns how many were closed.
    """
    open_deadlines = (
        db.query(CaseDeadline)
        .join(ProcedureRule, CaseDeadline.rule_id == ProcedureRule.id)
        .filter(
            CaseDeadline.case_id == case.id,
            CaseDeadline.status == "open",
            ProcedureRule.expected_procedure_type_id == new_procedure.procedure_type_id,
        )
        .all()
    )
    closed = 0
    for deadline in open_deadlines:
        deadline.status = "met"
        deadline.completed_by_procedure_id = new_procedure.id
        if deadline.reminder_id:
            reminder = db.get(CaseReminder, deadline.reminder_id)
            if reminder is not None and reminder.status == "open":
                reminder.status = "done"
                reminder.resolved_at = datetime.utcnow()
        closed += 1
    if closed:
        db.commit()
    return closed


def mark_missed_deadlines(db: Session, now: datetime) -> int:
    """Sweep OPEN deadlines whose due_at has passed with nothing recorded to
    satisfy them yet. Purely a status change for visibility (dashboard
    counters, badges) — the underlying CaseReminder already got its own
    "deadline passed" notice from escalation._run_task_alerts, so this does
    not send anything itself."""
    rows = (
        db.query(CaseDeadline)
        .filter(CaseDeadline.status == "open", CaseDeadline.due_at < now)
        .all()
    )
    changed = 0
    for row in rows:
        row.status = "missed"
        changed += 1
    if changed:
        db.commit()
    return changed


def stale_official_sync_case_ids(db: Session, now: datetime) -> list[int]:
    """Active cases not Assisted-Manual-Sync-checked within
    OFFICIAL_SYNC_STALENESS_DAYS — feeds an ordinary CaseReminder/dashboard
    counter (Phase 1 blueprint 4.5.4), never an automated check of the
    official portal itself."""
    threshold = now - timedelta(days=OFFICIAL_SYNC_STALENESS_DAYS)
    rows = (
        db.query(Case.id)
        .filter(
            Case.status == "active",
            (Case.last_official_check_at.is_(None)) | (Case.last_official_check_at < threshold),
        )
        .all()
    )
    return [r[0] for r in rows]
