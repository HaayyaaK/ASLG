-- ---------------------------------------------------------------------
-- Data seed: Procedural Intelligence taxonomy + rule catalogue.
--
-- NOT EXECUTED BY THE APPLICATION OR BY CLAUDE. Manual review and manual
-- application only, AFTER db\migration_procedural_intelligence.sql has
-- been applied:
--
--   mysql -h 127.0.0.1 -P 3306 -u root -p aslg_legal < db\seed_procedure_rules.sql
--
-- Row-for-row identical to backend/seed.py's seed_procedural_intelligence()
-- (which populates the same tables for a fresh dev/test install) —
-- production cannot use that Python function because backend/seed.py's
-- main() exits immediately once the `users` table has any rows, which it
-- already does here. This file is the production-safe equivalent: pure
-- INSERTs into tables that do not exist until the migration above has run,
-- and it touches NO other table -- no user, case, document, or reminder
-- row is read or written.
--
-- Idempotent via `INSERT ... SELECT ... WHERE NOT EXISTS` on every row, so
-- re-running this file (e.g. after adding one new rule to the bottom) does
-- not duplicate anything already loaded.
--
-- EVERY ProcedureRule below is inserted with is_enabled = 0, regardless of
-- its source_tier. Enabling one is a deliberate, audit-logged, in-app
-- action by a named lawyer (POST /api/rules/{id}/verify — see
-- backend/app/routers/rules.py), never something a seed file does. In
-- particular, note the two competing 'cassation_appeal_*' rows below: two
-- independent professional guides disagree on the Cassation appeal period
-- (30 vs 60 days), and this file deliberately does NOT pick one — both
-- ship disabled until a lawyer checks the primary statute text.
-- ---------------------------------------------------------------------

SET NAMES utf8mb4;

-- ---------------- case_types ----------------
-- source_tier='official_inferred': named after officially-described court
-- divisions (Commercial/Labour/Family/Administrative courts, etc — Phase 1
-- blueprint section 2.2), but the actual MOJ case-type CODE list was
-- explicitly "not determined" (section 2.4) -- these are working labels,
-- not a transcribed official list.
INSERT INTO case_types (code, name_ar, name_en, source_tier, is_enabled, sort_order)
SELECT * FROM (SELECT 'civil' code, 'مدني' name_ar, 'Civil' name_en, 'official_inferred' source_tier, 1 is_enabled, 1 sort_order
  UNION ALL SELECT 'commercial', 'تجاري', 'Commercial', 'official_inferred', 1, 2
  UNION ALL SELECT 'labour', 'عمالي', 'Labour', 'official_inferred', 1, 3
  UNION ALL SELECT 'administrative', 'إداري', 'Administrative', 'official_inferred', 1, 4
  UNION ALL SELECT 'rental', 'إيجارات', 'Rental', 'official_inferred', 1, 5
  UNION ALL SELECT 'family', 'أسرة', 'Family', 'official_inferred', 1, 6
  UNION ALL SELECT 'criminal', 'جزائي', 'Criminal', 'official_inferred', 1, 7
  UNION ALL SELECT 'misdemeanor', 'جنح', 'Misdemeanor', 'official_inferred', 1, 8
  UNION ALL SELECT 'urgent_matters', 'أمور مستعجلة', 'Urgent Matters', 'official_inferred', 1, 9
  UNION ALL SELECT 'payment_order', 'أمر أداء', 'Payment Order', 'official_inferred', 1, 10
  UNION ALL SELECT 'precautionary_order', 'أمر على عريضة', 'Precautionary Order', 'official_inferred', 1, 11
  UNION ALL SELECT 'execution', 'تنفيذ', 'Execution', 'official_inferred', 1, 12
) AS src
WHERE NOT EXISTS (SELECT 1 FROM case_types ct WHERE ct.code = src.code);

