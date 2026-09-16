"""One-time data loader for the ASLG database.

Run after schema.sql has been applied:  python seed.py
Safe to re-run — it exits early if the users table already has rows.

REQUIRED ENVIRONMENT VARIABLES (set in backend/.env — see .env.example):
  ASLG_SEED_ADMIN_PASSWORD  Password for the seeded System Admin account.
  ASLG_SEED_STAFF_PASSWORD  Password for every other seeded demo account
                            (Lawyer/Consultant/Delegate/Client).

No password is hardcoded anywhere in this file. If a variable above is
unset and a user needing that password would actually be created, seeding
fails immediately with a clear error rather than falling back to any
default — this file previously shipped `DEFAULT_PASSWORD = "Passw0rd!"`,
which went on to become the real, never-rotated production Admin password.
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Case,
    CaseNote,
    CaseStatus,
    CaseTimeline,
    CaseType,
    Court,
    CourtSession,
    DocClass,
    Document,
    ExecutionFile,
    Expert,
    Module,
    Notification,
    OfficialSource,
    ProcedureRule,
    ProcedureType,
    Role,
    RolePermission,
    User,
)
from app.security import hash_password  # noqa: E402


# Kuwait runs on UTC+3 all year — it abolished daylight saving in 1990 — so a
# fixed offset is exact here and avoids making the seed depend on the IANA tz
# database, which is not present on this Windows host (zoneinfo raises
# ZoneInfoNotFoundError for "Asia/Kuwait" without the tzdata package).
KUWAIT_UTC_OFFSET_HOURS = 3


def days_from_now(n: int, h: int = 9, m: int = 0) -> datetime:
    """A seeded timestamp, given as **Kuwait local** wall-clock time, returned
    as the naive UTC value this application stores.

    The h/m arguments read as the time a human means — a 9:30 hearing is
    written `days_from_now(2, 9, 30)` and a lawyer sees "9:30 AM". Previously
    that 9:30 was written straight into the database as 9:30 *UTC*, which the
    UI correctly renders as 12:30 PM Kuwait: every seeded court time appeared
    three hours later than intended.

    Storage stays naive UTC (unchanged architecture — see app/database.py,
    which pins the MySQL session to +00:00); only the interpretation of the
    arguments is corrected, in one place rather than at ~40 call sites.
    """
    d = datetime.utcnow() + timedelta(days=n)
    local = d.replace(hour=h, minute=m, second=0, microsecond=0)
    return local - timedelta(hours=KUWAIT_UTC_OFFSET_HOURS)


ROLES = [
    ("Admin", "مدير النظام", "System Admin"),
    ("Lawyer", "محامٍ", "Lawyer"),
    ("consultant", "مستشار", "Consultant"),
    ("delegate", "مندوب", "Delegate"),
    ("User", "عميل", "Client"),
]

MODULES = [
    "dashboard", "search", "cases", "documents", "notifications", "users", "reminders",
    # Procedural Intelligence — see db/migration_procedural_intelligence.sql
    # section 5, which this list and PERMISSIONS below deliberately mirror
    # so a fresh dev/test install and a manually-migrated production
    # database end up with the identical access matrix.
    "procedures", "deadlines", "official_sync", "rules_admin",
]

PERMISSIONS = {
    "Admin": {"dashboard": "full", "search": "full", "cases": "full", "documents": "full", "notifications": "full", "users": "full", "reminders": "full", "procedures": "full", "deadlines": "full", "official_sync": "full", "rules_admin": "full"},
    "Lawyer": {"dashboard": "full", "search": "full", "cases": "full", "documents": "full", "notifications": "full", "users": "none", "reminders": "full", "procedures": "full", "deadlines": "full", "official_sync": "full", "rules_admin": "view"},
    "consultant": {"dashboard": "full", "search": "edit", "cases": "limited", "documents": "edit", "notifications": "full", "users": "none", "reminders": "edit", "procedures": "edit", "deadlines": "edit", "official_sync": "edit", "rules_admin": "none"},
    "delegate": {"dashboard": "full", "search": "edit", "cases": "view", "documents": "edit", "notifications": "full", "users": "none", "reminders": "view", "procedures": "view", "deadlines": "view", "official_sync": "edit", "rules_admin": "none"},
    "User": {"dashboard": "limited", "search": "none", "cases": "own", "documents": "own", "notifications": "full", "users": "none", "reminders": "none", "procedures": "own", "deadlines": "own", "official_sync": "none", "rules_admin": "none"},
}

COURTS = [
    ("cassation", "محكمة التمييز", "Court of Cassation"),
    ("appeal", "محكمة الاستئناف", "Court of Appeal"),
    ("first_instance", "المحكمة الكلية", "Court of First Instance"),
    ("misdemeanor", "محكمة الجنح", "Misdemeanor Court"),
    ("family", "محكمة الأسرة", "Family Court"),
    ("execution", "دائرة التنفيذ", "Execution Circuit"),
]

# ---------------------------------------------------------------------
# Procedural Intelligence taxonomy + rule catalogue (Phase 1 blueprint
# section 2.3/4.2). Mirrored, row-for-row, in db/seed_procedure_rules.sql
# for production (that file is what actually gets applied there — this
# block only runs against a fresh dev/test database; see
# seed_procedural_intelligence() below and its call site in run_seed()).
#
# CASE_TYPES: named directly after the specialised court divisions the
# Sept 2026 research confirmed exist (Commercial/Labour/Family/
# Administrative courts, etc — Phase 1 blueprint section 2.2), so
# source_tier='official_inferred' — inferred from officially-described
# court structure, NOT itself an official case-type code list (the real
# MOJ code list was explicitly "not determined", section 2.4).
# ---------------------------------------------------------------------
CASE_TYPES = [
    ("civil", "مدني", "Civil"),
    ("commercial", "تجاري", "Commercial"),
    ("labour", "عمالي", "Labour"),
    ("administrative", "إداري", "Administrative"),
    ("rental", "إيجارات", "Rental"),
    ("family", "أسرة", "Family"),
    ("criminal", "جزائي", "Criminal"),
    ("misdemeanor", "جنح", "Misdemeanor"),
    ("urgent_matters", "أمور مستعجلة", "Urgent Matters"),
    ("payment_order", "أمر أداء", "Payment Order"),
    ("precautionary_order", "أمر على عريضة", "Precautionary Order"),
    ("execution", "تنفيذ", "Execution"),
]

# PROCEDURE_TYPES: the firm's own workflow vocabulary, not a legal
# assertion (no source_tier — see models.py's ProcedureType docstring).
PROCEDURE_TYPES = [
    ("case_filed", "تسجيل الدعوى", "Case Filed", False),
    ("case_served", "تبليغ الخصم", "Defendant Served", False),
    ("defense_submitted", "تقديم مذكرة الدفاع", "Defense Memo Submitted", False),
    ("hearing_scheduled", "تحديد جلسة", "Hearing Scheduled", False),
    ("hearing_held", "انعقاد الجلسة", "Hearing Held", False),
    ("hearing_postponed", "تأجيل الجلسة", "Hearing Postponed", False),
    ("expert_appointed", "تعيين خبير", "Expert Appointed", False),
    ("expert_report_filed", "تقديم تقرير الخبير", "Expert Report Filed", False),
    ("judgment_issued", "صدور الحكم", "Judgment Issued", False),
    ("judgment_served", "تبليغ الحكم", "Judgment Served", False),
    ("appeal_filed", "تقديم استئناف", "Appeal Filed", False),
    ("appeal_judgment_issued", "صدور حكم الاستئناف", "Appeal Judgment Issued", False),
    ("cassation_filed", "تقديم طعن بالتمييز", "Cassation Appeal Filed", False),
    ("objection_filed", "تقديم معارضة", "Objection Filed (in absentia)", False),
    ("grievance_filed", "تقديم تظلم", "Grievance Filed", False),
    ("payment_order_issued", "صدور أمر أداء", "Payment Order Issued", False),
    ("execution_opened", "فتح ملف تنفيذ", "Execution File Opened", False),
    ("seizure_ordered", "أمر بالحجز", "Seizure Ordered", False),
    ("execution_closed", "إغلاق ملف التنفيذ", "Execution File Closed", True),
    ("case_closed", "إغلاق الدعوى", "Case Closed", True),
    # Fallback target for backfill_procedures.py: a pre-existing case_timeline
    # step whose free-text title doesn't match any canonical type above
    # (real-world entries won't all use these exact phrasings) is recorded
    # under this generic type rather than guessed into a specific one it may
    # not actually be.
    ("migrated_step", "خطوة مؤرشفة من السجل السابق", "Historical Step (migrated)", False),
]

# CASE_STATUSES: firm-operational refinements of the existing `stage` enum
# (source_tier is implicitly 'firm_entered' — these are workflow labels the
# firm defines for itself, not a claim about Kuwaiti law).
CASE_STATUSES = [
    ("case_registered", "تسجيل الدعوى", "Case Registered", "new"),
    ("awaiting_service", "بانتظار التبليغ", "Awaiting Service", "prep"),
    ("defense_pending", "بانتظار مذكرة الدفاع", "Defense Memo Pending", "prep"),
    ("hearing_pending", "بانتظار الجلسة", "Hearing Pending", "pleading"),
    ("expert_assigned", "خبير معيّن", "Expert Assigned", "pleading"),
    ("judgment_pending", "بانتظار الحكم", "Judgment Pending", "judgment"),
    ("judgment_issued_status", "صدر الحكم", "Judgment Issued", "judgment"),
    ("execution_open", "ملف تنفيذ مفتوح", "Execution File Open", "execution"),
    ("case_closed_status", "مغلقة", "Closed", "closed"),
]

DOC_CLASSES = [
    ("pleading", "مذكرة", "Pleading"),
    ("power_of_attorney", "وكالة", "Power of Attorney"),
    ("judgment", "حكم", "Judgment"),
    ("expert_report", "تقرير خبير", "Expert Report"),
    ("execution_notice", "إشعار تنفيذ", "Execution Notice"),
    ("correspondence", "مراسلات", "Correspondence"),
    ("identity_document", "وثيقة هوية", "Identity Document"),
    ("other", "أخرى", "Other"),
]

# OFFICIAL_SOURCES: (code, name_ar, name_en, base_url, access_mode,
# requires_captcha, terms_url). access_mode/requires_captcha are the
# recorded REASON no automated sync exists — see Phase 1 blueprint 2.1 and
# procedures.py's module docstring.
OFFICIAL_SOURCES = [
    ("moj_eservices", "الخدمات الإلكترونية لوزارة العدل", "MOJ e-Services",
     "https://eservices.moj.gov.kw", "manual_authenticated", True, "https://eservices.moj.gov.kw"),
    ("sahel", "سهل", "Sahel", "https://sahel.gov.kw", "manual_authenticated", False, None),
    ("sahel_business", "سهل للأعمال", "Sahel Business",
     "https://sahel.gov.kw", "manual_authenticated", False, None),
    ("moj_site", "موقع وزارة العدل", "MOJ Website", "https://www.moj.gov.kw", "none", False, None),
]

# PROCEDURE_RULES: the brain, as data. Every row ships is_enabled=False.
# Column order: code, version, trigger_code, expected_code, deadline_days,
# day_basis, counts_from, source_tier, legal_citation, source_url, notes.
# See Phase 1 blueprint section 2.3 for the source tiers and, in
# particular, why the Cassation deadline is TWO competing disabled
# candidates rather than one guessed value.
_CASSATION_CONFLICT_NOTE = (
    "CONFLICTS with the other cassation_appeal_* candidate rule — Chambers' "
    "Litigation 2026 guide cites Art. 153 of Decree-Law 38/1980 for 60 days; "
    "DLA Piper's Global Litigation Guide states 30 days for the same "
    "transition. Verify against the primary statute text before enabling "
    "either variant; do not enable both."
)
PROCEDURE_RULES = [
    dict(
        code="appeal_first_instance_to_appeal", version=1,
        trigger="judgment_issued", expected="appeal_filed", deadline_days=30,
        day_basis="calendar", counts_from="judgment_date", source_tier="official_inferred",
        legal_citation="Decree-Law No. 38/1980",
        source_url="https://www.dlapiperintelligence.com/litigation/insight/index.html?t=01-overview-of-court-system&c=KW",
        notes="Consistent across two independent professional guides (DLA Piper, Chambers) as of Sept 2026, "
              "but neither is the primary statute text -- verify Art. references before enabling.",
    ),
    dict(
        code="cassation_appeal_60d", version=1,
        trigger="appeal_judgment_issued", expected="cassation_filed", deadline_days=60,
        day_basis="calendar", counts_from="judgment_date", source_tier="unverified",
        legal_citation="Decree-Law No. 38/1980, Art. 153 (per Chambers Litigation 2026 guide)",
        source_url="https://practiceguides.chambers.com/practice-guides/litigation-2026/kuwait",
        notes=_CASSATION_CONFLICT_NOTE,
    ),
    dict(
        code="cassation_appeal_30d", version=1,
        trigger="appeal_judgment_issued", expected="cassation_filed", deadline_days=30,
        day_basis="calendar", counts_from="judgment_date", source_tier="unverified",
        legal_citation="Decree-Law No. 38/1980 (per DLA Piper Global Litigation Guide)",
        source_url="https://www.dlapiperintelligence.com/litigation/insight/index.html?t=06-appeals&c=KW",
        notes=_CASSATION_CONFLICT_NOTE,
    ),
    dict(
        code="payment_order_grievance", version=1,
        trigger="payment_order_issued", expected="grievance_filed", deadline_days=10,
        day_basis="calendar", counts_from="notification", source_tier="unverified",
        legal_citation="Secondary commercial source re: أمر أداء grievance (تظلم) -- NOT primary statute text",
        source_url=None,
        notes="Debtor's reasoned grievance window after notification of a payment order. Sourced from a "
              "secondary commercial-law summary, not the primary statute -- verify before enabling.",
    ),
    dict(
        code="payment_order_service_validity", version=1,
        trigger="payment_order_issued", expected="case_served", deadline_days=180,
        day_basis="calendar", counts_from="occurrence", source_tier="unverified",
        legal_citation="Secondary commercial source: payment order is void if not served within 6 months",
        source_url=None,
        notes="Approximated as 180 days for 'six months' -- verify the statute's own definition of the "
              "period before enabling (some Kuwaiti provisions count lunar/Hijri months).",
    ),
]


USERS = [
    dict(name_en="Tamer Salem", name_ar="تامر سالم", username="tamer.salem", occupation="IT Administator", role="Admin"),
    dict(name_en="Hassan Falah", name_ar="حسن فلاح", username="hassan.falah", occupation="Lawyer", role="Lawyer", is_owner=True),
    dict(name_en="Jaber Barrak", name_ar="جابر براك", username="jaber.barrak", occupation="Lawyer", role="Lawyer", is_owner=True),
    dict(name_en="Mohammad Ahmad", name_ar="محمد أحمد", username="mohammad.ahmad", occupation="consultant", role="consultant"),
    dict(name_en="Mohammad Mahmoud", name_ar="محمد محمود", username="mohammad.mahmoud", occupation="consultant", role="consultant"),
    dict(name_en="Ahmad Sayed", name_ar="أحمد سيد", username="ahmad.sayed", occupation="delegate", role="delegate"),
    dict(name_en="Ahmad Saber", name_ar="أحمد صابر", username="ahmad.saber", occupation="delegate", role="delegate"),
    dict(name_en="Jarrah Saad", name_ar="جراح سعد", username="jarrah.saad", occupation="Client", role="User", civil_id="284010112233"),
    dict(name_en="Fahad Fazzaa", name_ar="فهد فزاع", username="fahad.fazzaa", occupation="Client", role="User", civil_id="290020098877"),
]

PLACEHOLDER_PDF = b"%PDF-1.4\n%ASLG demo document\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
PLACEHOLDER_JPG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300030202020202030202020304040304050805050405090b0908080a0708090a0b0c0e0e0e0e0e0e0c0cffd9"
)


def seed_procedural_intelligence(db):
    """Populate the Procedural Intelligence taxonomy + rule catalogue.

    Idempotent on its own (checked against case_types specifically, not the
    users-table guard `main()` uses) so it is safe even if ever called a
    second time against a database that already has this data — though in
    practice it only ever runs once, from inside run_seed(), on a database
    that had zero users. Every ProcedureRule is inserted with is_enabled
    False regardless of source_tier: enabling one is a Phase 2 runtime
    action (routers/rules.py), never a seed-time one.
    """
    if db.query(CaseType).first() is not None:
        return

    case_type_rows = {}
    for code, ar, en in CASE_TYPES:
        row = CaseType(code=code, name_ar=ar, name_en=en, source_tier="official_inferred", is_enabled=True)
        db.add(row)
        case_type_rows[code] = row

    procedure_type_rows = {}
    for code, ar, en, terminal in PROCEDURE_TYPES:
        row = ProcedureType(code=code, name_ar=ar, name_en=en, is_terminal=terminal)
        db.add(row)
        procedure_type_rows[code] = row

    for code, ar, en, maps_to in CASE_STATUSES:
        db.add(CaseStatus(code=code, name_ar=ar, name_en=en, maps_to_stage=maps_to))

    for code, ar, en in DOC_CLASSES:
        db.add(DocClass(code=code, name_ar=ar, name_en=en))

    for code, ar, en, url, access_mode, captcha, terms in OFFICIAL_SOURCES:
        db.add(OfficialSource(
            code=code, name_ar=ar, name_en=en, base_url=url,
            access_mode=access_mode, requires_captcha=captcha, terms_url=terms,
        ))
    db.flush()

    for r in PROCEDURE_RULES:
        db.add(ProcedureRule(
            code=r["code"], version=r["version"],
            trigger_procedure_type_id=procedure_type_rows[r["trigger"]].id,
            expected_procedure_type_id=procedure_type_rows[r["expected"]].id,
            deadline_days=r["deadline_days"], day_basis=r["day_basis"], counts_from=r["counts_from"],
            source_tier=r["source_tier"], legal_citation=r["legal_citation"], source_url=r["source_url"],
            notes=r["notes"], is_enabled=False,
        ))
    db.flush()


def run_seed(db):
    """Populate the (expected-empty) database with the demo/seed dataset.

    Pure population logic, no commit/close of its own — shared by the CLI
    entry point below and the admin Factory-Reset endpoint (app/routers/admin.py)
    so there is exactly one seeding implementation to keep in sync. Callers own
    the transaction: call db.commit() after this returns.
    """
    role_rows = {}
    for code, ar, en in ROLES:
        r = Role(code=code, name_ar=ar, name_en=en)
        db.add(r)
        role_rows[code] = r
    db.flush()

    module_rows = {}
    for code in MODULES:
        m = Module(code=code)
        db.add(m)
        module_rows[code] = m
    db.flush()

    for role_code, mods in PERMISSIONS.items():
        for module_code, level in mods.items():
            db.add(RolePermission(role_id=role_rows[role_code].id, module_id=module_rows[module_code].id, access_level=level))

    court_rows = {}
    for level_code, ar, en in COURTS:
        c = Court(level_code=level_code, name_ar=ar, name_en=en)
        db.add(c)
        court_rows[level_code] = c
    db.flush()

    seed_procedural_intelligence(db)

    # Never touch a user that already exists, and never create a second
    # Admin if one is already present — both checked against the real table,
    # not just this batch, so this stays safe if run_seed is ever called
    # against a database that already has some users in it.
    existing_usernames = {row[0] for row in db.query(User.username).all()}
    admin_already_exists = db.query(User).join(Role).filter(Role.code == "Admin").first() is not None

    user_rows = {}
    for u in USERS:
        if u["username"] in existing_usernames:
            continue
        is_admin = u["role"] == "Admin"
        if is_admin and admin_already_exists:
            continue
        password = settings.seed_admin_password if is_admin else settings.seed_staff_password
        if not password:
            var_name = "ASLG_SEED_ADMIN_PASSWORD" if is_admin else "ASLG_SEED_STAFF_PASSWORD"
            raise RuntimeError(f"Set {var_name} before running seed — no seed password is hardcoded in this file.")
        row = User(
            name_en=u["name_en"], name_ar=u["name_ar"], username=u["username"],
            occupation=u["occupation"], role_id=role_rows[u["role"]].id,
            civil_id=u.get("civil_id"), is_owner=u.get("is_owner", False),
            password_hash=hash_password(password),
        )
        db.add(row)
        user_rows[u["username"]] = row
    db.flush()

    hassan = user_rows["hassan.falah"]
    jaber = user_rows["jaber.barrak"]

    case1 = Case(
        case_number="1123", case_year=2024, court_id=court_rows["first_instance"].id,
        category_ar="تجاري", category_en="Commercial",
        parties_ar="شركة الخليج للمقاولات ضد مؤسسة النور", parties_en="Gulf Contracting Co. vs Al-Noor Est.",
        civil_id="284010112233", status="active", stage="pleading", assigned_lawyer_id=hassan.id,
        summary_ar="دعوى مطالبة مالية بقيمة 145,000 د.ك ناتجة عن عقد مقاولة.",
        summary_en="Financial claim lawsuit for KWD 145,000 arising from a contracting agreement.",
        next_hearing_at=days_from_now(2, 9, 30),
    )
    case2 = Case(
        case_number="0847", case_year=2024, court_id=court_rows["family"].id,
        category_ar="أحوال شخصية", category_en="Personal Status",
        parties_ar="س.م ضد ع.ك", parties_en="S.M. vs A.K.",
        civil_id="290020098877", status="active", stage="prep", assigned_lawyer_id=jaber.id,
        summary_ar="دعوى نفقة وحضانة.", summary_en="Alimony and child custody lawsuit.",
        next_hearing_at=days_from_now(6, 10, 0),
    )
    case3 = Case(
        case_number="5521", case_year=2023, court_id=court_rows["first_instance"].id,
        category_ar="مدني", category_en="Civil",
        parties_ar="ورثة المرحوم خالد العنزي ضد شركة التأمين المتحدة",
        parties_en="Heirs of Khalid Al-Anzi vs United Insurance Co.",
        civil_id="275030011122", status="active", stage="judgment", assigned_lawyer_id=hassan.id,
        summary_ar="دعوى تعويض حادث مروري.", summary_en="Traffic accident compensation lawsuit.",
        next_hearing_at=days_from_now(30, 9, 0),
    )
    case4 = Case(
        case_number="1990", case_year=2024, court_id=court_rows["execution"].id,
        category_ar="تنفيذ", category_en="Execution",
        parties_ar="بنك الوطن ضد مصنع الاتحاد للبلاستيك", parties_en="National Bank vs Al-Ittihad Plastics Factory",
        civil_id="260040055566", status="active", stage="execution", assigned_lawyer_id=jaber.id,
        summary_ar="ملف تنفيذ حكم مالي بقيمة 320,000 د.ك.",
        summary_en="Enforcement file for a financial judgment worth KWD 320,000.",
        next_hearing_at=days_from_now(1, 11, 0),
    )
    case5 = Case(
        case_number="3301", case_year=2022, court_id=court_rows["appeal"].id,
        category_ar="عمالي", category_en="Labor",
        parties_ar="موظف سابق ضد شركة الخدمات الفنية", parties_en="Former Employee vs Technical Services Co.",
        civil_id="295050033344", status="closed", stage="closed", assigned_lawyer_id=hassan.id,
        summary_ar="دعوى مستحقات عمالية - أغلقت بتسوية ودية.",
        summary_en="Labor dues lawsuit - closed via amicable settlement.",
        next_hearing_at=None,
    )
    for c in (case1, case2, case3, case4, case5):
        db.add(c)
    db.flush()

    timelines = [
        (case1, [
            ("تسجيل الدعوى", "Case Filed", days_from_now(-40), True),
            ("أول جلسة - تحديد الخبير", "First Hearing - Expert Appointed", days_from_now(-25), True),
            ("تقديم مذكرة الرد", "Response Memo Submitted", days_from_now(-10), True),
            ("جلسة المرافعة النهائية", "Final Pleading Hearing", days_from_now(2), False),
            ("النطق بالحكم", "Judgment Pronouncement", days_from_now(20), False),
        ]),
        (case2, [
            ("تسجيل الدعوى", "Case Filed", days_from_now(-15), True),
            ("جلسة تسوية", "Settlement Hearing", days_from_now(-3), True),
            ("جلسة استماع", "Hearing Session", days_from_now(6), False),
        ]),
        (case3, [
            ("تسجيل الدعوى", "Case Filed", days_from_now(-200), True),
            ("ندب خبير هندسي", "Engineering Expert Appointed", days_from_now(-90), True),
            ("صدور الحكم الابتدائي", "First-Instance Judgment Issued", days_from_now(-20), True),
            ("جلسة الاستئناف", "Appeal Hearing", days_from_now(30), False),
        ]),
        (case4, [
            ("صدور السند التنفيذي", "Writ of Execution Issued", days_from_now(-60), True),
            ("فتح ملف تنفيذ", "Execution File Opened", days_from_now(-30), True),
            ("جلسة حجز على المنقولات", "Attachment on Movables Hearing", days_from_now(1), False),
        ]),
        (case5, [
            ("تسجيل الدعوى", "Case Filed", days_from_now(-400), True),
            ("تسوية ودية", "Amicable Settlement", days_from_now(-100), True),
            ("إغلاق الملف", "File Closed", days_from_now(-95), True),
        ]),
    ]
    for case, steps in timelines:
        for i, (ar, en, dt, done) in enumerate(steps):
            db.add(CaseTimeline(case_id=case.id, step_title_ar=ar, step_title_en=en, step_date=dt, is_done=done, sort_order=i))

    db.add(CaseNote(case_id=case1.id, author_id=hassan.id, note_text="تم استلام تقرير الخبير الحسابي، يدعم موقف الموكل.", created_at=days_from_now(-5)))
    db.add(CaseNote(case_id=case3.id, author_id=hassan.id, note_text="صدر الحكم لصالح الموكل، بانتظار قرار الاستئناف من الطرف الآخر.", created_at=days_from_now(-18)))

    db.add(CourtSession(case_id=case1.id, circuit_ar="الدائرة التجارية 4", circuit_en="Commercial Circuit 4", courtroom="قاعة 12", session_at=days_from_now(2, 9, 30), status="scheduled"))
    db.add(CourtSession(case_id=case2.id, circuit_ar="دائرة الأسرة 2", circuit_en="Family Circuit 2", courtroom="قاعة 5", session_at=days_from_now(6, 10, 0), status="scheduled"))
    db.add(CourtSession(case_id=case4.id, circuit_ar="دائرة التنفيذ 7", circuit_en="Execution Circuit 7", courtroom="قاعة 3", session_at=days_from_now(1, 11, 0), status="scheduled"))
    db.add(CourtSession(case_id=case3.id, circuit_ar="الدائرة المدنية 1", circuit_en="Civil Circuit 1", courtroom="قاعة 8", session_at=days_from_now(-20, 9, 0), status="done"))
    db.add(CourtSession(case_id=case1.id, circuit_ar="الدائرة التجارية 4", circuit_en="Commercial Circuit 4", courtroom="قاعة 12", session_at=days_from_now(-10, 9, 0), status="done"))

    db.add(Expert(case_id=case1.id, file_no="خ-2024-118", expert_name="م. سالم العتيبي", specialty_ar="خبرة هندسية إنشائية", specialty_en="Structural Engineering", assigned_at=days_from_now(-25), status="in_progress"))
    db.add(Expert(case_id=case3.id, file_no="خ-2023-092", expert_name="أ. بدر الفهد", specialty_ar="خبرة حسابية", specialty_en="Accounting Expertise", assigned_at=days_from_now(-90), status="completed"))
    db.add(Expert(case_id=case2.id, file_no="خ-2024-201", expert_name="د. منى الرشيد", specialty_ar="خبرة اجتماعية أسرية", specialty_en="Family Social Expertise", assigned_at=days_from_now(-3), status="scheduled"))

    db.add(ExecutionFile(case_id=case4.id, file_no="ت-2024-4471", amount="320000.000", currency="KWD", status="in_progress", last_action_ar="حجز تحفظي على منقولات", last_action_en="Precautionary attachment on movables", last_action_at=days_from_now(-5)))
    db.add(ExecutionFile(case_id=case5.id, file_no="ت-2023-3390", amount="8500.000", currency="KWD", status="closed", last_action_ar="تم السداد الكامل", last_action_en="Fully settled", last_action_at=days_from_now(-95)))

    upload_root = settings.upload_path
    seed_docs = [
        (case1, "عقد المقاولة الأصلي.pdf", "pdf", PLACEHOLDER_PDF, "approved", hassan, -38),
        (case1, "تقرير الخبير الحسابي.pdf", "pdf", PLACEHOLDER_PDF, "approved", hassan, -5),
        (case2, "شهادة ميلاد.jpg", "jpg", PLACEHOLDER_JPG, "pending", jaber, -15),
        (case4, "السند التنفيذي.pdf", "pdf", PLACEHOLDER_PDF, "approved", jaber, -60),
    ]
    for case, name, ext, content, doc_status, uploader, age_days in seed_docs:
        case_dir = upload_root / str(case.id)
        case_dir.mkdir(parents=True, exist_ok=True)
        import uuid as _uuid
        stored = case_dir / f"{_uuid.uuid4().hex}.{ext}"
        stored.write_bytes(content)
        db.add(Document(
            case_id=case.id, file_name=name, file_type=ext, file_size=len(content),
            storage_path=str(stored), status=doc_status, uploaded_by=uploader.id,
            uploaded_at=days_from_now(age_days),
        ))

    db.add(Notification(target_role_id=role_rows["Admin"].id, type="hearing", message_ar="جلسة عاجلة غداً للقضية 1990/2024 - دائرة التنفيذ 7", message_en="Urgent hearing tomorrow for case 1990/2024 - Execution Circuit 7", is_read=False, created_at=days_from_now(0, 8, 0)))
    db.add(Notification(target_role_id=role_rows["Lawyer"].id, type="hearing", message_ar="جلسة عاجلة غداً للقضية 1990/2024 - دائرة التنفيذ 7", message_en="Urgent hearing tomorrow for case 1990/2024 - Execution Circuit 7", is_read=False, created_at=days_from_now(0, 8, 0)))
    db.add(Notification(user_id=hassan.id, type="status", message_ar="تم تحديث حالة القضية 1123/2024 إلى: مرافعة", message_en="Case 1123/2024 status updated to: Pleading", is_read=False, created_at=days_from_now(-1, 14, 0)))
    db.add(Notification(user_id=jaber.id, type="document", message_ar="بانتظار مراجعة مستند: شهادة ميلاد.jpg", message_en="Document pending review: birth_certificate.jpg", is_read=True, created_at=days_from_now(-2, 10, 0)))
    db.add(Notification(target_role_id=role_rows["Admin"].id, type="system", message_ar="تم إنشاء نسخة احتياطية للنظام بنجاح", message_en="System backup completed successfully", is_read=True, created_at=days_from_now(-3, 3, 0)))


def main():
    db = SessionLocal()
    try:
        if db.query(User).count() > 0:
            print("Users table already has data — seed already applied, exiting.")
            return
        run_seed(db)
        db.commit()
        # Never echo the actual password here — see the module docstring on
        # why this file no longer holds one to echo in the first place.
        print(f"Seed complete: {len(USERS)} users, 5 cases, documents stored under {settings.upload_path.resolve()}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
