"""Validation of the Automated Number (الرقم الآلي) on case creation.

Exercised through the real `POST /api/cases` endpoint rather than by
constructing `CaseCreateRequest` directly, because the thing worth pinning
is the behaviour an operator actually meets: a 422 with a message that says
what to type, not merely that a Pydantic validator exists.

Why this is guarded so closely: `automated_number` is the identifier a court
or a client quotes back at the firm, and `case_year` -- half of
uq_case_number_year, and the "1123/2024" identity printed on every screen
and every printed record -- is DERIVED from its first four digits. A value
that is wrong in a way the app accepts does not cause an error; it files a
case under the wrong year, permanently, and nothing points at the cause.

The same rule is enforced in three places on purpose, and each has a
different job:
  - js/pages/cases.js  -- tells the user before they submit (UX)
  - app/schemas.py     -- the rule (what these tests exercise)
  - ck_cases_automated_number_format -- the database's own backstop, for any
    write that bypasses the API entirely (manual INSERT, restored dump)
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


def _payload(base_data, **overrides):
    """A valid create-case body, with the field under test overridden.

    `case_number` varies per call because uq_case_number_year would
    otherwise reject the second case in a test for the wrong reason,
    masking whatever the test was actually checking.
    """
    body = {
        "case_number": overrides.pop("case_number", "4001"),
        "automated_number": "202699999",
        "court_id": base_data["court"].id,
        "parties_ar": "طرف أ ضد طرف ب",
        "stage": "new",
    }
    body.update(overrides)
    return body


# ------------------------------------------------------------ accepted --


def test_valid_automated_number_is_accepted_and_derives_the_year(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, automated_number="202699999"))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["automated_number"] == "202699999"
    assert body["case_year"] == 2026


def test_surrounding_whitespace_is_trimmed_not_rejected(api):
    """A number pasted out of an email or a court PDF very often arrives
    with a trailing space. Rejecting that would be a pointless obstacle;
    silently accepting it *with* the space would store a value that never
    matches a search. So it is trimmed, and the stored value is clean."""
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, automated_number="  202699999  "))
    assert resp.status_code == 201, resp.text
    assert resp.json()["automated_number"] == "202699999"


def test_matching_case_year_from_the_client_is_accepted(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post(
        "/api/cases", json=_payload(base_data, automated_number="202699999", case_year=2026)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["case_year"] == 2026


def test_case_year_is_derived_when_the_client_omits_it(api):
    """The frontend sends `case_year` as a cross-check, but it is optional
    on the wire. A caller that omits it must still get the right year
    rather than a 422 -- the server owns this value."""
    tc, base_data, db = api
    _as(base_data["admin"])
    body = _payload(base_data, automated_number="202399999")
    body.pop("case_year", None)
    resp = tc.post("/api/cases", json=body)
    assert resp.status_code == 201, resp.text
    assert resp.json()["case_year"] == 2023


# ------------------------------------------------------------ rejected --


@pytest.mark.parametrize(
    "value, why",
    [
        ("20269999", "eight digits"),
        ("2026999999", "ten digits"),
        ("2026ABCDE", "letters"),
        ("", "empty string"),
        ("---------", "nine non-numeric characters, right length"),
        ("2026 9999", "embedded space"),
    ],
)
def test_malformed_automated_numbers_are_rejected(api, value, why):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, automated_number=value))
    assert resp.status_code == 422, f"{why} was accepted: {resp.text}"


def test_missing_field_entirely_is_rejected(api):
    """A distinct code path from the empty string above: Pydantic reports a
    missing required field before any validator runs, so the two can fail
    independently of each other."""
    tc, base_data, db = api
    _as(base_data["admin"])
    body = _payload(base_data)
    body.pop("automated_number")
    assert tc.post("/api/cases", json=body).status_code == 422


@pytest.mark.parametrize("value", ["999900001", "180000001", "000000001"])
def test_implausible_year_prefixes_are_rejected(api, value):
    """These all pass the nine-digit format check, which is exactly why the
    plausibility check exists: `999900001` is an easy slip on a numeric
    keypad and would otherwise file a case in the year 9999."""
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, automated_number=value))
    assert resp.status_code == 422, f"{value} was accepted: {resp.text}"


def test_contradicting_case_year_from_the_client_is_rejected(api):
    """Rejected rather than silently corrected. If the client and the server
    disagree about which year this case belongs to, that is a bug or a stale
    form -- and since `case_year` is half of the uniqueness key and the
    printed identity, quietly overriding it would file the case under an
    identity the operator never saw."""
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post(
        "/api/cases", json=_payload(base_data, automated_number="202699999", case_year=2019)
    )
    assert resp.status_code == 422, resp.text
    assert "2019" in resp.text and "2026" in resp.text


def test_the_error_message_names_the_expected_format(api):
    """Guards the message, not just the status code. A 422 whose body says
    only "validation error" leaves the operator retyping the same wrong
    value; naming YYYYNNNNN and giving an example is what makes it fixable.
    A future refactor that swaps the custom validator for a bare regex
    constraint would still return 422 -- and would fail here."""
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.post("/api/cases", json=_payload(base_data, automated_number="123"))
    assert resp.status_code == 422
    assert "YYYYNNNNN" in resp.text
    assert "202400001" in resp.text
