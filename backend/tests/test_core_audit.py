"""End-to-end audit of the application's core functionality, exercised over
real HTTP (FastAPI TestClient) against a throwaway in-memory database.

Written as a standing regression suite, not a one-off script: each area the
Sept 2026 audit covered gets tests here so a future change that silently
breaks authentication, a role boundary, client isolation, or a notification
rule fails `pytest` instead of reaching production.

Areas covered (matching the audit report):
  1. Authentication            6. Dashboard
  2. Role-based access         7. User<->Case linking
  3. Cases CRUD + search       8. Reminders
  4. Documents + grants        9. i18n key parity (see test_i18n_parity.py)
  5. Notifications            10. Factory Reset gating (never executed)
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.main import app
from app.models import (
    Case,
    CaseReminder,
    CourtSession,
    Document,
    Notification,
    User,
    UserCaseLink,
)
from app.security import hash_password, verify_password


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


# ----------------------------------------------------------------- 1. auth --


def test_login_succeeds_with_correct_credentials(api):
    tc, base_data, db = api
    app.dependency_overrides.pop(get_current_user, None)
    user = base_data["admin"]
    user.password_hash = hash_password("CorrectHorse1!")
    db.commit()

    resp = tc.post("/api/auth/login", json={"username": user.username, "password": "CorrectHorse1!"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == user.username
    # The permissions map the SPA gates its whole nav on must come back with
    # the token -- a login that returns a token but no permissions renders an
    # empty sidebar, which has happened in other builds of this app.
    assert isinstance(body["permissions"], dict) and body["permissions"]


def test_login_rejects_wrong_password_and_never_leaks_which_check_failed(api):
    tc, base_data, db = api
    app.dependency_overrides.pop(get_current_user, None)
    user = base_data["admin"]
    user.password_hash = hash_password("CorrectHorse1!")
    db.commit()

    wrong_pw = tc.post("/api/auth/login", json={"username": user.username, "password": "nope"})
    unknown_user = tc.post("/api/auth/login", json={"username": "ghost.user", "password": "nope"})

    assert wrong_pw.status_code == 401
    assert unknown_user.status_code == 401
    # Identical message for both: revealing "no such user" vs "wrong password"
    # turns the login form into a username oracle.
    assert wrong_pw.json()["detail"] == unknown_user.json()["detail"]


def test_login_rejects_deactivated_account(api):
    tc, base_data, db = api
    app.dependency_overrides.pop(get_current_user, None)
    user = base_data["lawyer"]
    user.password_hash = hash_password("CorrectHorse1!")
    user.is_active = False
    db.commit()

    resp = tc.post("/api/auth/login", json={"username": user.username, "password": "CorrectHorse1!"})
    assert resp.status_code == 401


def test_password_is_hashed_never_stored_plaintext(api):
    tc, base_data, db = api
    user = base_data["admin"]
    user.password_hash = hash_password("CorrectHorse1!")
    db.commit()
    assert user.password_hash != "CorrectHorse1!"
    assert user.password_hash.startswith("$2b$")
    assert verify_password("CorrectHorse1!", user.password_hash)


def test_protected_endpoint_requires_a_token(api):
    tc, base_data, db = api
    app.dependency_overrides.pop(get_current_user, None)
    assert tc.get("/api/cases").status_code == 401
    assert tc.get("/api/dashboard/stats").status_code == 401


# ------------------------------------------------------- 2. role boundaries --


ROLE_MATRIX = [
    # (role key, endpoint, expected status)
    ("admin", "/api/cases", 200),
    ("admin", "/api/documents", 200),
    ("admin", "/api/dashboard/stats", 200),
    ("lawyer", "/api/cases", 200),
    ("lawyer", "/api/documents", 200),
    ("client", "/api/cases", 200),
    ("client", "/api/documents", 200),
    # Client must never reach search, reminders or the audit log.
    ("client", "/api/search/case-number", 403),
    ("client", "/api/reminders", 403),
    ("client", "/api/dashboard/task-stats", 403),
]


@pytest.mark.parametrize("role_key,endpoint,expected", ROLE_MATRIX)
def test_role_access_matrix(api, role_key, endpoint, expected):
    tc, base_data, db = api
    _as(base_data[role_key])
    assert tc.get(endpoint).status_code == expected, f"{role_key} -> {endpoint}"


def test_client_sees_only_their_own_cases(api):
    tc, base_data, db = api
    other = Case(
        case_number="7777", automated_number="202607777", case_year=2026, court_id=base_data["court"].id,
        parties_ar="طرف آخر", civil_id="not-the-client",
    )
    db.add(other)
    db.commit()

    _as(base_data["admin"])
    assert len(tc.get("/api/cases").json()) == 2

    _as(base_data["client"])
    client_cases = tc.get("/api/cases").json()
    assert len(client_cases) == 1
    assert client_cases[0]["id"] == base_data["case"].id


def test_client_cannot_create_or_modify_a_case(api):
    tc, base_data, db = api
    _as(base_data["client"])
    created = tc.post("/api/cases", json={
        "case_number": "6666", "automated_number": "202606666", "case_year": 2026,
        "court_id": base_data["court"].id, "parties_ar": "x",
    })
    staged = tc.put(f"/api/cases/{base_data['case'].id}/stage", json={"stage": "closed"})
    assert created.status_code == 403
    assert staged.status_code == 403


# ---------------------------------------------------------- 3. cases + search --


def test_case_create_read_update_flow(api):
    tc, base_data, db = api
    _as(base_data["admin"])

    created = tc.post("/api/cases", json={
        "case_number": "4242", "automated_number": "202604242", "case_year": 2026,
        "court_id": base_data["court"].id,
        "parties_ar": "أ ضد ب", "parties_en": "A v B", "stage": "new",
    })
    assert created.status_code == 201
    case_id = created.json()["id"]

    fetched = tc.get(f"/api/cases/{case_id}")
    assert fetched.status_code == 200
    assert fetched.json()["case_number"] == "4242"
    # Creating a case seeds its first timeline entry -- the Case Details modal
    # renders an empty state if this ever stops happening.
    assert len(fetched.json()["timeline"]) == 1

    staged = tc.put(f"/api/cases/{case_id}/stage", json={"stage": "pleading"})
    assert staged.status_code == 200
    assert staged.json()["stage"] == "pleading"

    noted = tc.post(f"/api/cases/{case_id}/notes", json={"note_text": "internal strategy note"})
    assert noted.status_code == 201


def test_duplicate_case_number_year_is_rejected(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    payload = {
        "case_number": "5150", "automated_number": "202605150", "case_year": 2026,
        "court_id": base_data["court"].id, "parties_ar": "x",
    }
    assert tc.post("/api/cases", json=payload).status_code == 201
    assert tc.post("/api/cases", json=payload).status_code == 409


def test_closing_a_case_also_closes_its_status(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.put(f"/api/cases/{base_data['case'].id}/stage", json={"stage": "closed"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_search_by_case_number_and_automated_number(api):
    tc, base_data, db = api
    _as(base_data["admin"])

    by_number = tc.get("/api/search/case-number", params={"case_number": "1000"})
    assert by_number.status_code == 200
    assert len(by_number.json()) == 1

    # The same case is now reachable by its real Automated Number column
    # (db/migration_automated_case_number.sql). Before that column existed
    # this parameter was an alias that matched `case_number`, so searching
    # by a genuine Automated Number could only ever find a case whose SHORT
    # number happened to contain the same digits.
    by_auto = tc.get("/api/search/case-number", params={"automated_number": "202601000"})
    assert by_auto.status_code == 200
    assert len(by_auto.json()) == 1
    assert by_auto.json()[0]["case_number"] == "1000"

    # Supplying both must OR them across the two different columns, not AND
    # them: a caller giving both is trying two ways to find one case. Here
    # the Automated Number is deliberately one that matches nothing, so only
    # the OR semantics can return a row.
    both = tc.get("/api/search/case-number",
                  params={"case_number": "1000", "automated_number": "999999999"})
    assert len(both.json()) == 1

    no_match = tc.get("/api/search/case-number", params={"case_number": "does-not-exist"})
    assert no_match.json() == []


def test_search_by_both_identifiers_matching_the_same_case(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    resp = tc.get(
        "/api/search/case-number",
        params={"case_number": "1000", "automated_number": "202601000"},
    )
    assert resp.status_code == 200
    # One case, not two: the OR must not duplicate a row that satisfies
    # both halves of the condition.
    assert len(resp.json()) == 1
    assert resp.json()[0]["case_number"] == "1000"


def test_exact_automated_number_match_ranks_first(api):
    """Pins the ranking fix made when the two columns were split apart.

    The sort used to compute one `exact_target = case_number or
    automated_number` and compare it against `c.case_number` only. Once
    Automated Number became its own column that comparison could never
    match, so an exact Automated Number hit silently lost its rank boost --
    no error, just a worse result order that nobody would trace back here.

    Making the boost observable needs care. Automated Numbers are all
    exactly nine digits, so one can only CONTAIN another by being equal to
    it -- a same-length decoy can never appear alongside an exact match.
    The OR path is what makes it visible instead:

      case_number="100"        partially matches BOTH cases, exactly neither
      automated_number=...     exactly matches the second case only

    so both rows come back, and only the second is an exact hit. Without
    the fix, no row scores as exact and the order falls back to
    case_number ascending, which puts "1000" first -- this test fails.
    """
    tc, base_data, db = api
    _as(base_data["admin"])
    # Fixture case is 1000/2026. "100" is a prefix of both short numbers.
    db.add(Case(
        case_number="10001", automated_number="202688888", case_year=2026,
        court_id=base_data["court"].id, parties_ar="طعم",
    ))
    db.commit()

    resp = tc.get(
        "/api/search/case-number",
        params={"case_number": "100", "automated_number": "202688888"},
    )
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2, f"expected both cases back from the OR, got {len(rows)}"
    assert rows[0]["automated_number"] == "202688888", (
        "the exact Automated Number match is not ranked first -- the "
        "exact-match boost is comparing against the wrong column again"
    )


def test_automated_number_search_does_not_match_the_case_number_column(api):
    """Proves the two columns are genuinely separate.

    The obvious version of this test passes vacuously: searching
    automated_number="1000" against fixture case 1000/2026 DOES return it,
    because that case's automated number is 202601000 and the filter is a
    `contains`. So this builds a case whose Automated Number is deliberately
    UNRELATED to its short number -- possible because only the migration's
    backfill used the derivation rule, not the modal -- and then searches
    for the short number in the Automated Number field. A hit here would
    mean the alias behaviour came back.
    """
    tc, base_data, db = api
    _as(base_data["admin"])
    db.add(Case(
        case_number="1234", automated_number="202677777", case_year=2026,
        court_id=base_data["court"].id, parties_ar="غير مرتبط",
    ))
    db.commit()

    by_auto = tc.get("/api/search/case-number", params={"automated_number": "1234"})
    assert by_auto.status_code == 200
    assert by_auto.json() == [], (
        "searching the Automated Number field matched a value that exists "
        "only in case_number -- the columns are not separate"
    )

    # Control: the same case IS reachable by its real Automated Number.
    by_real = tc.get("/api/search/case-number", params={"automated_number": "202677777"})
    assert len(by_real.json()) == 1
    assert by_real.json()[0]["case_number"] == "1234"


# ------------------------------------------------------- 4. documents/grants --


def test_document_listing_is_case_scoped_for_clients(api):
    tc, base_data, db = api
    other_case = Case(
        case_number="8888", automated_number="202608888", case_year=2026, court_id=base_data["court"].id,
        parties_ar="غير ذي صلة", civil_id="someone-else",
    )
    db.add(other_case)
    db.flush()
    db.add(Document(
        case_id=base_data["case"].id, file_name="mine.pdf", file_type="pdf", file_size=10,
        storage_path="/tmp/mine.pdf", uploaded_by=base_data["admin"].id,
    ))
    db.add(Document(
        case_id=other_case.id, file_name="theirs.pdf", file_type="pdf", file_size=10,
        storage_path="/tmp/theirs.pdf", uploaded_by=base_data["admin"].id,
    ))
    db.commit()

    _as(base_data["admin"])
    assert len(tc.get("/api/documents").json()) == 2

    _as(base_data["client"])
    client_docs = tc.get("/api/documents").json()
    assert [d["file_name"] for d in client_docs] == ["mine.pdf"]


def test_temporary_upload_grant_lifecycle(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    granted = tc.post("/api/documents/grants", json={
        "case_id": base_data["case"].id, "duration_minutes": 30,
    })
    assert granted.status_code == 201, granted.text
    body = granted.json()
    assert body["status"] == "active"
    assert body["source"] == "grant"
    assert body["expires_at"] is not None  # a temporary window must expire

    _as(base_data["client"])
    mine = tc.get("/api/documents/my-upload-access")
    assert mine.status_code == 200
    assert any(g["case_id"] == base_data["case"].id for g in mine.json())


def test_standing_link_upload_access_is_distinguishable_from_a_timed_grant(api):
    """A standing `user_case_links.can_upload` permission and a one-time
    DocumentUploadGrant both grant upload rights, but the UI must label them
    honestly ("standing" vs "temporary until X") -- so `source` has to
    differentiate them and a standing link must not claim an expiry."""
    tc, base_data, db = api
    db.add(UserCaseLink(
        user_id=base_data["client"].id, case_id=base_data["case"].id,
        can_upload=True, linked_by=base_data["admin"].id,
    ))
    db.commit()

    _as(base_data["client"])
    rows = tc.get("/api/documents/my-upload-access").json()
    link_rows = [r for r in rows if r["source"] == "link"]
    assert link_rows, rows
    assert link_rows[0]["expires_at"] is None


def test_client_cannot_review_documents(api):
    tc, base_data, db = api
    doc = Document(
        case_id=base_data["case"].id, file_name="review-me.pdf", file_type="pdf", file_size=10,
        storage_path="/tmp/review-me.pdf", uploaded_by=base_data["admin"].id,
    )
    db.add(doc)
    db.commit()

    _as(base_data["client"])
    assert tc.put(f"/api/documents/{doc.id}/status", json={"status": "approved"}).status_code == 403

    _as(base_data["admin"])
    ok = tc.put(f"/api/documents/{doc.id}/status", json={"status": "approved"})
    assert ok.status_code == 200
    assert ok.json()["status"] == "approved"


# ------------------------------------------------------------ 5. notifications --


def test_stage_change_notifies_linked_client_without_leaking_internals(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    tc.put(f"/api/cases/{base_data['case'].id}/stage", json={"stage": "judgment"})

    notes = db.query(Notification).filter(Notification.user_id == base_data["client"].id).all()
    assert notes, "linked client was not notified of the stage change"
    body = " ".join((n.message_en or "") + (n.message_ar or "") for n in notes)
    assert "1000/2026" in body
    # Only the case number and the stage transition -- never the case summary
    # or any internal note text.
    assert "internal" not in body.lower()


def test_note_added_notifies_client_but_never_includes_the_note_body(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    secret = "PRIVILEGED-STRATEGY-DO-NOT-LEAK"
    tc.post(f"/api/cases/{base_data['case'].id}/notes", json={"note_text": secret})

    notes = db.query(Notification).filter(Notification.user_id == base_data["client"].id).all()
    assert notes, "linked client was not notified that a note was added"
    for n in notes:
        assert secret not in (n.message_en or "")
        assert secret not in (n.message_ar or "")


def test_unchanged_stage_does_not_emit_a_notification(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    before = db.query(Notification).count()
    current = tc.get(f"/api/cases/{base_data['case'].id}").json()["stage"]
    tc.put(f"/api/cases/{base_data['case'].id}/stage", json={"stage": current})
    assert db.query(Notification).count() == before


def test_notifications_are_scoped_to_their_recipient(api):
    tc, base_data, db = api
    db.add(Notification(
        user_id=base_data["admin"].id, type="system",
        message_ar="خاص بالمسؤول", message_en="admin only",
    ))
    db.commit()

    _as(base_data["client"])
    client_msgs = [n["message_en"] for n in tc.get("/api/notifications").json()]
    assert "admin only" not in client_msgs


# ---------------------------------------------------------------- 6. dashboard --


def test_dashboard_stats_are_scoped_per_role(api):
    tc, base_data, db = api
    db.add(Case(
        case_number="3333", automated_number="202603333", case_year=2026, court_id=base_data["court"].id,
        parties_ar="أخرى", civil_id="different-person",
    ))
    db.commit()

    _as(base_data["admin"])
    assert tc.get("/api/dashboard/stats").json()["active_cases"] == 2

    _as(base_data["client"])
    assert tc.get("/api/dashboard/stats").json()["active_cases"] == 1


def test_upcoming_hearings_excludes_past_and_unscheduled(api):
    tc, base_data, db = api
    now = datetime.utcnow()
    db.add(CourtSession(
        case_id=base_data["case"].id, circuit_ar="دائرة", circuit_en="Circuit",
        session_at=now + timedelta(days=3), status="scheduled",
    ))
    db.add(CourtSession(
        case_id=base_data["case"].id, circuit_ar="دائرة", circuit_en="Circuit",
        session_at=now - timedelta(days=3), status="scheduled",
    ))
    db.add(CourtSession(
        case_id=base_data["case"].id, circuit_ar="دائرة", circuit_en="Circuit",
        session_at=now + timedelta(days=5), status="cancelled",
    ))
    db.commit()

    _as(base_data["admin"])
    rows = tc.get("/api/dashboard/upcoming-hearings").json()
    assert len(rows) == 1


def test_task_stats_refused_for_client_allowed_for_staff(api):
    tc, base_data, db = api
    _as(base_data["client"])
    assert tc.get("/api/dashboard/task-stats").status_code == 403
    _as(base_data["lawyer"])
    assert tc.get("/api/dashboard/task-stats").status_code == 200


# ------------------------------------------------------- 7. user<->case links --


def test_link_unlink_relink_and_upload_toggle(api):
    tc, base_data, db = api
    case_id = base_data["case"].id
    client_id = base_data["client"].id
    _as(base_data["admin"])

    created = tc.post(f"/api/cases/{case_id}/links", json={"user_id": client_id, "can_upload": False})
    assert created.status_code == 201
    assert created.json()["can_upload"] is False
    link_id = created.json()["id"]

    # Re-linking the same pair supersedes rather than stacking a second
    # active link (cases.py documents this; a DB unique index enforces it).
    relinked = tc.post(f"/api/cases/{case_id}/links", json={"user_id": client_id, "can_upload": True})
    assert relinked.status_code == 201
    assert relinked.json()["can_upload"] is True
    active = tc.get(f"/api/cases/{case_id}/links").json()
    assert len(active) == 1

    removed = tc.delete(f"/api/cases/{case_id}/links/{relinked.json()['id']}")
    assert removed.status_code == 204
    assert tc.get(f"/api/cases/{case_id}/links").json() == []
    assert link_id  # first link retained as revoked history, not deleted


def test_client_cannot_manage_case_links(api):
    tc, base_data, db = api
    _as(base_data["client"])
    resp = tc.post(
        f"/api/cases/{base_data['case'].id}/links",
        json={"user_id": base_data["client"].id, "can_upload": True},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------- 8. reminders --


def test_reminder_create_and_resolve(api):
    tc, base_data, db = api
    _as(base_data["admin"])
    created = tc.post("/api/reminders", json={
        "case_id": base_data["case"].id,
        "type": "follow_up",
        "due_at": (datetime.utcnow() + timedelta(days=3)).isoformat(),
        "note": "chase the court clerk",
        "assigned_to": base_data["lawyer"].id,
    })
    assert created.status_code == 201, created.text
    reminder_id = created.json()["id"]

    # The assignee is told immediately, not only once a pre-due layer fires.
    assert db.query(Notification).filter(Notification.user_id == base_data["lawyer"].id).count() >= 1

    _as(base_data["lawyer"])
    resolved = tc.put(f"/api/reminders/{reminder_id}/resolve", json={"status": "done"})
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "done"


def test_unrelated_user_cannot_resolve_someone_elses_reminder(api):
    tc, base_data, db = api
    reminder = CaseReminder(
        case_id=base_data["case"].id, type="follow_up",
        due_at=datetime.utcnow() + timedelta(days=2), note="not yours",
        created_by=base_data["admin"].id, assigned_to=base_data["admin"].id,
    )
    db.add(reminder)
    db.commit()

    _as(base_data["lawyer"])
    assert tc.put(f"/api/reminders/{reminder.id}/resolve", json={"status": "done"}).status_code == 403


def test_status_update_request_resolution_advances_the_case_stage(api):
    tc, base_data, db = api
    reminder = CaseReminder(
        case_id=base_data["case"].id, type="status_update_request",
        requested_stage="execution",
        due_at=datetime.utcnow() + timedelta(days=2), note="please advance",
        created_by=base_data["admin"].id, assigned_to=base_data["lawyer"].id,
    )
    db.add(reminder)
    db.commit()

    _as(base_data["lawyer"])
    resp = tc.put(f"/api/reminders/{reminder.id}/resolve", json={"status": "done"})
    assert resp.status_code == 200
    db.refresh(base_data["case"])
    assert base_data["case"].stage == "execution"


# ------------------------------------------------- 10. factory reset gating --


def test_factory_reset_requires_the_exact_confirmation_phrase(api):
    """NEVER executes a reset: every assertion here is on a REJECTED call.
    The happy path is deliberately untested — running it would wipe the
    database the rest of this suite is using."""
    tc, base_data, db = api
    _as(base_data["admin"])
    assert tc.post("/api/admin/reset-database", json={"confirm_phrase": ""}).status_code == 400
    assert tc.post("/api/admin/reset-database", json={"confirm_phrase": "reset database"}).status_code == 400
    assert tc.post("/api/admin/reset-database", json={"confirm_phrase": "RESET  DATABASE"}).status_code == 400


def test_factory_reset_is_admin_only(api):
    tc, base_data, db = api
    for role_key in ("lawyer", "client"):
        _as(base_data[role_key])
        resp = tc.post("/api/admin/reset-database", json={"confirm_phrase": "RESET DATABASE"})
        assert resp.status_code == 403, f"{role_key} was not refused"
