"""The "seeded database == migrated database" invariant.

Two completely separate pieces of code decide what a case's Automated
Number is for the five demo cases:

  * db/migration_automated_case_number.sql STEP 2, which backfilled the
    rows that already existed on the live server:
        CONCAT(case_year, LPAD(case_number, 5, '0'))
  * backend/seed.py, which builds those same five cases from scratch for a
    fresh install or a Factory Reset:
        f"{c.case_year}{c.case_number.zfill(5)}"

Nothing makes those agree except that somebody wrote them to agree. If they
drift, a Factory Reset silently produces demo data whose identifiers differ
from what the migration produced for the identical input -- and since both
are "valid", nothing fails and nobody notices until two environments are
compared by hand.
"""

import re
from pathlib import Path

import pytest

from app.models import Case

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MIGRATION_SQL = PROJECT_ROOT / "db" / "migration_automated_case_number.sql"
SEED_PY = PROJECT_ROOT / "backend" / "seed.py"

AUTOMATED_NUMBER_RE = re.compile(r"^\d{9}$")


@pytest.fixture()
def seeded(db, tmp_path, monkeypatch):
    """Runs the REAL seed against the throwaway in-memory database.

    Two monkeypatches, and neither is incidental -- do not "tidy" them away:

      * `upload_dir` -- seed.py writes real placeholder documents to disk
        (see its seed_docs loop). Unpatched, running it from a test would
        drop orphaned files into the LIVE uploads directory, which on this
        deployment is the production one. Pointing it at pytest's tmp_path
        keeps a test a test.

        Note it is `upload_dir` that is patched, not `upload_path`:
        `upload_path` is a read-only computed property that resolves
        `upload_dir` and mkdirs it, and pydantic rejects assignment to a
        property with no setter. Patching the underlying field is both what
        works and what genuinely redirects the writes.
      * the two seed passwords -- seed.py raises unless they are set, by
        design (no hardcoded fallback, deliberately). Reading them from the
        real .env would make this test pass or fail depending on the
        machine's configuration rather than on the code under test.
        They are SecretStr because that is what the real settings hold --
        handing seed.py a plain str here would test a shape the
        application never actually sees.
    """
    from pydantic import SecretStr

    from app.config import settings
    from seed import run_seed

    monkeypatch.setattr(settings, "upload_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "seed_admin_password", SecretStr("test-admin-pw"), raising=False)
    monkeypatch.setattr(settings, "seed_staff_password", SecretStr("test-staff-pw"), raising=False)

    run_seed(db)
    db.commit()
    return db.query(Case).order_by(Case.id).all()


def test_seeded_cases_all_have_a_valid_automated_number(seeded):
    assert len(seeded) == 5, "the seed no longer creates exactly five demo cases"
    for c in seeded:
        assert c.automated_number, f"case {c.case_number}/{c.case_year} has no Automated Number"
        assert AUTOMATED_NUMBER_RE.match(c.automated_number), (
            f"case {c.case_number}/{c.case_year} has Automated Number "
            f"{c.automated_number!r}, which is not nine digits -- the live "
            f"database's CHECK constraint would reject this row"
        )


def test_every_seeded_automated_number_follows_the_derivation_rule(seeded):
    for c in seeded:
        expected = f"{c.case_year}{c.case_number.zfill(5)}"
        assert c.automated_number == expected, (
            f"case {c.case_number}/{c.case_year} seeded as {c.automated_number!r} "
            f"but the migration's backfill would have produced {expected!r}"
        )


def test_seeded_automated_numbers_are_unique(seeded):
    """uq_cases_automated_number would reject a duplicate on a real
    database, so a seed that produced one would fail a Factory Reset
    part-way through, leaving the database half-populated."""
    numbers = [c.automated_number for c in seeded]
    assert len(set(numbers)) == len(numbers), f"duplicate Automated Numbers in seed data: {numbers}"


def test_seed_and_migration_derivation_rule_stay_in_sync():
    """Reads the rule out of BOTH files and checks they still agree.

    Breaking this test means one of two files was changed without the
    other, and that the migration's backfill and seed.py will now produce
    different Automated Numbers for the same case:

      db/migration_automated_case_number.sql  (STEP 2's UPDATE)
      backend/seed.py                         (the loop after case5)

    Fix by making them match again -- not by relaxing this assertion.
    """
    sql = MIGRATION_SQL.read_text(encoding="utf-8")
    seed_src = SEED_PY.read_text(encoding="utf-8")

    sql_expr = re.search(
        r"SET\s+automated_number\s*=\s*(CONCAT\([^)]*\([^)]*\)[^)]*\))", sql, re.I
    )
    assert sql_expr, "could not find the backfill expression in the migration file"
    normalised_sql = re.sub(r"\s+", "", sql_expr.group(1)).upper()
    assert normalised_sql == "CONCAT(CASE_YEAR,LPAD(CASE_NUMBER,5,'0'))", (
        f"the migration's backfill rule changed: {sql_expr.group(1)}"
    )

    py_expr = re.search(r'automated_number\s*=\s*(f"[^"]*")', seed_src)
    assert py_expr, "could not find the derivation expression in seed.py"
    assert py_expr.group(1) == 'f"{c.case_year}{c.case_number.zfill(5)}"', (
        f"seed.py's derivation rule changed: {py_expr.group(1)}"
    )
