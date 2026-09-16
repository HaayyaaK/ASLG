"""Tests for the new Procedural Intelligence engine (backend/app/procedures.py).

Covers exactly the guarantees the Phase 1 blueprint promised:
  - no enabled rule matching => next_actions() is empty, never a guess
  - a rule that IS enabled and lawyer-verified produces a 'confirmed' deadline
  - an unverified/disabled rule (the seeded default) never reaches this far,
    and if it somehow matched would produce 'provisional', never 'confirmed'
  - idempotency: running the engine twice never duplicates a deadline
  - weekend handling pushes a deadline FORWARD (the opposite direction from
    escalation.py's pre-event reminder shifting, which pulls EARLIER)
  - recording the expected next procedure closes the open deadline and its
    bridged CaseReminder
"""

from datetime import datetime, timedelta

from tests.conftest import make_procedure, make_rule

from app.models import CaseDeadline, CaseReminder
from app.procedures import (
    _shift_off_weekend_forward,
    close_deadlines_for_procedure,
    next_actions,
    sync_deadlines_for_case,
)


def test_no_matching_rule_returns_empty_not_a_guess(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["case_filed"], base_data["lawyer"].id)
    # No ProcedureRule seeded at all -> next_actions must be empty, never a
    # fabricated entry.
    assert next_actions(db, case) == []


def test_disabled_rule_never_produces_a_deadline(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30, is_enabled=False,
    )
    assert next_actions(db, case) == []


def test_enabled_verified_rule_produces_a_confirmed_deadline(db, base_data, procedure_types):
    case = base_data["case"]
    admin = base_data["admin"]
    judgment = make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id,
                               occurred_at=datetime(2026, 9, 1, 9, 0))
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="official_verified", verified_by_user_id=admin.id,
    )

    actions = next_actions(db, case)
    assert len(actions) == 1
    assert actions[0]["confidence"] == "confirmed"
    assert actions[0]["due_at"] >= judgment.occurred_at + timedelta(days=30)


def test_enabled_but_unverified_rule_is_only_provisional(db, base_data, procedure_types):
    """A rule can be is_enabled=1 in the data without ever having been
    through the lawyer-verification gate in routers/rules.py (e.g. a stale
    row from a bad manual edit) -- next_actions() must independently refuse
    to call anything 'confirmed' unless BOTH source_tier=='official_verified'
    AND verified_by_user_id is set, never trusting is_enabled alone."""
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="unverified", verified_by_user_id=None,
    )
    actions = next_actions(db, case)
    assert len(actions) == 1
    assert actions[0]["confidence"] == "provisional"


def test_case_type_scoped_rule_does_not_apply_to_a_different_case_type(db, base_data, procedure_types):
    from app.models import CaseType

    case = base_data["case"]
    labour = CaseType(code="labour", name_ar="عمالي", name_en="Labour")
    civil = CaseType(code="civil", name_ar="مدني", name_en="Civil")
    db.add_all([labour, civil])
    db.flush()
    case.case_type_id = civil.id
    db.commit()

    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="labour_only_rule", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=15,
        is_enabled=True, source_tier="official_verified", verified_by_user_id=base_data["admin"].id,
        case_type_id=labour.id,
    )
    assert next_actions(db, case) == []


def test_sync_deadlines_is_idempotent(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="official_verified", verified_by_user_id=base_data["admin"].id,
    )

    first_run = sync_deadlines_for_case(db, case)
    second_run = sync_deadlines_for_case(db, case)

    assert len(first_run) == 1
    assert len(second_run) == 0  # nothing new -- already materialised
    assert db.query(CaseDeadline).filter(CaseDeadline.case_id == case.id).count() == 1


def test_confirmed_deadline_bridges_into_a_case_reminder(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="official_verified", verified_by_user_id=base_data["admin"].id,
    )
    created = sync_deadlines_for_case(db, case)
    assert len(created) == 1
    deadline = created[0]
    assert deadline.reminder_id is not None
    reminder = db.get(CaseReminder, deadline.reminder_id)
    assert reminder.type == "procedural_deadline"
    assert reminder.assigned_to == base_data["lawyer"].id
    assert reminder.status == "open"


def test_provisional_deadline_does_not_create_a_reminder(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="unverified", verified_by_user_id=None,
    )
    created = sync_deadlines_for_case(db, case)
    assert len(created) == 1
    assert created[0].confidence == "provisional"
    assert created[0].reminder_id is None


def test_weekend_shift_moves_deadline_forward_not_earlier():
    """The opposite direction from escalation._shift_off_weekend (which
    pulls pre-event reminder alerts earlier): a legal deadline landing on
    the Kuwaiti weekend rolls to the NEXT working day, never an earlier one
    (a statute never lets you file something before its own deadline)."""
    friday_9am = datetime(2026, 9, 18, 9, 0)  # Friday, the only weekend day
    shifted = _shift_off_weekend_forward(friday_9am)
    assert shifted > friday_9am
    assert shifted.weekday() != 4  # no longer Friday


def test_recording_expected_procedure_closes_the_open_deadline_and_reminder(db, base_data, procedure_types):
    case = base_data["case"]
    make_procedure(db, case, procedure_types["judgment_issued"], base_data["lawyer"].id)
    make_rule(
        db, code="appeal_30d", trigger=procedure_types["judgment_issued"],
        expected=procedure_types["appeal_filed"], deadline_days=30,
        is_enabled=True, source_tier="official_verified", verified_by_user_id=base_data["admin"].id,
    )
    created = sync_deadlines_for_case(db, case)
    deadline = created[0]
    reminder_id = deadline.reminder_id

    appeal_event = make_procedure(db, case, procedure_types["appeal_filed"], base_data["lawyer"].id)
    closed_count = close_deadlines_for_procedure(db, case, appeal_event)

    db.refresh(deadline)
    reminder = db.get(CaseReminder, reminder_id)
    assert closed_count == 1
    assert deadline.status == "met"
    assert deadline.completed_by_procedure_id == appeal_event.id
    assert reminder.status == "done"
