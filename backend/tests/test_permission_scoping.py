"""Regression tests for the pre-existing case-visibility scoping
(backend/app/routers/cases.py::_scope_query and get_permission_level) —
establishes the baseline BEFORE any Procedural Intelligence code is added,
per the Phase 1 implementation plan step 0. Also proves the extension
point new routers (procedures/deadlines/rules/official_sync) must use:
`_scope_query`'s civil_id UNION user_case_links pattern must keep working
unchanged, since every new router reuses it rather than re-implementing
its own case-visibility rule."""

from app.deps import get_permission_level
from app.models import Case, UserCaseLink
from app.routers.cases import _scope_query


def test_admin_sees_every_case(db, base_data):
    admin = base_data["admin"]
    visible = _scope_query(db, admin).all()
    assert len(visible) == 1
    assert visible[0].id == base_data["case"].id


def test_client_with_matching_civil_id_sees_their_own_case(db, base_data):
    client = base_data["client"]  # civil_id="12345", matches base_data["case"]
    visible = _scope_query(db, client).all()
    assert [c.id for c in visible] == [base_data["case"].id]


def test_client_without_civil_id_match_sees_nothing(db, base_data):
    client = base_data["client"]
    client.civil_id = "does-not-match-anything"
    db.commit()
    visible = _scope_query(db, client).all()
    assert visible == []


def test_explicit_user_case_link_grants_visibility_independent_of_civil_id(db, base_data):
    """A second, unrelated case linked to the client via user_case_links
    (not a civil_id match) must also become visible — the union, not just
    the civil_id branch, is what every new module's own scoping call must
    inherit unchanged."""
    client = base_data["client"]
    client.civil_id = "no-match"
    db.commit()

    other_case = Case(
        case_number="2000", automated_number="202602000", case_year=2026, court_id=base_data["court"].id,
        parties_ar="طرف آخر", civil_id="9999999",
    )
    db.add(other_case)
    db.flush()
    db.add(UserCaseLink(user_id=client.id, case_id=other_case.id, linked_by=base_data["admin"].id))
    db.commit()

    visible = _scope_query(db, client).all()
    assert [c.id for c in visible] == [other_case.id]


def test_get_permission_level_defaults_to_none_for_unconfigured_module(db, base_data):
    """Both "unknown module" paths must resolve to 'none' rather than raising
    or defaulting open: a module code that doesn't exist at all, and a real
    module that simply has no RolePermission row for this role. The fixture
    now mirrors the full production matrix, so the second case is built here
    explicitly instead of relying on a gap in the fixture."""
    from app.models import Module

    consultant_role_id = base_data["roles"]["consultant"].id

    # (a) module code that was never registered
    assert get_permission_level(db, consultant_role_id, "no_such_module") == "none"

    # (b) a registered module with no grant for this role
    db.add(Module(code="ungranted_module"))
    db.commit()
    assert get_permission_level(db, consultant_role_id, "ungranted_module") == "none"


def test_new_modules_default_to_none_until_explicitly_granted(db, base_data):
    """The four new modules this feature adds (procedures/deadlines/
    official_sync/rules_admin) must be as strict-by-default as every
    existing module: a role with no explicit grant sees 'none', never an
    implicit allow. `rules_admin` in particular is deliberately granted to
    ONLY Admin/Lawyer in the real matrix (db/migration_procedural_
    intelligence.sql section 5) -- consultant and delegate must see 'none'."""
    for role_code in ("consultant", "delegate"):
        assert get_permission_level(db, base_data["roles"][role_code].id, "rules_admin") == "none"
