-- ---------------------------------------------------------------------
-- Migration: Procedural Intelligence
--   Current Status -> Latest Event -> Required Next Procedure ->
--   Responsible User -> Deadline -> Reminder/Notification -> Completion
--
-- NOT EXECUTED BY THE APPLICATION OR BY CLAUDE. This file is a draft for
-- manual review and manual application only, following the same rule as
-- db\migration_user_case_links.sql.
--
-- The application's own MySQL account (aslg_app) holds only
-- SELECT/INSERT/UPDATE/DELETE on its schema -- no CREATE/ALTER/DROP -- so
-- this cannot be run by the app itself even if something tried. Apply it
-- yourself with a privileged account, e.g.:
--
--   mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\migration_procedural_intelligence.sql
--
-- After applying: grant aslg_app plain DML on the new tables (see the
-- GRANT block at the end of this file) and recycle the app pool to pick up
-- the backend/frontend code that uses them (description.md Section 12.8).
--
-- EVERYTHING BELOW IS ADDITIVE. No existing table is altered destructively,
-- no existing column is dropped or renamed, and `cases.stage` keeps its
-- current meaning and values -- every existing query, badge, filter and
-- print template keeps working unchanged. A matching
-- db\rollback_procedural_intelligence.sql drops only what this file adds.
--
-- Every legal-rule row this migration seeds is inserted DISABLED
-- (is_enabled = 0) with its source citation and source_tier attached. No
-- rule takes effect, and no deadline is ever generated as "confirmed",
-- until a named lawyer explicitly enables it (see procedure_rules.sql
-- comment below and backend/app/routers/rules.py). This file creates zero
-- new legal obligations by itself.
-- ---------------------------------------------------------------------

SET NAMES utf8mb4;

-- =====================================================================
-- 1. Reference / taxonomy tables
-- =====================================================================

-- Every taxonomy/rule row in this migration carries a source_tier so the
-- UI can always show whether a fact is official-and-verified, merely
-- official-inferred, entered by firm staff, AI-suggested, or unverified.
-- Repeated as an identical ENUM on every table below rather than a shared
-- lookup table, matching this schema's existing style (see e.g. `status`
-- repeated per-table rather than centralised).

CREATE TABLE case_types (
  id            SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  parent_id     SMALLINT UNSIGNED NULL,               -- self-reference: hierarchical catalogue
  code          VARCHAR(40)  NOT NULL UNIQUE,
  name_ar       VARCHAR(120) NOT NULL,
  name_en       VARCHAR(120) NOT NULL,
  source_tier   ENUM('official_verified','official_inferred','firm_entered','ai_suggested','unverified')
                NOT NULL DEFAULT 'unverified',
  is_enabled    TINYINT(1)   NOT NULL DEFAULT 1,
  sort_order    SMALLINT     NOT NULL DEFAULT 0,
  CONSTRAINT fk_case_types_parent FOREIGN KEY (parent_id) REFERENCES case_types(id) ON DELETE SET NULL,
  INDEX idx_case_types_parent (parent_id)
) ENGINE=InnoDB;

CREATE TABLE court_circuits (
  id            SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  court_id      SMALLINT UNSIGNED NOT NULL,
  name_ar       VARCHAR(120) NOT NULL,
  name_en       VARCHAR(120) NOT NULL,
  source_tier   ENUM('official_verified','official_inferred','firm_entered','ai_suggested','unverified')
                NOT NULL DEFAULT 'unverified',
  is_enabled    TINYINT(1)   NOT NULL DEFAULT 1,
  CONSTRAINT fk_circuits_court FOREIGN KEY (court_id) REFERENCES courts(id) ON DELETE CASCADE,
  INDEX idx_circuits_court (court_id)
) ENGINE=InnoDB;

CREATE TABLE procedure_types (
  id            SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code          VARCHAR(48)  NOT NULL UNIQUE,          -- case_filed, hearing_held, judgment_issued, appeal_filed, ...
  name_ar       VARCHAR(160) NOT NULL,
  name_en       VARCHAR(160) NOT NULL,
  is_terminal   TINYINT(1)   NOT NULL DEFAULT 0,        -- e.g. execution_closed: no further rule ever fires from this
  sort_order    SMALLINT     NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE case_statuses (
  id            SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code          VARCHAR(48)  NOT NULL UNIQUE,
  name_ar       VARCHAR(160) NOT NULL,
  name_en       VARCHAR(160) NOT NULL,
  -- Every fine-grained status rolls up to exactly one of the existing
  -- coarse `cases.stage` values, so cases.stage can keep being derived
  -- from it and every existing consumer of `stage` needs no change.
  maps_to_stage ENUM('new','prep','pleading','judgment','execution','closed') NOT NULL,
  sort_order    SMALLINT     NOT NULL DEFAULT 0
) ENGINE=InnoDB;

CREATE TABLE doc_classes (
  id       SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code     VARCHAR(40)  NOT NULL UNIQUE,               -- pleading, judgment, power_of_attorney, expert_report, ...
  name_ar  VARCHAR(120) NOT NULL,
  name_en  VARCHAR(120) NOT NULL
) ENGINE=InnoDB;

-- =====================================================================
-- 2. Official-source layer
-- =====================================================================

CREATE TABLE official_sources (
  id                SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code              VARCHAR(40)  NOT NULL UNIQUE,       -- moj_eservices, sahel, sahel_business, moj_site
  name_ar           VARCHAR(160) NOT NULL,
  name_en           VARCHAR(160) NOT NULL,
  base_url          VARCHAR(255) NOT NULL,
  -- Recorded here, in the schema itself, as the reason automation is
  -- refused: every official channel researched in Sept 2026 is
  -- 'manual_authenticated' (login + CAPTCHA); 'api_authorised' is the seam
  -- for a future authorised integration, and is not seeded enabled today.
  access_mode       ENUM('manual_authenticated','api_authorised','none') NOT NULL DEFAULT 'manual_authenticated',
  requires_captcha  TINYINT(1)   NOT NULL DEFAULT 0,
  terms_url         VARCHAR(255) NULL,
  is_enabled        TINYINT(1)   NOT NULL DEFAULT 1
) ENGINE=InnoDB;

CREATE TABLE official_source_checks (
  id                     BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id                BIGINT UNSIGNED NOT NULL,
  source_id              SMALLINT UNSIGNED NOT NULL,
  checked_by             INT UNSIGNED NOT NULL,
  checked_at             DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  outcome                ENUM('no_change','change_recorded','not_found','blocked') NOT NULL,
  evidence_document_id   BIGINT UNSIGNED NULL,          -- optional PDF/screenshot proving what was seen
  resulting_procedure_id BIGINT UNSIGNED NULL,           -- set when this check created a case_procedures row
  raw_note               TEXT NULL,
  CONSTRAINT fk_osc_case     FOREIGN KEY (case_id)     REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_osc_source   FOREIGN KEY (source_id)   REFERENCES official_sources(id),
  CONSTRAINT fk_osc_checker  FOREIGN KEY (checked_by)  REFERENCES users(id),
  CONSTRAINT fk_osc_document FOREIGN KEY (evidence_document_id) REFERENCES documents(id) ON DELETE SET NULL,
  INDEX idx_osc_case_time (case_id, checked_at)
) ENGINE=InnoDB;

-- =====================================================================
-- 3. Procedural spine
-- =====================================================================

-- Append-only event log. This IS "Latest Event" -- the current procedural
-- position of a case is always `SELECT ... ORDER BY occurred_at DESC,
-- id DESC LIMIT 1` filtered to supersedes_id chains not superseded.
CREATE TABLE case_procedures (
  id                    BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id               BIGINT UNSIGNED NOT NULL,
  procedure_type_id     SMALLINT UNSIGNED NOT NULL,
  occurred_at           DATETIME NOT NULL,
  recorded_by           INT UNSIGNED NOT NULL,
  -- Who/what actually produced this row -- distinct from source_tier
  -- (how much legal weight it carries), because a firm_entered row can
  -- carry official_verified weight once a lawyer confirms it by hand.
  source                ENUM('firm_entered','official_manual','official_api','migrated')
                        NOT NULL DEFAULT 'firm_entered',
  source_tier           ENUM('official_verified','official_inferred','firm_entered','ai_suggested','unverified')
                        NOT NULL DEFAULT 'firm_entered',
  observed_at           DATETIME NULL,                  -- when a human actually looked at the official record
  observed_by           INT UNSIGNED NULL,
  official_ref          VARCHAR(120) NULL,               -- e.g. the official portal's own reference/ticket number
  evidence_document_id  BIGINT UNSIGNED NULL,
  notes_ar              TEXT NULL,
  notes_en              TEXT NULL,
  supersedes_id         BIGINT UNSIGNED NULL,            -- corrections: never UPDATE/DELETE a past event, supersede it
  created_at            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cp_case       FOREIGN KEY (case_id)      REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_cp_type       FOREIGN KEY (procedure_type_id) REFERENCES procedure_types(id),
  CONSTRAINT fk_cp_recorder   FOREIGN KEY (recorded_by)  REFERENCES users(id),
  CONSTRAINT fk_cp_observer   FOREIGN KEY (observed_by)  REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_cp_document   FOREIGN KEY (evidence_document_id) REFERENCES documents(id) ON DELETE SET NULL,
  CONSTRAINT fk_cp_supersedes FOREIGN KEY (supersedes_id) REFERENCES case_procedures(id) ON DELETE SET NULL,
  INDEX idx_cp_case_time (case_id, occurred_at),
  INDEX idx_cp_case_type (case_id, procedure_type_id)
) ENGINE=InnoDB;

-- The brain, as data -- never as code. Every row is a candidate rule for
-- "what must happen next, and by when." Seeded 100% DISABLED; see the
-- seed file below for why the two Cassation-deadline candidates in
-- particular must stay disabled until a lawyer resolves the 30-vs-60-day
-- conflict found during Sept 2026 research (Phase 1 blueprint, section 2.3).
CREATE TABLE procedure_rules (
  id                         INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code                       VARCHAR(64) NOT NULL,
  version                    SMALLINT UNSIGNED NOT NULL DEFAULT 1,
  case_type_id               SMALLINT UNSIGNED NULL,     -- NULL = applies to any case type
  court_level_code           ENUM('cassation','appeal','first_instance','misdemeanor','family','execution') NULL,
  trigger_procedure_type_id  SMALLINT UNSIGNED NOT NULL,  -- "when THIS just happened..."
  expected_procedure_type_id SMALLINT UNSIGNED NOT NULL,  -- "...THIS is what's due next"
  deadline_days              SMALLINT UNSIGNED NOT NULL,
  day_basis                  ENUM('calendar','kuwait_business') NOT NULL DEFAULT 'calendar',
  counts_from                ENUM('occurrence','notification','judgment_date') NOT NULL DEFAULT 'occurrence',
  responsible_role_code      VARCHAR(32) NULL,           -- fallback if the case has no assigned_lawyer_id
  legal_basis_ar             VARCHAR(255) NULL,
  legal_basis_en             VARCHAR(255) NULL,
  legal_citation             VARCHAR(160) NULL,           -- e.g. "Decree-Law 38/1980, Art. 153"
  source_url                 VARCHAR(255) NULL,
  source_tier                ENUM('official_verified','official_inferred','firm_entered','ai_suggested','unverified')
                             NOT NULL DEFAULT 'unverified',
  -- A rule computes NOTHING until this is 1, and it may only become 1
  -- together with verified_by_user_id + verified_at (enforced in
  -- backend/app/routers/rules.py, not just here) -- enabling a rule
  -- asserts a legal fact and is audit-logged.
  is_enabled                 TINYINT(1)  NOT NULL DEFAULT 0,
  verified_by_user_id        INT UNSIGNED NULL,
  verified_at                DATETIME NULL,
  effective_from             DATE NULL,
  effective_to               DATE NULL,
  notes                      TEXT NULL,
  created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_pr_case_type FOREIGN KEY (case_type_id) REFERENCES case_types(id) ON DELETE SET NULL,
  CONSTRAINT fk_pr_trigger   FOREIGN KEY (trigger_procedure_type_id)  REFERENCES procedure_types(id),
  CONSTRAINT fk_pr_expected  FOREIGN KEY (expected_procedure_type_id) REFERENCES procedure_types(id),
  CONSTRAINT fk_pr_verifier  FOREIGN KEY (verified_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE KEY uq_pr_code_version (code, version),
  INDEX idx_pr_trigger_enabled (trigger_procedure_type_id, is_enabled)
) ENGINE=InnoDB;

-- Materialised deadline instances, one per (procedure event, matching
-- enabled rule). This IS "Deadline" in the requested chain.
CREATE TABLE case_deadlines (
  id                         BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id                    BIGINT UNSIGNED NOT NULL,
  triggered_by_procedure_id  BIGINT UNSIGNED NOT NULL,
  rule_id                    INT UNSIGNED NULL,           -- NULL = manually set by a user, not rule-derived
  rule_version               SMALLINT UNSIGNED NULL,
  deadline_type_code         VARCHAR(64) NOT NULL,
  due_at                     DATETIME NOT NULL,
  responsible_user_id        INT UNSIGNED NULL,
  -- 'confirmed' only when produced by an is_enabled=1, lawyer-verified
  -- rule; everything else is 'provisional' -- badged in the UI, excluded
  -- from hard escalation, and cannot close a procedural step by itself.
  confidence                 ENUM('confirmed','provisional') NOT NULL DEFAULT 'provisional',
  confirmed_by               INT UNSIGNED NULL,
  confirmed_at               DATETIME NULL,
  status                     ENUM('open','met','missed','waived','superseded') NOT NULL DEFAULT 'open',
  completed_by_procedure_id  BIGINT UNSIGNED NULL,
  reminder_id                BIGINT UNSIGNED NULL,        -- bridges into the existing case_reminders engine
  created_at                 DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_cd_case          FOREIGN KEY (case_id)          REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_cd_trigger       FOREIGN KEY (triggered_by_procedure_id) REFERENCES case_procedures(id) ON DELETE CASCADE,
  CONSTRAINT fk_cd_rule          FOREIGN KEY (rule_id)          REFERENCES procedure_rules(id) ON DELETE SET NULL,
  CONSTRAINT fk_cd_responsible   FOREIGN KEY (responsible_user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_cd_confirmer     FOREIGN KEY (confirmed_by)     REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_cd_completed_by  FOREIGN KEY (completed_by_procedure_id) REFERENCES case_procedures(id) ON DELETE SET NULL,
  CONSTRAINT fk_cd_reminder      FOREIGN KEY (reminder_id)      REFERENCES case_reminders(id) ON DELETE SET NULL,
  -- Idempotency: re-running the engine over the same triggering event
  -- against the same rule version never creates a duplicate deadline.
  -- Multiple NULL rule_ids are not collisions (manual deadlines), which is
  -- correct -- idempotency only needs to hold for rule-derived rows.
  UNIQUE KEY uq_cd_trigger_rule_version (triggered_by_procedure_id, rule_id, rule_version),
  INDEX idx_cd_case_status_due (case_id, status, due_at),
  INDEX idx_cd_responsible (responsible_user_id, status)
) ENGINE=InnoDB;

-- =====================================================================
-- 4. Extend existing tables (additive only)
-- =====================================================================

ALTER TABLE cases
  ADD COLUMN case_type_id          SMALLINT UNSIGNED NULL AFTER category_en,
  ADD COLUMN procedural_status_id  SMALLINT UNSIGNED NULL AFTER stage,
  -- Powers "cases not synced in N days" staleness reminders (design 4.5.4);
  -- NULL means "never checked", which is itself meaningful and not backfilled.
  ADD COLUMN last_official_check_at DATETIME NULL AFTER next_hearing_at,
  ADD CONSTRAINT fk_cases_case_type FOREIGN KEY (case_type_id) REFERENCES case_types(id) ON DELETE SET NULL,
  ADD CONSTRAINT fk_cases_proc_status FOREIGN KEY (procedural_status_id) REFERENCES case_statuses(id) ON DELETE SET NULL,
  ADD INDEX idx_cases_case_type (case_type_id);

ALTER TABLE documents
  ADD COLUMN doc_class_id SMALLINT UNSIGNED NULL AFTER file_type,
  ADD CONSTRAINT fk_documents_class FOREIGN KEY (doc_class_id) REFERENCES doc_classes(id) ON DELETE SET NULL;

-- MySQL ENUM widening: existing rows/values are untouched, this only adds
-- new accepted values at the end of each list.
ALTER TABLE case_reminders
  MODIFY COLUMN type ENUM('follow_up','status_update_request','procedural_deadline') NOT NULL DEFAULT 'follow_up';

ALTER TABLE notifications
  MODIFY COLUMN type ENUM('hearing','status','document','system','reminder','deadline') NOT NULL;

-- =====================================================================
-- 5. New modules + permissions (data, not DDL, but bootstrap-required)
-- =====================================================================

INSERT INTO modules (code) VALUES ('procedures'), ('deadlines'), ('official_sync'), ('rules_admin');

-- Mirrors the access matrix from the Phase 1 blueprint section 4.7.
-- Uses each role's existing code -- no role is added or removed here.
INSERT INTO role_permissions (role_id, module_id, access_level)
SELECT r.id, m.id, v.access_level FROM (
  SELECT 'Admin'      AS role_code, 'procedures'    AS module_code, 'full' AS access_level UNION ALL
  SELECT 'Admin',      'deadlines',      'full' UNION ALL
  SELECT 'Admin',      'official_sync',  'full' UNION ALL
  SELECT 'Admin',      'rules_admin',    'full' UNION ALL
  SELECT 'Lawyer',     'procedures',     'full' UNION ALL
  SELECT 'Lawyer',     'deadlines',      'full' UNION ALL
  SELECT 'Lawyer',     'official_sync',  'full' UNION ALL
  SELECT 'Lawyer',     'rules_admin',    'view' UNION ALL
  SELECT 'consultant', 'procedures',     'edit' UNION ALL
  SELECT 'consultant', 'deadlines',      'edit' UNION ALL
  SELECT 'consultant', 'official_sync',  'edit' UNION ALL
  SELECT 'consultant', 'rules_admin',    'none' UNION ALL
  SELECT 'delegate',   'procedures',     'view' UNION ALL
  SELECT 'delegate',   'deadlines',      'view' UNION ALL
  SELECT 'delegate',   'official_sync',  'edit' UNION ALL
  SELECT 'delegate',   'rules_admin',    'none' UNION ALL
  SELECT 'User',       'procedures',     'own' UNION ALL
  SELECT 'User',       'deadlines',      'own' UNION ALL
  SELECT 'User',       'official_sync',  'none' UNION ALL
  SELECT 'User',       'rules_admin',    'none'
) AS v
JOIN roles r ON r.code = v.role_code
JOIN modules m ON m.code = v.module_code;

-- =====================================================================
-- 6. Grant the app's runtime account plain DML on the new tables
--    (uncomment and adjust to match your actual aslg_app grant scope)
-- =====================================================================
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.case_types              TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.court_circuits          TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.procedure_types         TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.case_statuses           TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.doc_classes             TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.official_sources        TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.official_source_checks  TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.case_procedures         TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.procedure_rules         TO 'aslg_app'@'127.0.0.1';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.case_deadlines          TO 'aslg_app'@'127.0.0.1';
-- FLUSH PRIVILEGES;

-- Run db\seed_procedure_rules.sql AFTER this file to load the taxonomy and
-- (all-disabled) rule catalogue -- kept separate so the structural
-- migration and the legal-content seed can be reviewed independently.
