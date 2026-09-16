"""Regression test for a real production outage (Sept 2026): adding new
ORM columns/relationships for Procedural Intelligence
(`cases.case_type_id`/`procedural_status_id`/`last_official_check_at`,
`documents.doc_class_id`) broke `/api/cases`, `/api/dashboard/stats`,
`/api/dashboard/upcoming-hearings`, and `/api/documents` in production,
because the live database did not have those columns yet (the migration
that adds them, db/migration_procedural_intelligence.sql, is intentionally
NOT applied — see that file's own docstring on why it's manual-only).

  pymysql.err.OperationalError: (1054, "Unknown column 'cases.case_type_id'
  in 'field list'")

Root cause, in two parts:
  1. A plain `db.query(Case)...` issued by every one of the affected
     endpoints implicitly selects every mapped column, including brand
     new ones the live table doesn't have yet.
  2. Even after marking those columns `deferred=True` (which fixes part 1
     for `.all()`/`.first()`), `Query.count()` was found to IGNORE
     deferred and still select every mapped column when it wraps the
     statement in a `SELECT count(*) FROM (...)` subquery — so
     `dashboard.py`'s `case_q.count()` / `doc_q.count()` needed their own
     fix (`.with_entities(<pk>).count()`) on top of `deferred=True`.

This test builds a schema that matches the LIVE production database
(`premigration_db`/`premigration_base_data` fixtures in conftest.py — the
full ORM schema with exactly those 4 columns dropped again, confirmed via
a live `DESCRIBE cases`/`DESCRIBE documents` to be what's actually missing
today) and exercises the real endpoints against it, so a future column
added the same way, without deferring it (or without fixing a `.count()`
call site the same way), fails `pytest` before it can ever reach
production again.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models import CourtSession, Document


@pytest.fixture()
def premigration_client(premigration_db: Session, premigration_base_data: dict):
    def _get_db_override():
        yield premigration_db

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app), premigration_base_data
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _login_as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def test_list_cases_works_against_the_live_premigration_schema(premigration_client):
    tc, base_data = premigration_client
    _login_as(base_data["admin"])
    resp = tc.get("/api/cases")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_create_case_works_against_the_live_premigration_schema(premigration_client):
    """The write-side half of the same bug: `Case.case_type_id` etc. used
    to be mapped with `default=None` (later `deferred=True`, which turned
    out not to help either — see this file's module docstring). Either
    way, SQLAlchemy always sends a value for every mapped column on
    INSERT, so simply declaring these columns on the ORM class broke
    POST /api/cases in production just as much as the GET endpoints,
    confirmed directly against the live database during this fix.
    """
    tc, base_data = premigration_client
    _login_as(base_data["admin"])
    resp = tc.post("/api/cases", json={
        "case_number": "9999", "case_year": 2026, "court_id": base_data["court"].id,
        "parties_ar": "طرف تجريبي", "stage": "new",
    })
    assert resp.status_code == 201, resp.text
    assert resp.json()["case_number"] == "9999"


def test_dashboard_stats_works_against_the_live_premigration_schema(premigration_client):
    """This is the exact endpoint (`/api/dashboard/stats`) that 500'd in
    production — specifically via `case_q.count()`, the call `deferred=True`
    alone did not fix (see this file's module docstring, part 2)."""
    tc, base_data = premigration_client
    _login_as(base_data["admin"])
    resp = tc.get("/api/dashboard/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_cases"] == 1
    assert "pending_documents" in body


def test_dashboard_upcoming_hearings_works_against_the_live_premigration_schema(premigration_db, premigration_client):
    tc, base_data = premigration_client
    session = CourtSession(
        case_id=base_data["case"].id, circuit_ar="دائرة", circuit_en="Circuit",
        session_at=datetime.utcnow() + timedelta(days=1), status="scheduled",
    )
    premigration_db.add(session)
    premigration_db.commit()

    _login_as(base_data["admin"])
    resp = tc.get("/api/dashboard/upcoming-hearings")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_documents_list_works_against_the_live_premigration_schema(premigration_db, premigration_client):
    """`documents.doc_class_id` is the other new column this phase added
    to a pre-existing table -- covers it independently of the `cases`
    columns above."""
    tc, base_data = premigration_client
    doc = Document(
        case_id=base_data["case"].id, file_name="test.pdf", file_type="pdf", file_size=100,
        storage_path="/tmp/test.pdf", uploaded_by=base_data["admin"].id,
    )
    premigration_db.add(doc)
    premigration_db.commit()

    _login_as(base_data["admin"])
    resp = tc.get("/api/documents")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_pending_documents_count_in_dashboard_stats_against_premigration_schema(premigration_db, premigration_client):
    """The other `.count()` call site the same bug affected
    (`doc_q.count()` in dashboard.py) — covered separately from the plain
    list-documents case above since `.count()` is where `deferred=True`
    alone was proven insufficient."""
    tc, base_data = premigration_client
    doc = Document(
        case_id=base_data["case"].id, file_name="pending.pdf", file_type="pdf", file_size=50,
        storage_path="/tmp/pending.pdf", uploaded_by=base_data["admin"].id, status="pending",
    )
    premigration_db.add(doc)
    premigration_db.commit()

    _login_as(base_data["admin"])
    resp = tc.get("/api/dashboard/stats")
    assert resp.status_code == 200
    assert resp.json()["pending_documents"] == 1