-- ---------------- procedure_types ----------------
-- The firm's own workflow vocabulary -- no source_tier column on this
-- table by design (see backend/app/models.py::ProcedureType).
INSERT INTO procedure_types (code, name_ar, name_en, is_terminal, sort_order)
SELECT * FROM (SELECT 'case_filed' code, 'تسجيل الدعوى' name_ar, 'Case Filed' name_en, 0 is_terminal, 1 sort_order
  UNION ALL SELECT 'case_served', 'تبليغ الخصم', 'Defendant Served', 0, 2
  UNION ALL SELECT 'defense_submitted', 'تقديم مذكرة الدفاع', 'Defense Memo Submitted', 0, 3
  UNION ALL SELECT 'hearing_scheduled', 'تحديد جلسة', 'Hearing Scheduled', 0, 4
  UNION ALL SELECT 'hearing_held', 'انعقاد الجلسة', 'Hearing Held', 0, 5
  UNION ALL SELECT 'hearing_postponed', 'تأجيل الجلسة', 'Hearing Postponed', 0, 6
  UNION ALL SELECT 'expert_appointed', 'تعيين خبير', 'Expert Appointed', 0, 7
  UNION ALL SELECT 'expert_report_filed', 'تقديم تقرير الخبير', 'Expert Report Filed', 0, 8
  UNION ALL SELECT 'judgment_issued', 'صدور الحكم', 'Judgment Issued', 0, 9
  UNION ALL SELECT 'judgment_served', 'تبليغ الحكم', 'Judgment Served', 0, 10
  UNION ALL SELECT 'appeal_filed', 'تقديم استئناف', 'Appeal Filed', 0, 11
  UNION ALL SELECT 'appeal_judgment_issued', 'صدور حكم الاستئناف', 'Appeal Judgment Issued', 0, 12
  UNION ALL SELECT 'cassation_filed', 'تقديم طعن بالتمييز', 'Cassation Appeal Filed', 0, 13
  UNION ALL SELECT 'objection_filed', 'تقديم معارضة', 'Objection Filed (in absentia)', 0, 14
  UNION ALL SELECT 'grievance_filed', 'تقديم تظلم', 'Grievance Filed', 0, 15
  UNION ALL SELECT 'payment_order_issued', 'صدور أمر أداء', 'Payment Order Issued', 0, 16
  UNION ALL SELECT 'execution_opened', 'فتح ملف تنفيذ', 'Execution File Opened', 0, 17
  UNION ALL SELECT 'seizure_ordered', 'أمر بالحجز', 'Seizure Ordered', 0, 18
  UNION ALL SELECT 'execution_closed', 'إغلاق ملف التنفيذ', 'Execution File Closed', 1, 19
  UNION ALL SELECT 'case_closed', 'إغلاق الدعوى', 'Case Closed', 1, 20
  -- Fallback target for backfill_procedures.py -- see backend/seed.py's
  -- PROCEDURE_TYPES comment on this same row for why it exists.
  UNION ALL SELECT 'migrated_step', 'خطوة مؤرشفة من السجل السابق', 'Historical Step (migrated)', 0, 21
) AS src
WHERE NOT EXISTS (SELECT 1 FROM procedure_types pt WHERE pt.code = src.code);

-- ---------------- case_statuses ----------------
INSERT INTO case_statuses (code, name_ar, name_en, maps_to_stage, sort_order)
SELECT * FROM (SELECT 'case_registered' code, 'تسجيل الدعوى' name_ar, 'Case Registered' name_en, 'new' maps_to_stage, 1 sort_order
  UNION ALL SELECT 'awaiting_service', 'بانتظار التبليغ', 'Awaiting Service', 'prep', 2
  UNION ALL SELECT 'defense_pending', 'بانتظار مذكرة الدفاع', 'Defense Memo Pending', 'prep', 3
  UNION ALL SELECT 'hearing_pending', 'بانتظار الجلسة', 'Hearing Pending', 'pleading', 4
  UNION ALL SELECT 'expert_assigned', 'خبير معيّن', 'Expert Assigned', 'pleading', 5
  UNION ALL SELECT 'judgment_pending', 'بانتظار الحكم', 'Judgment Pending', 'judgment', 6
  UNION ALL SELECT 'judgment_issued_status', 'صدر الحكم', 'Judgment Issued', 'judgment', 7
  UNION ALL SELECT 'execution_open', 'ملف تنفيذ مفتوح', 'Execution File Open', 'execution', 8
  UNION ALL SELECT 'case_closed_status', 'مغلقة', 'Closed', 'closed', 9
) AS src
WHERE NOT EXISTS (SELECT 1 FROM case_statuses cs WHERE cs.code = src.code);

-- ---------------- doc_classes ----------------
INSERT INTO doc_classes (code, name_ar, name_en)
SELECT * FROM (SELECT 'pleading' code, 'مذكرة' name_ar, 'Pleading' name_en
  UNION ALL SELECT 'power_of_attorney', 'وكالة', 'Power of Attorney'
  UNION ALL SELECT 'judgment', 'حكم', 'Judgment'
  UNION ALL SELECT 'expert_report', 'تقرير خبير', 'Expert Report'
  UNION ALL SELECT 'execution_notice', 'إشعار تنفيذ', 'Execution Notice'
  UNION ALL SELECT 'correspondence', 'مراسلات', 'Correspondence'
  UNION ALL SELECT 'identity_document', 'وثيقة هوية', 'Identity Document'
  UNION ALL SELECT 'other', 'أخرى', 'Other'
) AS src
WHERE NOT EXISTS (SELECT 1 FROM doc_classes dc WHERE dc.code = src.code);

