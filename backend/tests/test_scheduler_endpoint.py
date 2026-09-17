"""Regression tests for the Scheduled Task hook, `POST
/api/internal/run-escalations` (app/routers/internal.py).

Split out of test_premigration_compatibility.py deliberately: these
exercise a router that ships with the Procedural Intelligence change set,
while that file ships with the pre-migration ORM fix. Keeping them apart
means each commit passes its own tests in isolation rather than depending
on a later one.

They reuse the `premigration_db` fixture because the state they care about
IS the live server's state today: the token is configured, the migration is
not applied.
"""

import pytest
from pydantic import SecretStr
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.main import app


@pytest.fixture()
def premigration_client(premigration_db: Session, premigration_base_data: dict):
    """A local copy rather than an import from the sibling test module, so
    the two files stay independent — see this module's docstring. It is
    small enough that sharing it via conftest would couple two otherwise
    unrelated commits for no real saving."""
    def _get_db_override():
        yield premigration_db

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app), premigration_base_data
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_scheduler_endpoint_skips_the_deadline_sweep_before_the_migration(
    premigration_db, premigration_client, monkeypatch
):
    """`POST /api/internal/run-escalations` does two things: the reminder
    escalations (which depend on nothing new) and the Procedural
    Intelligence deadline sweep (which needs tables the migration creates).

    On the live server today the token is configured but the migration is
    NOT applied, so the sweep's tables do not exist. Without the
    `_procedural_tables_exist` guard the task would commit the escalation
    notifications and only then raise (1146, "Table 'aslg_legal.
    procedure_rules' doesn't exist") — a partial run, every 15 minutes,
    failing inside a Scheduled Task with nobody watching the exit code.

    This drops the two tables the guard looks for to reproduce exactly that
    state, and asserts the endpoint completes instead of raising.
    """
    from app.config import settings
    from app.models import CaseDeadline, ProcedureRule

    bind = premigration_db.get_bind()
    CaseDeadline.__table__.drop(bind)
    ProcedureRule.__table__.drop(bind)

    monkeypatch.setattr(settings, "internal_task_token", SecretStr("test-token"), raising=False)
    tc, _ = premigration_client

    resp = tc.post(
        "/api/internal/run-escalations",
        headers={"X-Internal-Task-Token": "test-token"},
    )
    assert resp.status_code == 204, resp.text


def test_scheduler_endpoint_still_refuses_a_bad_token_before_the_migration(
    premigration_client, monkeypatch
):
    """The guard must not have become an early-exit that bypasses auth:
    the token check still runs first."""
    from app.config import settings

    monkeypatch.setattr(settings, "internal_task_token", SecretStr("test-token"), raising=False)
    tc, _ = premigration_client

    assert tc.post("/api/internal/run-escalations").status_code == 401
    assert tc.post(
        "/api/internal/run-escalations",
        headers={"X-Internal-Task-Token": "wrong"},
    ).status_code == 401


def test_scheduler_endpoint_refuses_entirely_when_no_token_is_configured(
    premigration_client, monkeypatch
):
    """The documented safe default — an unset ASLG_INTERNAL_TASK_TOKEN
    disables the endpoint rather than leaving it open. Setting the token in
    production must not have changed this code path."""
    from app.config import settings

    monkeypatch.setattr(settings, "internal_task_token", None, raising=False)
    tc, _ = premigration_client

    resp = tc.post(
        "/api/internal/run-escalations",
        headers={"X-Internal-Task-Token": "anything"},
    )
    assert resp.status_code == 503
