-- =====================================================================
--  ROLLBACK for db/migration_automated_case_number.sql
--
--  MANUAL, ONE-TIME, NOT RUN BY THE APPLICATION.
--
--  REVERT THE CODE FIRST, THEN RUN THIS.
--  Order matters and getting it wrong is an outage, not an inconvenience:
--  a running worker whose Case model still declares `automated_number`
--  will 500 on every read AND every insert the moment the column is
--  gone -- SQLAlchemy selects and inserts every mapped column, and no
--  mapped_column configuration changes that. This is not hypothetical;
--  it is exactly the September 2026 production outage recorded in
--  backend/tests/test_premigration_compatibility.py.
--
--  So, in this order:
--    1. Remove `automated_number` from backend/app/models.py.
--    2. Revert the code that depends on it -- the New Case modal field
--       in js/pages/cases.js, the validator in backend/app/schemas.py,
--       the create path in backend/app/routers/cases.py, the real-column
--       match in backend/app/routers/search.py (back to the case_number
--       alias), and the five Case(...) constructions in backend/seed.py.
--    3. Recycle the ASLG application pool.
--    4. Only then run this file.
--    5. Mirror the removal back into db/schema.sql by hand.
--
--  DATA LOSS: dropping the column discards every Automated Number,
--  including any entered through the UI after the migration was applied.
--  Values that were BACKFILLED are reproducible (they derive from
--  case_number and case_year), but values a user typed are not. Take a
--  backup first if any case has been created since the migration:
--
--    SELECT id, case_number, case_year, automated_number
--    FROM cases
--    WHERE automated_number <> CONCAT(case_year, LPAD(case_number,5,'0'));
--
--  Anything that query returns is a hand-entered value that this
--  rollback destroys and cannot recompute.
-- =====================================================================


-- The CHECK constraint must go first: MySQL refuses to drop a column
-- that a CHECK constraint still references.
ALTER TABLE cases DROP CHECK ck_cases_automated_number_format;

-- Then the unique index. (The migration deliberately creates no second,
-- non-unique index on this column, so there is only this one to drop.)
ALTER TABLE cases DROP INDEX uq_cases_automated_number;

-- Then the column itself.
ALTER TABLE cases DROP COLUMN automated_number;


-- ---------------------------------------------------------------------
-- VERIFICATION -- all three should show the column and its constraints
-- are gone, and that nothing else about `cases` changed.
-- ---------------------------------------------------------------------

-- Expect: no row named automated_number.
SELECT COLUMN_NAME, IS_NULLABLE, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'cases'
  AND COLUMN_NAME  = 'automated_number';

-- Expect: no rows.
SELECT CONSTRAINT_NAME
FROM information_schema.TABLE_CONSTRAINTS
WHERE TABLE_SCHEMA = DATABASE()
  AND TABLE_NAME   = 'cases'
  AND CONSTRAINT_NAME IN ('uq_cases_automated_number',
                          'ck_cases_automated_number_format');

-- Expect: uq_case_number_year still present and untouched -- this
-- rollback must not disturb the original uniqueness key.
SHOW INDEX FROM cases WHERE Key_name = 'uq_case_number_year';

-- Expect: the same row count as before the rollback. Dropping a column
-- removes no rows; this is here to make that visible rather than assumed.
SELECT COUNT(*) AS cases_after FROM cases;
