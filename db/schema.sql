-- =====================================================================
-- ASLG — Legal Web Portal
-- MySQL 8.0+ Relational Schema (DDL only)
-- Charset: utf8mb4 (full Arabic + English support)
--
-- Seed data (roles, permissions, users with real bcrypt hashes, courts,
-- cases, hearings, experts, execution files, notifications) is loaded by
-- backend/seed.py, not by this file — that keeps password hashing and
-- the single source of demo data in one place instead of two formats.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS aslg_legal
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE aslg_legal;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ---------------------------------------------------------------------
-- Roles & Permissions
-- ---------------------------------------------------------------------
CREATE TABLE roles (
  id            TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code          VARCHAR(32)  NOT NULL UNIQUE,       -- Admin, Lawyer, consultant, delegate, User
  name_ar       VARCHAR(64)  NOT NULL,
  name_en       VARCHAR(64)  NOT NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE modules (
  id            TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code          VARCHAR(32)  NOT NULL UNIQUE          -- dashboard, search, cases, documents, notifications, users
) ENGINE=InnoDB;

CREATE TABLE role_permissions (
  role_id       TINYINT UNSIGNED NOT NULL,
  module_id     TINYINT UNSIGNED NOT NULL,
  access_level  ENUM('none','view','own','limited','edit','full') NOT NULL DEFAULT 'none',
  PRIMARY KEY (role_id, module_id),
  CONSTRAINT fk_rp_role   FOREIGN KEY (role_id)   REFERENCES roles(id)   ON DELETE CASCADE,
  CONSTRAINT fk_rp_module FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Users & Sessions
-- ---------------------------------------------------------------------
CREATE TABLE users (
  id             INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name_en        VARCHAR(120) NOT NULL,
  name_ar        VARCHAR(120) NOT NULL,
  username       VARCHAR(64)  NOT NULL UNIQUE,
  email          VARCHAR(160) UNIQUE,
  occupation     VARCHAR(80),
  role_id        TINYINT UNSIGNED NOT NULL,
  civil_id       VARCHAR(20)  NULL,                  -- used to scope client (User role) case visibility
  password_hash  VARCHAR(255) NOT NULL,               -- bcrypt/argon2 hash, never plaintext
  is_owner       TINYINT(1)   NOT NULL DEFAULT 0,     -- firm-owner lawyers: can assign tasks/reminders to any staff
  is_active      TINYINT(1)   NOT NULL DEFAULT 1,
  last_login_at  DATETIME     NULL,
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles(id),
  INDEX idx_users_role (role_id)
) ENGINE=InnoDB;

CREATE TABLE user_sessions (
  id             BINARY(16)   PRIMARY KEY,             -- UUID token
  user_id        INT UNSIGNED NOT NULL,
  ip_address     VARCHAR(45),
  user_agent     VARCHAR(255),
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at     DATETIME     NOT NULL,
  revoked_at     DATETIME     NULL,
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_sessions_user (user_id),
  INDEX idx_sessions_expiry (expires_at)
) ENGINE=InnoDB;

CREATE TABLE audit_log (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  user_id        INT UNSIGNED NULL,
  action         VARCHAR(64)  NOT NULL,                -- login, logout, case_update, document_upload, ...
  entity_type    VARCHAR(64),
  entity_id      BIGINT UNSIGNED,
  meta_json      JSON,
  ip_address     VARCHAR(45),
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_audit_entity (entity_type, entity_id),
  INDEX idx_audit_user (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Courts / Cases
-- ---------------------------------------------------------------------
CREATE TABLE courts (
  id             SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  level_code     ENUM('cassation','appeal','first_instance','misdemeanor','family','execution') NOT NULL,
  name_ar        VARCHAR(160) NOT NULL,
  name_en        VARCHAR(160) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE cases (
  id                 BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_number        VARCHAR(32)  NOT NULL,
  case_year          SMALLINT     NOT NULL,
  court_id           SMALLINT UNSIGNED NOT NULL,
  category_ar        VARCHAR(80),
  category_en        VARCHAR(80),
  parties_ar         VARCHAR(255) NOT NULL,
  parties_en         VARCHAR(255),
  civil_id           VARCHAR(20),                       -- opposing/client civil ID for lookup
  status             ENUM('active','closed') NOT NULL DEFAULT 'active',
  stage              ENUM('new','prep','pleading','judgment','execution','closed') NOT NULL DEFAULT 'new',
  assigned_lawyer_id INT UNSIGNED NULL,
  summary_ar         TEXT,
  summary_en         TEXT,
  next_hearing_at    DATETIME NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_cases_court  FOREIGN KEY (court_id) REFERENCES courts(id),
  CONSTRAINT fk_cases_lawyer FOREIGN KEY (assigned_lawyer_id) REFERENCES users(id) ON DELETE SET NULL,
  UNIQUE KEY uq_case_number_year (case_number, case_year),
  INDEX idx_cases_status (status),
  INDEX idx_cases_stage (stage),
  INDEX idx_cases_civil_id (civil_id),
  FULLTEXT INDEX ft_cases_search (parties_ar, parties_en, summary_ar, summary_en)
) ENGINE=InnoDB;

CREATE TABLE case_timeline (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id        BIGINT UNSIGNED NOT NULL,
  step_title_ar  VARCHAR(200) NOT NULL,
  step_title_en  VARCHAR(200),
  step_date      DATETIME NOT NULL,
  is_done        TINYINT(1) NOT NULL DEFAULT 0,
  sort_order     SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  CONSTRAINT fk_timeline_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
  INDEX idx_timeline_case (case_id)
) ENGINE=InnoDB;

CREATE TABLE case_notes (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id        BIGINT UNSIGNED NOT NULL,
  author_id      INT UNSIGNED NOT NULL,
  note_text      TEXT NOT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_notes_case   FOREIGN KEY (case_id)   REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_notes_author FOREIGN KEY (author_id) REFERENCES users(id),
  INDEX idx_notes_case (case_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Sessions & Circuits (Court Hearings)
-- ---------------------------------------------------------------------
CREATE TABLE court_sessions (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id        BIGINT UNSIGNED NOT NULL,
  circuit_ar     VARCHAR(120) NOT NULL,
  circuit_en     VARCHAR(120),
  courtroom      VARCHAR(60),
  session_at     DATETIME NOT NULL,
  status         ENUM('scheduled','done','postponed','cancelled') NOT NULL DEFAULT 'scheduled',
  outcome_notes  TEXT,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_sessions_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
  INDEX idx_sessions_case (case_id),
  INDEX idx_sessions_date (session_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Experts
-- ---------------------------------------------------------------------
CREATE TABLE experts (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id        BIGINT UNSIGNED NOT NULL,
  file_no        VARCHAR(40)  NOT NULL,
  expert_name    VARCHAR(160) NOT NULL,
  specialty_ar   VARCHAR(160),
  specialty_en   VARCHAR(160),
  assigned_at    DATETIME NOT NULL,
  status         ENUM('scheduled','in_progress','completed') NOT NULL DEFAULT 'scheduled',
  report_summary TEXT,
  CONSTRAINT fk_experts_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
  UNIQUE KEY uq_expert_file_no (file_no),
  INDEX idx_experts_case (case_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Execution Files
-- ---------------------------------------------------------------------
CREATE TABLE execution_files (
  id               BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id          BIGINT UNSIGNED NOT NULL,
  file_no          VARCHAR(40)  NOT NULL,
  amount           DECIMAL(14,3) NOT NULL DEFAULT 0,   -- KWD supports 3 decimal fils
  currency         CHAR(3) NOT NULL DEFAULT 'KWD',
  status           ENUM('in_progress','closed','suspended') NOT NULL DEFAULT 'in_progress',
  last_action_ar   VARCHAR(255),
  last_action_en   VARCHAR(255),
  last_action_at   DATETIME,
  CONSTRAINT fk_execution_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
  UNIQUE KEY uq_execution_file_no (file_no),
  INDEX idx_execution_case (case_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Documents
-- ---------------------------------------------------------------------
CREATE TABLE documents (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id        BIGINT UNSIGNED NOT NULL,
  file_name      VARCHAR(255) NOT NULL,
  file_type      VARCHAR(10)  NOT NULL,                -- pdf, docx, jpg, png ...
  file_size      BIGINT UNSIGNED NOT NULL,
  storage_path   VARCHAR(500) NOT NULL,                -- filesystem or object-storage key
  status         ENUM('pending','approved','rejected') NOT NULL DEFAULT 'pending',
  uploaded_by    INT UNSIGNED NOT NULL,
  uploaded_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_docs_case     FOREIGN KEY (case_id)     REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_docs_uploader FOREIGN KEY (uploaded_by) REFERENCES users(id),
  INDEX idx_docs_case (case_id),
  INDEX idx_docs_status (status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Notifications
-- ---------------------------------------------------------------------
CREATE TABLE notifications (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  user_id        INT UNSIGNED NULL,                    -- NULL => broadcast to target_role_id
  target_role_id TINYINT UNSIGNED NULL,
  type           ENUM('hearing','status','document','system','reminder') NOT NULL,
  message_ar     VARCHAR(500) NOT NULL,
  message_en     VARCHAR(500),
  is_read        TINYINT(1) NOT NULL DEFAULT 0,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id)        REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_notif_role FOREIGN KEY (target_role_id) REFERENCES roles(id) ON DELETE CASCADE,
  INDEX idx_notif_user (user_id),
  INDEX idx_notif_role (target_role_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Imported Records (from MOJ e-Services search results)
-- ---------------------------------------------------------------------
CREATE TABLE imported_records (
  id             BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  source_type    ENUM('case','session','expert','execution') NOT NULL,
  source_ref_id  BIGINT UNSIGNED NOT NULL,              -- id in the corresponding table
  imported_by    INT UNSIGNED NOT NULL,
  imported_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_imported_user FOREIGN KEY (imported_by) REFERENCES users(id),
  INDEX idx_imported_source (source_type, source_ref_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Case Watchers (auto-subscribed on import from official search; anyone
-- can also opt in manually) — drives which users get notified when a
-- watched case's stage, sessions, or documents change.
-- ---------------------------------------------------------------------
CREATE TABLE case_watchers (
  case_id        BIGINT UNSIGNED NOT NULL,
  user_id        INT UNSIGNED NOT NULL,
  source         ENUM('import','manual') NOT NULL DEFAULT 'manual',
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (case_id, user_id),
  CONSTRAINT fk_watchers_case FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_watchers_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  INDEX idx_watchers_user (user_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Case Reminders / Follow-ups / Status-Update Requests
-- Admin, Lawyer and Consultant roles may schedule a follow-up reminder
-- or submit a request asking the assigned lawyer to update a case's
-- stage; the assignee resolves it by acting or dismissing.
-- ---------------------------------------------------------------------
CREATE TABLE case_reminders (
  id               BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id          BIGINT UNSIGNED NOT NULL,
  type             ENUM('follow_up','status_update_request') NOT NULL DEFAULT 'follow_up',
  requested_stage  ENUM('new','prep','pleading','judgment','execution','closed') NULL,
  due_at           DATETIME NOT NULL,
  note             VARCHAR(500) NOT NULL,
  created_by       INT UNSIGNED NOT NULL,
  assigned_to      INT UNSIGNED NOT NULL,
  status           ENUM('open','done','dismissed') NOT NULL DEFAULT 'open',
  escalation_level TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- 3-layer nudge: 0=none, 1=due, 2=overdue, 3=critical (owner pulled in)
  resolved_at      DATETIME NULL,
  created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_reminders_case      FOREIGN KEY (case_id)     REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_reminders_creator   FOREIGN KEY (created_by)  REFERENCES users(id),
  CONSTRAINT fk_reminders_assignee  FOREIGN KEY (assigned_to) REFERENCES users(id),
  INDEX idx_reminders_case (case_id),
  INDEX idx_reminders_assignee (assigned_to, status),
  INDEX idx_reminders_due (due_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- Document Upload Grants
-- Clients cannot upload documents by default. An Admin, Lawyer, or
-- Consultant grants a one-time, time-limited upload window for a
-- specific client + case; the grant is consumed on first successful
-- upload (or expires), automatically reverting to blocked.
-- ---------------------------------------------------------------------
CREATE TABLE document_upload_grants (
  id               BIGINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  case_id          BIGINT UNSIGNED NOT NULL,
  client_user_id   INT UNSIGNED NOT NULL,
  granted_by       INT UNSIGNED NOT NULL,
  granted_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at       DATETIME NOT NULL,
  used_at          DATETIME NULL,
  status           ENUM('active','used','revoked','expired') NOT NULL DEFAULT 'active',
  CONSTRAINT fk_grant_case     FOREIGN KEY (case_id)        REFERENCES cases(id) ON DELETE CASCADE,
  CONSTRAINT fk_grant_client   FOREIGN KEY (client_user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT fk_grant_granter  FOREIGN KEY (granted_by)     REFERENCES users(id),
  INDEX idx_grant_lookup (case_id, client_user_id, status)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- User <-> Case Links
-- Explicit Admin/owning-Lawyer-controlled link between a portal user
-- (typically a Client) and a case, independent of the civil_id match on
-- cases.civil_id (kept working unchanged — this is additive). Supports
-- many users per case (co-clients, power of attorney) and many cases per
-- user. can_upload is a standing upload permission, separate from the
-- one-time document_upload_grants window above; can_upload_until is
-- reserved for a future expiring-standing-access feature (NULL = never
-- expires today, no UI sets it yet).
--
-- uq_ucl_active_pair is a MySQL 8.0.13+ functional unique index: the
-- expression evaluates to 1 for an active row and NULL for a revoked one,
-- and InnoDB treats every NULL in a unique index as distinct from every
-- other NULL — so any number of revoked rows may exist for the same
-- (user_id, case_id) pair, but at most one row for that pair may ever be
-- active at once, enforced by the database itself (not just application
-- code), even under a race between two admins linking the same pair at once.
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
  UNIQUE KEY uq_ucl_active_pair (user_id, case_id, ((CASE WHEN status = 'active' THEN 1 ELSE NULL END))),
  INDEX idx_ucl_user (user_id, status),
  INDEX idx_ucl_case (case_id, status)
) ENGINE=InnoDB;

SET FOREIGN_KEY_CHECKS = 1;
