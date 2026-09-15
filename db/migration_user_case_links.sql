-- ---------------------------------------------------------------------
-- Migration: add user_case_links (explicit user <-> case linking)
--
-- NOT EXECUTED BY THE APPLICATION OR BY CLAUDE. This file is a draft for
-- manual review and manual application only.
--
-- The application's own MySQL account (aslg_app) holds only
-- SELECT/INSERT/UPDATE/DELETE on its schema -- no CREATE/ALTER/DROP -- so
-- this cannot be run by the app itself even if something tried. Apply it
-- yourself with a privileged account, e.g.:
--
--   mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\migration_user_case_links.sql
--
-- After applying, no code changes or app-pool recycle are needed purely for
-- the schema change itself (the backend code already expects this table to
-- exist once you apply this file) -- but the app pool DOES need a recycle
-- to pick up the new backend/frontend code that uses it, the same as any
-- other backend deploy on this box (see description.md Section 12.8).
--
-- Requires MySQL 8.0.13+ for the functional unique index below. If the
-- target server is older, drop the UNIQUE KEY line and rely on the
-- application-level revoke-then-insert logic alone (already implemented in
-- backend/app/routers/cases.py::link_user_to_case).
-- ---------------------------------------------------------------------

CREATE TABLE user_case_links (
  id                BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  user_id           INT UNSIGNED NOT NULL,
  case_id           BIGINT UNSIGNED NOT NULL,
  can_upload        TINYINT(1) NOT NULL DEFAULT 0,
  can_upload_until  DATETIME NULL,
  linked_by         INT UNSIGNED NULL,
  linked_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status            ENUM('active','revoked') NOT NULL DEFAULT 'active',
  revoked_by        INT UNSIGNED NULL,
  revoked_at        DATETIME NULL,
  CONSTRAINT fk_ucl_user    FOREIGN KEY (user_id)    REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_ucl_case    FOREIGN KEY (case_id)    REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_ucl_linker  FOREIGN KEY (linked_by)  REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_ucl_revoker FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL,
  -- At most one ACTIVE row per (user_id, case_id): the expression is 1 for
  -- an active row and NULL for a revoked one, and InnoDB never treats two
  -- NULLs in a unique index as a collision -- so revoked history rows are
  -- unlimited, but only one row per pair may ever be active at a time.
  UNIQUE KEY uq_ucl_active_pair (user_id, case_id, ((CASE WHEN status = 'active' THEN 1 ELSE NULL END))),
  INDEX idx_ucl_user (user_id, status),
  INDEX idx_ucl_case (case_id, status)
) ENGINE=InnoDB;

-- Grant the app's own runtime account the row-level privileges it needs on
-- the new table (it already lacks CREATE/ALTER by design -- this grants
-- ordinary DML only, matching every other table it uses):
-- GRANT SELECT, INSERT, UPDATE, DELETE ON aslg_legal.user_case_links TO 'aslg_app'@'127.0.0.1';
-- FLUSH PRIVILEGES;
-- (Uncomment and adjust the account/host above to match your actual aslg_app grant if it's scoped per-table rather than schema-wide.)
