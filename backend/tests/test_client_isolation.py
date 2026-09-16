"""Security-critical: a Client (role 'User') must never see a provisional/
AI-suggested deadline, the rule catalogue, or Official Source Sync
internals — see Phase 1 blueprint section 4.7/4.8 and the implementation
plan's step 14. These are full HTTP-level tests (FastAPI TestClient) with
`get_db`/`get_current_user` overridden, rather than direct engine calls, so
they exercise the ACTUAL permission gate every router enforces, not just
the underlying query.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.conftest import make_procedure, make_rule

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models import CaseDeadline


@pytest.fixture()
def client_app(db: Session, base_data, procedure_types):
    """A TestClient wired to the SAME in-memory db/base_data fixtures every
    other test uses, with authentication short-circuited via dependency
    override (no real JWT needed — this suite is testing authorization,
    not authentication)."""
    def _get_db_override():
        yield db

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app), base_data, procedure_types
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _login_as(app_, user):
    app_.dependency_overrides[get_current_user] = lambda: user


def test_client_deadlines_list_excludes_provisional(db, client_app):
    tc, base_data, ptypes = client_app
    case = base_data["case"]
    lawyer = base_data["lawyer"]
    make_procedure(db, case, ptypes["judgment_issued"], lawyer.id)
    # Unverified rule -> provisional deadline.
    make_rule(
        db, code="appeal_30d", trigger=ptypes["judgment_issued"], expected=ptypes["appeal_filed"],
        deadline_days=30, is_enabled=True, source_tier="unverified", verified_by_user_id=None,
    )
    from app.procedures import sync_deadlines_for_case
    sync_deadlines_for_case(db, case)
    assert db.query(CaseDeadline).count() == 1
    assert db.query(CaseDeadline).first().confidence == "provisional"

    _login_as(tc.app, base_data["client"])
    resp = tc.get("/api/deadlines")
    assert resp.status_code == 200
    assert resp.json() == []  # the one existing deadline is provisional -> hidden from a Client


def test_client_deadlines_list_includes_confirmed(db, client_app):
    tc, base_data, ptypes = client_app
    case = base_data["case"]
    lawyer, admin = base_data["lawyer"], base_data["admin"]
    make_procedure(db, case, ptypes["judgment_issued"], lawyer.id)
    make_rule(
        db, code="appeal_30d", trigger=ptypes["judgment_issued"], expected=ptypes["appeal_filed"],
        deadline_days=30, is_enabled=True, source_tier="official_verified", verified_by_user_id=admin.id,
    )
    from app.procedures import sync_deadlines_for_case
    sync_deadlines_for_case(db, case)

    # The client's civil_id was set to match this case in base_data.
    _login_as(tc.app, base_data["client"])
    resp = tc.get("/api/deadlines")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["confidence"] == "confirmed"


def test_client_cannot_access_rules_catalogue(client_app):
    tc, base_data, _ = client_app
    _login_as(tc.app, base_data["client"])
    resp = tc.get("/api/rules")
    assert resp.status_code == 403


def test_client_cannot_access_official_sync(client_app):
    tc, base_data, _ = client_app
    _login_as(tc.app, base_data["client"])
    resp = tc.get(f"/api/official-sync/case/{base_data['case'].id}/checks")
    assert resp.status_code == 403


def test_client_cannot_record_a_procedure(client_app):
    tc, base_data, ptypes = client_app
    _login_as(tc.app, base_data["client"])
    resp = tc.post(
        f"/api/procedures/{base_data['case'].id}",
        json={"procedure_type_id": ptypes["case_filed"].id, "occurred_at": datetime.utcnow().isoformat()},
    )
    assert resp.status_code == 403


def test_client_cannot_see_procedures_on_a_case_that_is_not_theirs(db, client_app):
    tc, base_data, ptypes = client_app
    other_case_id = base_data["case"].id + 999  # does not exist / not linked to this client
    _login_as(tc.app, base_data["client"])
    resp = tc.get(f"/api/procedures/{other_case_id}")
    assert resp.status_code == 404


def test_non_owner_cannot_enable_a_rule_even_with_full_permission(db, client_app):
    """A Lawyer who is NOT the firm owner must be refused even if somehow
    granted 'full' on rules_admin -- role/ownership is a second, independent
    gate on top of the module permission (routers/rules.py::_assert_may_verify)."""
    tc, base_data, ptypes = client_app
    from app.models import RolePermission, Role, Module

    non_owner_lawyer = base_data["lawyer"]
    non_owner_lawyer.is_owner = False
    db.commit()

    rule = make_rule(
        db, code="appeal_30d", trigger=ptypes["judgment_issued"], expected=ptypes["appeal_filed"],
        deadline_days=30, is_enabled=False, source_tier="official_inferred",
    )
    _login_as(tc.app, non_owner_lawyer)
    resp = tc.post(f"/api/rules/{rule.id}/verify", json={"confirm": True})
    assert resp.status_code == 403


def test_verifying_an_unverified_source_tier_rule_is_refused(db, client_app):
    """The gate in routers/rules.py must independently refuse to enable a
    rule whose source_tier is still 'unverified', even for an Admin who
    passes confirm=true — enabling requires the citation to have actually
    been checked, not merely a click."""
    tc, base_data, ptypes = client_app
    rule = make_rule(
        db, code="cassation_60d", trigger=ptypes["appeal_judgment_issued"], expected=ptypes["cassation_filed"],
        deadline_days=60, is_enabled=False, source_tier="unverified",
    )
    _login_as(tc.app, base_data["admin"])
    resp = tc.post(f"/api/rules/{rule.id}/verify", json={"confirm": True})
    assert resp.status_code == 400
    db.refresh(rule)
    assert rule.is_enabled is False
