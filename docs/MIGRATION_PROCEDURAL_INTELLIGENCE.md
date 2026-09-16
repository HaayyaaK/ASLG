# Runbook — Procedural Intelligence migration

**Status: NOT YET APPLIED.** This document is the procedure for applying it.
Nothing in it runs automatically, and no AI assistant working on this project
applies it — it is executed by a human with a privileged MySQL account, in a
planned window.

Estimated window: **20–30 minutes**, of which roughly 2 minutes is the actual
schema change. The rest is backup, verification, and the code step.

---

## 1. Purpose — what this adds, and what it does not

The Procedural Intelligence feature answers, for any case: *Current Status →
Latest Event → Required Next Procedure → Responsible User → Deadline →
Reminder/Notification → Completion*. See `description.md` §3.8 for the
feature description and `GUIDELINES.md` §2.9 for the user-facing version.

### 1.1 Schema this adds

**Ten new tables** (`db/migration_procedural_intelligence.sql`):

| Table | Purpose |
|---|---|
| `case_types` | Hierarchical case-type taxonomy |
| `court_circuits` | Circuits/chambers within a court (seeded empty by design) |
| `procedure_types` | Canonical procedural event vocabulary |
| `case_statuses` | Fine-grained status, each rolling up to an existing `cases.stage` value |
| `doc_classes` | Legal document classification |
| `official_sources` | MOJ e-Services / Sahel / Sahel Business / MOJ site |
| `official_source_checks` | One row per Assisted Manual Sync observation |
| `case_procedures` | **Append-only procedural event log** — the "Latest Event" spine |
| `procedure_rules` | The rule catalogue — "the brain, as data" |
| `case_deadlines` | Materialised deadline instances |

**Four columns on two pre-existing tables** — these are the ones that caused
the September 2026 outage when added to the ORM ahead of the database, and
they are the reason step 4 of this runbook exists:

| Table | Column |
|---|---|
| `cases` | `case_type_id`, `procedural_status_id`, `last_official_check_at` |
| `documents` | `doc_class_id` |

**Two widened ENUMs** (additive — no existing value changes):
`case_reminders.type += 'procedural_deadline'`, `notifications.type += 'deadline'`.

**Four new permission modules**: `procedures`, `deadlines`, `official_sync`,
`rules_admin`, plus their `role_permissions` rows.

### 1.2 What this explicitly does NOT do

- **It does not create any legal obligation.** Every row in
  `db/seed_procedure_rules.sql` is inserted with `is_enabled = 0`. No deadline
  is computed from a disabled rule. Applying this migration is therefore safe
  *before* any legal review has happened.
- **It does not change `cases.stage`.** Every existing badge, filter, print
  template and query that reads `stage` is untouched.
- **It does not drop or rename anything.** The migration is purely additive.
- **It does not enable any automated contact with a government portal.** There
  is none in this codebase.

