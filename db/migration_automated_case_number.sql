-- =====================================================================
--  Adds cases.automated_number  (the "Automated Number" / الرقم الآلي)
--
--  MANUAL, ONE-TIME, NOT RUN BY THE APPLICATION. Same convention as
--  db/migration_procedural_intelligence.sql: nothing under backend/ ever
--  executes this file, and no application code path applies it.
--
--  WHY THIS EXISTS
--  "Automated Number" already appeared in the UI as a SEARCH field, but
--  had no column behind it. backend/app/routers/search.py matched it
--  against `case_number` as an alias and said so in its own comment:
--    "Automated Number has no dedicated column yet -- it's an alternate
--     way to identify the same case ... so it matches the same
--     case_number column."
--  This migration makes it a real, stored, unique identifier. That
--  comment in search.py is rewritten in the same change set.
--
--  WHAT IT DOES NOT DO
--  It does not drop or alter `case_year`, and it does not touch
--  uq_case_number_year. `case_year` is DERIVED from the first four
--  digits of automated_number when a case is created, so the existing
--  "1123/2024" display format, the uniqueness key, and every existing
--  search path keep working unchanged.
--
--  FORMAT
--  YYYYNNNNN -- a four-digit year followed by five digits, nine
--  characters in total (e.g. 202400001). Enforced client-side, again
--  server-side in the Pydantic schema, and once more by a CHECK
--  constraint here so a write path that bypasses the API (a manual
--  INSERT, a restored dump, a script) cannot introduce a bad value.
--
--  HOW TO RUN
--  Take a backup first. Then run the steps IN ORDER and read the output
--  of each verification query before continuing. STEP 0 and the queries
--  inside STEP 2 are read-only; do not proceed past either if what they
--  return is not what the comment says to expect.
-- =====================================================================


-- ---------------------------------------------------------------------
-- STEP 0 -- PRE-FLIGHT GUARDS (read-only; 0a/0b/0c MUST return no rows)
--
-- These were all verified empty against the live database on
-- 17 Sep 2026, against the five rows then present. They are kept in the
-- file anyway, because this migration may be run later, or against a
-- restored copy, or on another environment, where they may not be.
-- ---------------------------------------------------------------------

-- 0a. Leading-zero collision.
--     uq_case_number_year permits BOTH '0847' and '847' in the same year
--     as two distinct rows, and LPAD(...,5,'0') maps both to '00847'.
--     If this returns anything, STOP: the derived values would not be
--     unique, and STEP 3 would fail *after* STEP 2 had already written.
SELECT case_year,
       LPAD(case_number, 5, '0') AS padded,
       COUNT(*)                  AS n,
       GROUP_CONCAT(case_number) AS colliding_numbers
FROM cases
GROUP BY case_year, padded
HAVING n > 1;

-- 0b. A case_number longer than 5 digits derives a value longer than the
--     9-character YYYYNNNNN format, which the CHECK in STEP 3 rejects.
SELECT id, case_number, case_year
FROM cases
WHERE CHAR_LENGTH(case_number) > 5;

-- 0c. A non-numeric case_number cannot derive a numeric automated number.
SELECT id, case_number, case_year
FROM cases
WHERE case_number NOT REGEXP '^[0-9]+$';

-- Baseline row count, to compare against after STEP 2.
SELECT COUNT(*) AS cases_before FROM cases;


-- ---------------------------------------------------------------------
-- STEP 1 -- ADD THE COLUMN, NULLABLE
--
-- Nullable first, because adding a NOT NULL column with no default to a
-- table that already has rows is rejected outright. On MySQL 8 this uses
-- the INSTANT algorithm: no table rebuild and no meaningful lock.
--
-- No separate secondary index is created here on purpose. STEP 3's
-- UNIQUE constraint creates its own index on the same column, so an
-- index added here would be redundant and would leave the table carrying
-- two indexes for one column.
-- ---------------------------------------------------------------------
ALTER TABLE cases
  ADD COLUMN automated_number VARCHAR(32) NULL AFTER case_number;


