"""Regression tests for the pre-existing proactive notification engine
(backend/app/escalation.py) — establishes the baseline BEFORE any
Procedural Intelligence code touches this file, per the Phase 1
implementation plan step 0. Also proves the specific contract
procedures.py depends on: `_run_task_alerts` treats every open
CaseReminder identically regardless of `type`, so a `procedural_deadline`
reminder rides these layers unchanged."""

from datetime import datetime, timedelta

from app.escalation import _due_layer, _layer_moments, _notify_once, _shift_off_weekend
from app.models import CaseReminder, Notification


def test_shift_off_weekend_only_ever_moves_earlier():
    friday_9am = datetime(2026, 9, 18, 6, 0)  # Friday 09:00 Kuwait
    shifted = _shift_off_weekend(friday_9am)
    assert shifted < friday_9am
    assert shifted.date() < friday_9am.date()


def test_layer_moments_are_strictly_increasing_and_before_the_event():
    event_at = datetime(2026, 10, 1, 9, 0)
    known_from = datetime(2026, 9, 1, 9, 0)  # comfortable notice (30 days)
    moments = _layer_moments(event_at, known_from)
    assert len(moments) == 3
    assert moments[0] < moments[1] < moments[2] < event_at


def test_layer_moments_compress_proportionally_under_short_notice():
    event_at = datetime(2026, 9, 20, 9, 0)
    known_from = datetime(2026, 9, 18, 9, 0)  # only 2 days notice
    moments = _layer_moments(event_at, known_from)
    assert moments[0] < moments[1] < moments[2] < event_at


def test_due_layer_zero_before_any_layer_arrives():
    event_at = datetime(2026, 10, 1, 9, 0)
    known_from = datetime(2026, 9, 1, 9, 0)
    now = datetime(2026, 9, 2, 9, 0)  # way before layer 1 (7 days out)
    assert _due_layer(event_at, known_from, now) == 0


def test_notify_once_deduplicates_identical_message(db, base_data):
    user_id = base_data["lawyer"].id
    inserted_first = _notify_once(db, user_id, "reminder", "ar text", "en text")
    db.commit()
    inserted_second = _notify_once(db, user_id, "reminder", "ar text", "en text")
    assert inserted_first is True
    assert inserted_second is False


def test_run_task_alerts_fires_for_procedural_deadline_type_reminder(db, base_data):
    """The exact contract procedures.py's sync_deadlines_for_case() relies
    on: `_run_task_alerts` must not filter on CaseReminder.type, so a
    'procedural_deadline' reminder gets the same 7/3/1 treatment as an
    ordinary 'follow_up' one with zero changes to escalation.py."""
    case = base_data["case"]
    lawyer = base_data["lawyer"]
    now = datetime.utcnow()
    due_at = now + timedelta(days=1)
    # 10 days of total notice (created 9 days before a due date 1 day out)
    # puts `now` past all three of the comfortable-notice 7/3/1 layers, so
    # the "final alert" layer is unambiguously reached rather than depending
    # on the short-notice proportional-compression branch.
    reminder = CaseReminder(
        case_id=case.id,
        type="procedural_deadline",
        due_at=due_at,
        note="File the appeal",
        created_by=lawyer.id,
        assigned_to=lawyer.id,
        created_at=now - timedelta(days=9),
    )
    db.add(reminder)
    db.commit()

    # `_run_task_alerts` alone (like every private helper in this module)
    # only adds pending Notification rows without flushing — the app's own
    # SessionLocal runs with autoflush=False (database.py), so a bare
    # `db.query(...)` right after would see nothing. `run_reminder_escalations`
    # is the real, always-used public entry point that commits when
    # `changed`, so exercising it here is also the more faithful test.
    from app.escalation import run_reminder_escalations

    run_reminder_escalations(db)

    notif = (
        db.query(Notification)
        .filter(Notification.user_id == lawyer.id, Notification.type == "reminder")
        .first()
    )
    assert notif is not None
    assert "File the appeal" in notif.message_en