-- ---------------- official_sources ----------------
-- access_mode/requires_captcha are themselves the recorded reason no
-- automated sync exists for any of these -- see Phase 1 blueprint 2.1.
INSERT INTO official_sources (code, name_ar, name_en, base_url, access_mode, requires_captcha, terms_url, is_enabled)
SELECT * FROM (
  SELECT 'moj_eservices' code, 'الخدمات الإلكترونية لوزارة العدل' name_ar, 'MOJ e-Services' name_en,
         'https://eservices.moj.gov.kw' base_url, 'manual_authenticated' access_mode, 1 requires_captcha,
         'https://eservices.moj.gov.kw' terms_url, 1 is_enabled
  UNION ALL SELECT 'sahel', 'سهل', 'Sahel', 'https://sahel.gov.kw', 'manual_authenticated', 0, NULL, 1
  UNION ALL SELECT 'sahel_business', 'سهل للأعمال', 'Sahel Business', 'https://sahel.gov.kw', 'manual_authenticated', 0, NULL, 1
  UNION ALL SELECT 'moj_site', 'موقع وزارة العدل', 'MOJ Website', 'https://www.moj.gov.kw', 'none', 0, NULL, 1
) AS src
WHERE NOT EXISTS (SELECT 1 FROM official_sources os WHERE os.code = src.code);

-- ---------------- procedure_rules ----------------
-- Every row: is_enabled = 0. Resolves trigger/expected procedure_type_id
-- by joining on the codes just inserted above, so this file has no
-- dependency on any particular auto-increment id ordering.
INSERT INTO procedure_rules
  (code, version, trigger_procedure_type_id, expected_procedure_type_id, deadline_days, day_basis,
   counts_from, source_tier, legal_citation, source_url, notes, is_enabled)
SELECT src.code, src.version, tpt.id, ept.id, src.deadline_days, src.day_basis,
       src.counts_from, src.source_tier, src.legal_citation, src.source_url, src.notes, 0
FROM (
  SELECT 'appeal_first_instance_to_appeal' code, 1 version, 'judgment_issued' trigger_code,
         'appeal_filed' expected_code, 30 deadline_days, 'calendar' day_basis, 'judgment_date' counts_from,
         'official_inferred' source_tier, 'Decree-Law No. 38/1980' legal_citation,
         'https://www.dlapiperintelligence.com/litigation/insight/index.html?t=01-overview-of-court-system&c=KW' source_url,
         'Consistent across two independent professional guides (DLA Piper, Chambers) as of Sept 2026, but neither is the primary statute text -- verify Art. references before enabling.' notes
  UNION ALL
  SELECT 'cassation_appeal_60d', 1, 'appeal_judgment_issued', 'cassation_filed', 60, 'calendar', 'judgment_date',
         'unverified', 'Decree-Law No. 38/1980, Art. 153 (per Chambers Litigation 2026 guide)',
         'https://practiceguides.chambers.com/practice-guides/litigation-2026/kuwait',
         'CONFLICTS with cassation_appeal_30d -- Chambers cites Art. 153 for 60 days; DLA Piper states 30 days for the same transition. Verify against the primary statute text before enabling either variant; do not enable both.'
  UNION ALL
  SELECT 'cassation_appeal_30d', 1, 'appeal_judgment_issued', 'cassation_filed', 30, 'calendar', 'judgment_date',
         'unverified', 'Decree-Law No. 38/1980 (per DLA Piper Global Litigation Guide)',
         'https://www.dlapiperintelligence.com/litigation/insight/index.html?t=06-appeals&c=KW',
         'CONFLICTS with cassation_appeal_60d -- see that row''s notes. Verify against the primary statute text before enabling either variant; do not enable both.'
  UNION ALL
  SELECT 'payment_order_grievance', 1, 'payment_order_issued', 'grievance_filed', 10, 'calendar', 'notification',
         'unverified', 'Secondary commercial source re: أمر أداء grievance (تظلم) -- NOT primary statute text', NULL,
         'Debtor''s reasoned grievance window after notification of a payment order. Sourced from a secondary commercial-law summary, not the primary statute -- verify before enabling.'
  UNION ALL
  SELECT 'payment_order_service_validity', 1, 'payment_order_issued', 'case_served', 180, 'calendar', 'occurrence',
         'unverified', 'Secondary commercial source: payment order is void if not served within 6 months', NULL,
         'Approximated as 180 days for "six months" -- verify the statute''s own definition of the period before enabling (some Kuwaiti provisions count lunar/Hijri months).'
) AS src
JOIN procedure_types tpt ON tpt.code = src.trigger_code
JOIN procedure_types ept ON ept.code = src.expected_code
WHERE NOT EXISTS (
  SELECT 1 FROM procedure_rules pr WHERE pr.code = src.code AND pr.version = src.version
);