-- ---------------------------------------------------------------------
-- STEP 2 -- BACKFILL EXISTING ROWS
--
-- Deterministic and derived purely from (case_number, case_year), which
-- is ALREADY unique -- so the derived value is unique too, provided
-- guard 0a passed. The 4-digit year plus LPAD to 5 digits produces
-- exactly the YYYYNNNNN shape new cases will use, so a backfilled row is
-- indistinguishable from one entered through the New Case modal.
--
-- `WHERE automated_number IS NULL` makes this safely re-runnable: a
-- second execution matches nothing and changes nothing.
-- ---------------------------------------------------------------------
UPDATE cases
   SET automated_number = CONCAT(case_year, LPAD(case_number, 5, '0'))
 WHERE automated_number IS NULL;

-- VERIFY BEFORE ENFORCING. Expect:
--   total           = cases_before from STEP 0
--   nulls           = 0
--   distinct_values = total
--   bad_format      = 0
-- If any of those differ, STOP and do not run STEP 3 -- the column is
-- still nullable at this point, so the rollback is simply dropping it.
SELECT COUNT(*)                                      AS total,
       SUM(automated_number IS NULL)                 AS nulls,
       COUNT(DISTINCT automated_number)              AS distinct_values,
       SUM(automated_number NOT REGEXP '^[0-9]{9}$') AS bad_format
FROM cases;


-- ---------------------------------------------------------------------
-- STEP 3 -- ENFORCE
--
-- Only after STEP 2's verification passes. MODIFY restates the whole
-- column definition, which is how MySQL's syntax works -- VARCHAR(32)
-- here is the same type as STEP 1, only the nullability changes.
-- ---------------------------------------------------------------------
ALTER TABLE cases
  MODIFY automated_number VARCHAR(32) NOT NULL;

ALTER TABLE cases
  ADD CONSTRAINT uq_cases_automated_number UNIQUE (automated_number);

-- Format enforcement at the database level, not only in application
-- code. MySQL enforces CHECK from 8.0.16; this server is 8.4.9.
ALTER TABLE cases
  ADD CONSTRAINT ck_cases_automated_number_format
  CHECK (automated_number REGEXP '^[0-9]{9}$');


-- ---------------------------------------------------------------------
-- FINAL VERIFICATION
-- ---------------------------------------------------------------------

-- Expect one row per index part for uq_cases_automated_number, and
-- Non_unique = 0.
SHOW INDEX FROM cases WHERE Key_name = 'uq_cases_automated_number';

-- Expect the CHECK constraint to be listed and ENFORCED = YES.
SELECT cc.CONSTRAINT_NAME, cc.CHECK_CLAUSE, tc.ENFORCED
FROM information_schema.CHECK_CONSTRAINTS cc
JOIN information_schema.TABLE_CONSTRAINTS tc
  ON tc.CONSTRAINT_NAME   = cc.CONSTRAINT_NAME
 AND tc.CONSTRAINT_SCHEMA = cc.CONSTRAINT_SCHEMA
WHERE cc.CONSTRAINT_NAME = 'ck_cases_automated_number_format';

-- Expect every row populated, nine digits, year prefix matching case_year.
SELECT id, case_number, case_year, automated_number
FROM cases
ORDER BY id;


-- ---------------------------------------------------------------------
-- AFTER THIS FILE HAS BEEN APPLIED
--
--  1. Mirror the change by hand into db/schema.sql -- that file is this
--     project's canonical DDL and is NOT generated from the ORM, so it
--     does not update itself (same convention as
--     docs/MIGRATION_PROCEDURAL_INTELLIGENCE.md section 4).
--  2. Add the real mapped column to backend/app/models.py:
--         automated_number: Mapped[str] = mapped_column(unique=True)
--     placed immediately after `case_number`.
--  3. Recycle the ASLG application pool so the running worker picks up
--     the new model.
--
-- Rollback: db/rollback_automated_case_number.sql -- and revert the code
-- FIRST, then the schema, for the same reason the Procedural
-- Intelligence runbook gives: a live worker holding a mapped column that
-- the table no longer has will 500 on every read and every insert.
-- ---------------------------------------------------------------------
