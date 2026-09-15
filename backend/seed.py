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
    CaseTimeline,
    Court,
    CourtSession,
    Document,
    ExecutionFile,
    Expert,
    Module,
    Notification,
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

MODULES = ["dashboard", "search", "cases", "documents", "notifications", "users", "reminders"]

PERMISSIONS = {
    "Admin": {"dashboard": "full", "search": "full", "cases": "full", "documents": "full", "notifications": "full", "users": "full", "reminders": "full"},
    "Lawyer": {"dashboard": "full", "search": "full", "cases": "full", "documents": "full", "notifications": "full", "users": "none", "reminders": "full"},
    "consultant": {"dashboard": "full", "search": "edit", "cases": "limited", "documents": "edit", "notifications": "full", "users": "none", "reminders": "edit"},
    "delegate": {"dashboard": "full", "search": "edit", "cases": "view", "documents": "edit", "notifications": "full", "users": "none", "reminders": "view"},
    "User": {"dashboard": "limited", "search": "none", "cases": "own", "documents": "own", "notifications": "full", "users": "none", "reminders": "none"},
}

COURTS = [
    ("cassation", "محكمة التمييز", "Court of Cassation"),
    ("appeal", "محكمة الاستئناف", "Court of Appeal"),
    ("first_instance", "المحكمة الكلية", "Court of First Instance"),
    ("misdemeanor", "محكمة الجنح", "Misdemeanor Court"),
    ("family", "محكمة الأسرة", "Family Court"),
    ("execution", "دائرة التنفيذ", "Execution Circuit"),
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