> **Enabling a rule is a separate, later, in-app action** (Admin or
> owner-Lawyer, audit-logged, requires `confirm: true`, and is refused
> outright while the rule's `source_tier` is still `unverified`). Notably the
> Cassation appeal deadline ships as **two competing disabled candidates**
> (30 vs 60 days) because two professional sources disagree — a Kuwaiti
> lawyer must check the statute before either is enabled. That verification
> is **not** a prerequisite for this migration.

---

## 2. Pre-flight

Run these **before** touching anything. Stop if any check fails.

### 2.1 Take a backup — non-negotiable

```bat
cd C:\inetpub\sites\Platforms\ASLG
mysqldump --no-tablespaces -h 127.0.0.1 -P 3306 -u root -p ^
  --single-transaction --routines --triggers ^
  aslg_legal > "C:\backups\aslg_legal_premigration_%DATE:~-4%%DATE:~4,2%%DATE:~7,2%_%TIME:~0,2%%TIME:~3,2%.sql"
```

`--no-tablespaces` avoids needing the `PROCESS` privilege; `--single-transaction`
keeps the dump consistent without locking the app out. **Verify the file is
non-empty and ends with `-- Dump completed`** before continuing.

### 2.2 Check MySQL version

```sql
SELECT VERSION();
```

Must be **8.0.13 or newer**. The migration uses functional/expression indexes
and `ALTER TABLE ... MODIFY COLUMN` on ENUMs. Production was verified on
**MySQL 8.4**.

### 2.3 Confirm you are NOT using the app's own account

```sql
SELECT CURRENT_USER();
```

Must **not** be `aslg_app`. That account deliberately holds only
SELECT/INSERT/UPDATE/DELETE — no CREATE/ALTER/DROP — so the application can
never alter its own schema. Use `root` or another privileged account.

### 2.4 Record the current shape, so you can prove the change afterwards

```sql
SELECT COUNT(*) AS cases_before FROM cases;
SELECT COUNT(*) AS documents_before FROM documents;
SHOW COLUMNS FROM cases LIKE 'case_type_id';        -- expect: empty set
SHOW COLUMNS FROM documents LIKE 'doc_class_id';    -- expect: empty set
```

### 2.5 Confirm the test suite is green on the current code

```bat
cd C:\inetpub\sites\Platforms\ASLG\backend
pytest -q
```

Expect **all tests passing** before you start. If they are not, fix that first —
you do not want to be diagnosing a pre-existing failure mid-migration.

---

## 3. Apply the schema

```bat
cd C:\inetpub\sites\Platforms\ASLG
mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\migration_procedural_intelligence.sql
mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\seed_procedure_rules.sql
```

**Expected output: complete silence.** `mysql` prints nothing on success for a
script of DDL + INSERTs. Any output at all is an error — stop and go to §6.

Order matters: the seed file inserts into tables the migration creates.

### 3.1 Grant the app account DML on the new tables

The migration file ends with a commented-out `GRANT` block. If your `aslg_app`
grant is **schema-wide** (`ON aslg_legal.*`), nothing to do — it already covers
the new tables. If it is **per-table**, uncomment and run that block, adjusting
the account/host to match your actual grant, then `FLUSH PRIVILEGES;`.

Check which you have:

```sql
SHOW GRANTS FOR 'aslg_app'@'127.0.0.1';
```

### 3.2 Verify the schema change landed

```sql
SHOW COLUMNS FROM cases LIKE 'case_type_id';            -- expect: 1 row
SHOW COLUMNS FROM cases LIKE 'procedural_status_id';    -- expect: 1 row
SHOW COLUMNS FROM cases LIKE 'last_official_check_at';  -- expect: 1 row
SHOW COLUMNS FROM documents LIKE 'doc_class_id';        -- expect: 1 row

SHOW CREATE TABLE cases\G
SHOW CREATE TABLE documents\G

-- Row counts must be IDENTICAL to §2.4. The migration adds columns; it must
-- not have touched a single existing row.
SELECT COUNT(*) AS cases_after FROM cases;
SELECT COUNT(*) AS documents_after FROM documents;

-- All ten new tables present:
SELECT table_name FROM information_schema.tables
 WHERE table_schema = 'aslg_legal'
   AND table_name IN ('case_types','court_circuits','procedure_types','case_statuses',
                      'doc_classes','official_sources','official_source_checks',
                      'case_procedures','procedure_rules','case_deadlines')
 ORDER BY table_name;   -- expect: 10 rows

-- CRITICAL: every seeded rule must be disabled.
SELECT COUNT(*) AS total, SUM(is_enabled) AS enabled FROM procedure_rules;
-- expect: total = 5, enabled = 0   <-- if `enabled` is anything but 0, STOP.

-- The four new permission modules and their grants:
SELECT code FROM modules WHERE code IN ('procedures','deadlines','official_sync','rules_admin');
```

---

## 4. Restore the ORM columns

The four columns are currently **commented out** in `backend/app/models.py`.
This was not a design choice — it is the fix for the outage described in §1.1.
SQLAlchemy always selects *and* inserts every mapped column, regardless of
`deferred=True` or omitting `default=`, so a column declared on the class but
absent from the table breaks reads, counts **and** writes. With the table now
having the columns, they can come back.

**Do this only after §3.2 has fully passed.**

### 4.1 Edit `backend/app/models.py`

Each site has the exact restore snippet in its own comment. In order:

| # | Class | Restore |
|---|---|---|
| 1 | `Case` | `case_type_id` + the `case_type` relationship |
| 2 | `Case` | `procedural_status_id` + the `procedural_status` relationship |
| 3 | `Case` | `last_official_check_at` |
| 4 | `Document` | `doc_class_id` + the `doc_class` relationship |

### 4.2 Optional tidy-up (safe to skip)

- `backend/app/procedures.py::_matching_rules` reads `getattr(case,
  "case_type_id", None)`. That keeps working unchanged once the column is
  back; it can be simplified to `case.case_type_id` but does not need to be.
- `backend/app/routers/dashboard.py` uses `.with_entities(Case.id).count()` /
  `.with_entities(Document.id).count()`. **Leave these.** They remain correct
  and are strictly more efficient than counting full entity rows.

### 4.3 Update the test suite

`backend/tests/test_premigration_compatibility.py` and the
`premigration_db` / `premigration_base_data` fixtures in
`backend/tests/conftest.py` exist to prove the app works against the
*pre-migration* schema. Once the migration is applied and the columns are
restored, that scenario no longer describes production and those tests will
legitimately fail.

**Delete both the test file and the two fixtures at this point**, in the same
commit as the column restore. They have served their purpose; keeping them
means keeping a test that asserts the opposite of reality.

### 4.4 Mirror the DDL into `db/schema.sql`

This project has no migration tool: `db/schema.sql` is the source of truth for
the table layout and is updated by hand after each applied change (see
`description.md` §10). Copy the new `CREATE TABLE` statements and the
`ALTER TABLE ... ADD COLUMN` results into it so a fresh install reproduces
what production now has.

### 4.5 Recycle

```bat
%windir%\system32\inetsrv\appcmd.exe recycle apppool "ASLG"
```

A file edit to `.py` is **not** picked up without this — `httpPlatformHandler`
does not watch Python files.

---

## 5. Post-migration verification

### 5.1 Test suite

```bat
cd C:\inetpub\sites\Platforms\ASLG\backend
pytest -q
```

All tests must pass (minus the pre-migration file deleted in §4.3).

### 5.2 The five endpoints that broke last time

As **Admin** and again as a **Client**:

| Endpoint | Admin | Client |
|---|---|---|
| `/api/cases` | 200 | 200 (own cases only) |
| `/api/dashboard/stats` | 200 | 200 (own counts only) |
| `/api/dashboard/upcoming-hearings` | 200 | 200 |
| `/api/documents` | 200 | 200 (own case docs only) |
| `/api/dashboard/task-stats` | 200 | **403** (correct — Clients have `reminders: none`) |

### 5.3 Writes, not just reads

The outage broke `POST` as badly as `GET`. Explicitly confirm:

- Create a new case through the UI.
- Upload a document to a case.

### 5.4 Client isolation

Log in as a Client and confirm they see only their own case, no Deadlines
page content beyond confirmed items, no Procedure Rules entry, and no
Official Sync panel.

### 5.5 New feature surfaces appear

After the migration the four new permission modules exist, so for an
Admin/Lawyer the sidebar gains **Deadlines** and **Procedure Rules**, and the
Dashboard gains its third stats row. Before the migration these are correctly
invisible (the permission lookup returns `none`).

### 5.6 Log scan

```bat
cd C:\inetpub\sites\Platforms\ASLG\backend\logs
findstr /C:"Unknown column" /C:"500 Internal Server Error" /C:"Traceback" <newest log file>
```

Expect no matches.

### 5.7 Optional — backfill historical events

```bat
cd C:\inetpub\sites\Platforms\ASLG\backend
python backfill_procedures.py            REM dry run, prints what it would do
python backfill_procedures.py --apply    REM writes
```

Projects existing `case_timeline` / `court_sessions` / `experts` /
`execution_files` rows into `case_procedures`, tagged
`source='migrated', source_tier='unverified'`. Generates **no** deadlines —
backfilling a deadline retroactively would fabricate a legal position the firm
never actually tracked. Idempotent; safe to re-run.

---

## 6. Rollback

**Order is critical: revert the CODE first, then the SCHEMA.** Dropping the
columns while the application still expects them reproduces the original
outage exactly — reads, counts and writes all fail.

1. **Re-comment the four ORM columns** in `backend/app/models.py` (reverse of
   §4.1), restore the deleted pre-migration tests if you want the guard back.
2. **Recycle the app pool** and confirm the five endpoints return 200/403.
   *The app is now healthy again on the old schema — the urgent part is over.*
3. **Only then** drop the schema:
   ```bat
   mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\rollback_procedural_intelligence.sql
   ```
   It removes only what the migration added, and touches no pre-existing data.
4. Revert `db/schema.sql` (§4.4).
5. Re-run `pytest -q` and re-verify the five endpoints.

### 6.1 If you only need to neutralise the feature, not remove it

You almost certainly do not need a rollback. Disabling every rule stops all
deadline computation instantly, with no schema change and no data loss:

```sql
UPDATE procedure_rules SET is_enabled = 0;
```

The event log, deadlines already recorded, and sync history all remain intact
and visible. This is the reversible "off switch"; §6 is the nuclear option.

---

## 7. Risk and blast radius

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Migration fails partway | Low | Medium | It is DDL over 10 new tables + 2 ALTERs; a failure leaves some tables created. Re-running is not idempotent — restore from the §2.1 backup, or drop the created tables via the rollback script and retry. |
| Existing data altered | **Very low** | High | Migration contains no `UPDATE`/`DELETE` against pre-existing tables. §3.2's row-count comparison proves it. |
| Code/schema out of step | Medium | **High** | This is exactly the outage already suffered. §4 must follow §3, and §6 must reverse that order. Never do §4 first. |
| `aslg_app` lacks DML on new tables | Low | Medium | §3.1. Symptom would be permission errors on the new endpoints only; core app unaffected. |
| A rule gets enabled prematurely | Low | **High (legal)** | §3.2 asserts `enabled = 0`. Enabling additionally requires Admin/owner-Lawyer + explicit confirm + a non-`unverified` source tier. |
| App pool not recycled | Medium | Medium | §4.5. Symptom: code changes appear to have no effect. |

**Blast radius if it goes wrong:** the `cases` and `documents` tables are the
two most load-bearing in the application, so a failure between §3 and §4.5
degrades Cases, Dashboard and Documents for **all roles** — which is precisely
what happened in September 2026. Everything else (auth, users, activity log)
is unaffected. Recovery is the §6 order, and the fast path is step 1–2 only
(code revert + recycle), which restores service without touching the database.

---

## 8. Sign-off checklist

- [ ] §2.1 backup taken, file verified non-empty
- [ ] §2.2 MySQL ≥ 8.0.13
- [ ] §2.3 not running as `aslg_app`
- [ ] §2.4 pre-change row counts recorded
- [ ] §2.5 `pytest -q` green before starting
- [ ] §3 migration + seed applied, no output
- [ ] §3.2 all verification queries pass, **`procedure_rules.enabled = 0`**
- [ ] §4 ORM columns restored, pre-migration tests removed, `schema.sql` mirrored
- [ ] §4.5 app pool recycled
- [ ] §5 endpoints, writes, client isolation, logs all verified
- [ ] Rule enabling deferred to the lawyer review (separate task)
