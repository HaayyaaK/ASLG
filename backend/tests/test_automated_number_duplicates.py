"""Uniqueness of the Automated Number, and which conflict is reported.

A case can now clash with an existing one in two independent ways -- same
`case_number` + `case_year`, or same `automated_number` -- and the two need
DIFFERENT corrective action from whoever hit them:

  * number+year      -> one of those two values is wrong, change it
  * automated number -> this case is already filed, under a different short
                        number; go and look at that one instead

So they are separate 409s with separate messages, and the Automated Number
message names the case that already holds it. These tests pin both, plus
the order they are checked in, which is otherwise invisible.

The duplicate check is done explicitly in the endpoint rather than being
left to uq_cases_automated_number: an IntegrityError from the database
escapes as a bare 500, which tells the operator nothing and looks like an
outage rather than a correctable mistake.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.main import app


@pytest.fixture()
def api(db: Session, base_data: dict):
    def _get_db_override():
        yield db

    app.dependency_overrides[get_db] = _get_db_override
    try:
        yield TestClient(app), base_data, db
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_current_user, None)


def _as(user):
    app.dependency_overrides[get_current_user] = lambda: user


def _payload(base_data, case_number, automated_number, case_year=None):
    body = {
        "case_number": case_number,
        "automated_number": automated_number,
        "court_id": base_data["court"].id,
        "parties_ar": "طرف أ ضد طرف ب",
        "assigned_lawyer_id": base_data["lawyer"].id,
        "stage": "new",
    }
    if case_year is not None:
        body["case_year"] = case_year
    return body


def test_first_case_with_a_given_automated_number_succeeds(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, "5001", "202610001"))
    assert resp.status_code == 201, resp.text
    assert resp.json()["automated_number"] == "202610001"


def test_duplicate_automated_number_returns_409_naming_the_existing_case(api):
    """The message must identify WHICH case already holds the number.
    "Automated Number already in use" alone leaves the operator hunting
    through the case list for something they cannot search for -- the
    number they have is, by definition, the one that does not belong to
    the case they are trying to create."""
    tc, base_data, db = api
    _as(base_data["admin"])
    first = tc.post("/api/cases", json=_payload(base_data, "5002", "202610002"))
    assert first.status_code == 201, first.text

    # Different short number, different parties -- only the Automated
    # Number collides, so nothing else can be responsible for the 409.
    dup = tc.post("/api/cases", json=_payload(base_data, "5003", "202610002"))
    assert dup.status_code == 409, dup.text
    assert "202610002" in dup.text
    assert "5002" in dup.text, "the 409 does not name the case that already holds the number"


def test_same_case_number_and_year_still_returns_the_original_409(api):
    """The pre-existing uq_case_number_year conflict must keep behaving
    exactly as it did before this column was added."""
    tc, base_data, db = api
    _as(base_data["admin"])
    assert tc.post("/api/cases", json=_payload(base_data, "5004", "202610004")).status_code == 201
    # Same number+year, deliberately DIFFERENT automated number, so this
    # can only be the number+year conflict.
    dup = tc.post("/api/cases", json=_payload(base_data, "5004", "202610005"))
    assert dup.status_code == 409, dup.text
    assert "already exists" in dup.text


def test_a_fully_distinct_case_succeeds(api):
    """The control: with both identifiers free, creation is unaffected by
    either duplicate check."""
    tc, base_data, db = api
    _as(base_data["admin"])
    assert tc.post("/api/cases", json=_payload(base_data, "5006", "202610006")).status_code == 201
    resp = tc.post("/api/cases", json=_payload(base_data, "5007", "202610007"))
    assert resp.status_code == 201, resp.text


def test_number_year_conflict_is_reported_before_automated_number_conflict(api):
    """When BOTH identifiers clash, the endpoint checks number+year first.

    That precedence is currently invisible -- both paths return 409, so
    swapping the two blocks would change which message the operator sees
    with nothing failing. It matters because number+year is the conflict
    they can actually act on first: if that is wrong, the Automated Number
    probably belongs to the same already-filed case anyway.
    """
    tc, base_data, db = api
    _as(base_data["admin"])
    assert tc.post("/api/cases", json=_payload(base_data, "5008", "202610008")).status_code == 201

    both = tc.post("/api/cases", json=_payload(base_data, "5008", "202610008"))
    assert both.status_code == 409, both.text
    assert "already exists" in both.text, (
        "with both identifiers clashing, the number+year conflict should be "
        "reported -- the Automated Number message surfaced instead"
    )
