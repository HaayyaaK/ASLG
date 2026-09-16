"""Shared pytest fixtures.

Every test in this suite runs against a throwaway in-memory SQLite
database, NEVER the real MySQL database this app talks to in dev/production
(`backend/.env`'s DB_HOST/DB_USER/DB_PASSWORD are never read for connection
purposes here — see `engine` below, which is a fresh sqlite:///:memory:
engine per test, entirely independent of `app.database.engine`). Nothing in
this test suite issues a single write against the real database.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base  # noqa: E402
from app.models import (  # noqa: E402
    Case,
    CaseProcedure,
    CaseType,
    Court,
    Module,
    ProcedureRule,
    ProcedureType,
    Role,
    RolePermission,
    User,
)
from app.security import hash_password  # noqa: E402


@pytest.fixture()
def db() -> Session:
    """A fresh, empty schema for every test — isolation, not speed, is the
    point: two tests must never be able to see each other's rows."""
    # StaticPool is required, not just check_same_thread=False: SQLite's
    # default pool for a `:memory:` URL is one connection PER THREAD, which
    # means each thread would silently get its OWN empty database — fatal
    # for test_client_isolation.py, whose FastAPI TestClient requests run
    # each endpoint in a worker thread (Starlette's run_in_threadpool) that
    # is not the thread this fixture set up the schema on. StaticPool pins
    # every checkout to the single real connection this fixture opened.
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def premigration_db() -> Session:
    """A schema matching the LIVE production database as it exists right
    now -- before db/migration_procedural_intelligence.sql has been applied
    -- rather than the full ORM metadata `db` above creates.

    Built by creating the full schema (so every OTHER table Procedural
    Intelligence added -- case_procedures, procedure_rules, etc. -- still
    exists, matching reality: those are genuinely new tables nobody has
    queried against the old schema yet) and then dropping exactly the four
    columns this phase's ORM changes added to two PRE-EXISTING tables
    (`cases.case_type_id`/`procedural_status_id`/`last_official_check_at`,
    `documents.doc_class_id`) -- confirmed via a live `DESCRIBE cases` /
    `DESCRIBE documents` against the real database to be genuinely absent
    until the migration runs. Exists so a regression like the one that
    actually reached production (see test_premigration_compatibility.py)
    is caught by `pytest` before it ever reaches a real deployment again.
    """
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    # SQLite's ALTER TABLE ... DROP COLUMN refuses to drop a column that
    # participates in a FOREIGN KEY clause on that same table (which
    # case_type_id/procedural_status_id both do) -- "error in table cases
    # after drop column: unknown column ... in foreign key definition".
    # Dropping and recreating the two affected tables outright sidesteps
    # that: SQLite does not enforce referential integrity between tables
    # unless `PRAGMA foreign_keys=ON` is set (it isn't, here or anywhere
    # else this test suite sets up its schema), so the already-created
    # child tables (documents, case_timeline, case_procedures, ...) are
    # completely unaffected by their referenced parent table being
    # replaced afterward. Column list below is copied verbatim from a live
    # `DESCRIBE cases` / `DESCRIBE documents` against the real production
    # database, i.e. exactly what's actually there today.
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE cases")
        conn.exec_driver_sql("""
            CREATE TABLE cases (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_number VARCHAR(32) NOT NULL,
              case_year SMALLINT NOT NULL,
              court_id SMALLINT NOT NULL,
              category_ar VARCHAR(80),
              category_en VARCHAR(80),
              parties_ar VARCHAR(255) NOT NULL,
              parties_en VARCHAR(255),
              civil_id VARCHAR(20),
              status VARCHAR(10) NOT NULL DEFAULT 'active',
              stage VARCHAR(10) NOT NULL DEFAULT 'new',
              assigned_lawyer_id INTEGER,
              summary_ar TEXT,
              summary_en TEXT,
              next_hearing_at DATETIME,
              created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.exec_driver_sql("DROP TABLE documents")
        conn.exec_driver_sql("""
            CREATE TABLE documents (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              case_id INTEGER NOT NULL,
              file_name VARCHAR(255) NOT NULL,
              file_type VARCHAR(10) NOT NULL,
              file_size INTEGER NOT NULL,
              storage_path VARCHAR(500) NOT NULL,
              status VARCHAR(10) NOT NULL DEFAULT 'pending',
              uploaded_by INTEGER NOT NULL,
              uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _seed_base_data(db: Session) -> dict:
    """The minimum reference data most tests build on: roles, the modules
    this feature adds, one court of each level actually used below, and one
    Admin + one Lawyer user. Mirrors backend/seed.py's real data in shape
    without importing it directly, so a change to the demo dataset can never
    silently break this suite (and vice versa).

    Plain function, not a fixture, so it can be reused verbatim against
    both the normal full-schema `db` fixture and the deliberately
    old-schema `premigration_db` fixture above.
    """
    roles = {}
    for code in ("Admin", "Lawyer", "consultant", "delegate", "User"):
        r = Role(code=code, name_ar=code, name_en=code)
        db.add(r)
        roles[code] = r
    db.flush()

    modules = {}
    for code in ("dashboard", "search", "cases", "documents", "notifications", "users", "reminders", "procedures", "deadlines", "official_sync", "rules_admin"):
        m = Module(code=code)
        db.add(m)
        modules[code] = m
    db.flush()

    # Mirrors the access matrix from db/migration_procedural_intelligence.sql
    # section 5 / Phase 1 blueprint 4.7 -- kept in this fixture rather than
    # imported from anywhere, so a change to the real migration's matrix
    # cannot silently desync the tests that assert on it (test_client_
    # isolation.py exercises exactly these rows over real HTTP).
    # The COMPLETE production access matrix, role by role -- deliberately a
    # verbatim mirror of backend/seed.py's PERMISSIONS (which is itself
    # mirrored by db/migration_procedural_intelligence.sql section 5 for the
    # four Procedural Intelligence modules). Every pair is inserted
    # explicitly, including the "none" ones, exactly as seed.py does: a test
    # that passes only because a permission row was *missing* from the
    # fixture proves nothing about the real system, which is how an earlier
    # version of this fixture produced four misleading failures.
    permissions = {
        "Admin":      {"dashboard": "full",    "search": "full", "cases": "full",    "documents": "full", "notifications": "full", "users": "full", "reminders": "full", "procedures": "full", "deadlines": "full", "official_sync": "full", "rules_admin": "full"},
        "Lawyer":     {"dashboard": "full",    "search": "full", "cases": "full",    "documents": "full", "notifications": "full", "users": "none", "reminders": "full", "procedures": "full", "deadlines": "full", "official_sync": "full", "rules_admin": "view"},
        "consultant": {"dashboard": "full",    "search": "edit", "cases": "limited", "documents": "edit", "notifications": "full", "users": "none", "reminders": "edit", "procedures": "edit", "deadlines": "edit", "official_sync": "edit", "rules_admin": "none"},
        "delegate":   {"dashboard": "full",    "search": "edit", "cases": "view",    "documents": "edit", "notifications": "full", "users": "none", "reminders": "view", "procedures": "view", "deadlines": "view", "official_sync": "edit", "rules_admin": "none"},
        "User":       {"dashboard": "limited", "search": "none", "cases": "own",     "documents": "own",  "notifications": "full", "users": "none", "reminders": "none", "procedures": "own",  "deadlines": "own",  "official_sync": "none", "rules_admin": "none"},
    }
    for role_code, mods in permissions.items():
        for module_code, level in mods.items():
            db.add(RolePermission(role_id=roles[role_code].id, module_id=modules[module_code].id, access_level=level))

    admin = User(
        name_en="Admin User", name_ar="مدير", username="admin.test", role_id=roles["Admin"].id,
        password_hash=hash_password("x"), is_active=True,
    )
    lawyer = User(
        name_en="Lawyer User", name_ar="محامي", username="lawyer.test", role_id=roles["Lawyer"].id,
        password_hash=hash_password("x"), is_active=True, is_owner=True,
    )
    client = User(
        name_en="Client User", name_ar="عميل", username="client.test", role_id=roles["User"].id,
        password_hash=hash_password("x"), is_active=True, civil_id="12345",
    )
    db.add_all([admin, lawyer, client])
    db.flush()

    court = Court(level_code="first_instance", name_ar="المحكمة الكلية", name_en="Court of First Instance")
    court_appeal = Court(level_code="appeal", name_ar="محكمة الاستئناف", name_en="Court of Appeal")
    db.add_all([court, court_appeal])
    db.flush()

    case = Case(
        case_number="1000", case_year=2026, court_id=court.id,
        parties_ar="طرف 1 ضد طرف 2", parties_en="Party 1 v Party 2",
        civil_id="12345", assigned_lawyer_id=lawyer.id,
    )
    db.add(case)
    db.flush()

    db.commit()
    return {
        "roles": roles, "modules": modules,
        "admin": admin, "lawyer": lawyer, "client": client,
        "court": court, "court_appeal": court_appeal, "case": case,
    }


@pytest.fixture()
def base_data(db: Session) -> dict:
    return _seed_base_data(db)


@pytest.fixture()
def premigration_base_data(premigration_db: Session) -> dict:
    return _seed_base_data(premigration_db)


@pytest.fixture()
def procedure_types(db: Session) -> dict:
    types = {}
    for code, terminal in [
        ("case_filed", False),
        ("judgment_issued", False),
        ("appeal_filed", False),
        ("appeal_judgment_issued", False),
        ("cassation_filed", False),
        ("execution_closed", True),
    ]:
        t = ProcedureType(code=code, name_ar=code, name_en=code, is_terminal=terminal)
        db.add(t)
        types[code] = t
    db.flush()
    db.commit()
    return types


def make_procedure(db: Session, case: Case, ptype: ProcedureType, recorded_by_id: int, occurred_at: datetime | None = None) -> CaseProcedure:
    proc = CaseProcedure(
        case_id=case.id,
        procedure_type_id=ptype.id,
        occurred_at=occurred_at or datetime.utcnow(),
        recorded_by=recorded_by_id,
    )
    db.add(proc)
    db.commit()
    db.refresh(proc)
    return proc


def make_rule(
    db: Session,
    *,
    code: str,
    trigger: ProcedureType,
    expected: ProcedureType,
    deadline_days: int,
    day_basis: str = "calendar",
    is_enabled: bool = True,
    source_tier: str = "official_verified",
    verified_by_user_id: int | None = None,
    version: int = 1,
    court_level_code: str | None = None,
    case_type_id: int | None = None,
) -> ProcedureRule:
    rule = ProcedureRule(
        code=code,
        version=version,
        trigger_procedure_type_id=trigger.id,
        expected_procedure_type_id=expected.id,
        deadline_days=deadline_days,
        day_basis=day_basis,
        is_enabled=is_enabled,
        source_tier=source_tier,
        verified_by_user_id=verified_by_user_id,
        verified_at=datetime.utcnow() if verified_by_user_id else None,
        court_level_code=court_level_code,
        case_type_id=case_type_id,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule
