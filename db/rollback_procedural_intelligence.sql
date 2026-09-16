-- ---------------------------------------------------------------------
-- Rollback for db\migration_procedural_intelligence.sql
--
-- NOT EXECUTED BY THE APPLICATION OR BY CLAUDE. Manual review and manual
-- application only, by a privileged account:
--
--   mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\rollback_procedural_intelligence.sql
--
-- Drops ONLY what the migration added. Every pre-existing table (cases,
-- documents, case_reminders, notifications, ...) is left with its data
-- intact -- only the additive columns/enum values this feature introduced
-- are removed, and only from those four tables. `cases.stage` and every
-- pre-existing column are untouched.
--
-- Run this and the app reverts to exactly its pre-migration behaviour:
-- Procedural Intelligence pages and endpoints will 404/no-op once the
-- corresponding backend code is also rolled back or feature-flagged off.
-- ---------------------------------------------------------------------

SET FOREIGN_KEY_CHECKS = 0;

-- Reverse of section 5 (bootstrap data)
DELETE rp FROM role_permissions rp
  JOIN modules m ON m.id = rp.module_id
  WHERE m.code IN ('procedures', 'deadlines', 'official_sync', 'rules_admin');
DELETE FROM modules WHERE code IN ('procedures', 'deadlines', 'official_sync', 'rules_admin');

-- Reverse of section 4 (additive columns on existing tables)
ALTER TABLE notifications
  MODIFY COLUMN type ENUM('hearing','status','document','system','reminder') NOT NULL;

ALTER TABLE case_reminders
  MODIFY COLUMN type ENUM('follow_up','status_update_request') NOT NULL DEFAULT 'follow_up';

ALTER TABLE documents
  DROP FOREIGN KEY fk_documents_class,
  DROP COLUMN doc_class_id;

ALTER TABLE cases
  DROP FOREIGN KEY fk_cases_case_type,
  DROP FOREIGN KEY fk_cases_proc_status,
  DROP INDEX idx_cases_case_type,
  DROP COLUMN case_type_id,
  DROP COLUMN procedural_status_id,
  DROP COLUMN last_official_check_at;

-- Reverse of sections 1-3 (new tables) -- children before parents
DROP TABLE IF EXISTS case_deadlines;
DROP TABLE IF EXISTS procedure_rules;
DROP TABLE IF EXISTS case_procedures;
DROP TABLE IF EXISTS official_source_checks;
DROP TABLE IF EXISTS official_sources;
DROP TABLE IF EXISTS doc_classes;
DROP TABLE IF EXISTS case_statuses;
DROP TABLE IF EXISTS procedure_types;
DROP TABLE IF EXISTS court_circuits;
DROP TABLE IF EXISTS case_types;

SET FOREIGN_KEY_CHECKS = 1;
