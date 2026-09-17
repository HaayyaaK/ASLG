from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    users: Mapped[list["User"]] = relationship(back_populates="role")
    permissions: Mapped[list["RolePermission"]] = relationship(back_populates="role")


class Module(Base):
    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), primary_key=True)
    access_level: Mapped[str] = mapped_column(
        Enum("none", "view", "own", "limited", "edit", "full"), default="none"
    )

    role: Mapped[Role] = relationship(back_populates="permissions")
    module: Mapped[Module] = relationship()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_en: Mapped[str]
    name_ar: Mapped[str]
    username: Mapped[str] = mapped_column(unique=True)
    email: Mapped[str | None] = mapped_column(unique=True, default=None)
    occupation: Mapped[str | None] = mapped_column(default=None)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    civil_id: Mapped[str | None] = mapped_column(default=None)
    password_hash: Mapped[str]
    is_owner: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow
    )

    role: Mapped[Role] = relationship(back_populates="users")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    action: Mapped[str]
    entity_type: Mapped[str | None] = mapped_column(default=None)
    entity_id: Mapped[int | None] = mapped_column(default=None)
    meta_json: Mapped[dict | None] = mapped_column(JSON, default=None)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    user: Mapped["User | None"] = relationship()


class Court(Base):
    __tablename__ = "courts"

    id: Mapped[int] = mapped_column(primary_key=True)
    level_code: Mapped[str] = mapped_column(
        Enum("cassation", "appeal", "first_instance", "misdemeanor", "family", "execution")
    )
    name_ar: Mapped[str]
    name_en: Mapped[str]


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (UniqueConstraint("case_number", "case_year", name="uq_case_number_year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    case_number: Mapped[str]
    # The "Automated Number" (الرقم الآلي) -- the long identifier a court or
    # client quotes instead of the short case_number/case_year pair. Format
    # YYYYNNNNN: a four-digit year followed by five digits, nine characters
    # in total.
    #
    # Until db/migration_automated_case_number.sql this had no column at
    # all: routers/search.py accepted an `automated_number` query parameter
    # and matched it against `case_number` as an alias, and said so in its
    # own comment. It is now a real, stored, unique value; that comment has
    # been rewritten accordingly.
    #
    # `case_year` deliberately stays. It is DERIVED from this column's first
    # four digits when a case is created, which keeps uq_case_number_year,
    # the "1123/2024" display format used in a dozen places, and every
    # existing search path working unchanged.
    #
    # Declared `unique=True` to mirror the database, which enforces this
    # three ways: NOT NULL, uq_cases_automated_number, and a CHECK on the
    # nine-digit format (verified enforcing against the live server).
    automated_number: Mapped[str] = mapped_column(unique=True)
    case_year: Mapped[int] = mapped_column(SmallInteger)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"))
    category_ar: Mapped[str | None] = mapped_column(default=None)
    category_en: Mapped[str | None] = mapped_column(default=None)
    # --- case_type_id (Structured taxonomy alongside category_ar/en) ---
    # TEMPORARILY REMOVED as a real mapped column -- see the "PRE-MIGRATION
    # COMPATIBILITY" note below models.py's imports for the full
    # explanation. In short: SQLAlchemy always sends a value (NULL if
    # unset) for every mapped column on INSERT, and always selects every
    # mapped column on a plain entity load, REGARDLESS of `deferred=True`
    # or omitting `default=` -- there is no mapped_column configuration
    # that makes a column merely "optional" at the SQL level once the
    # class declares it. Since the live `cases` table genuinely does not
    # have this column yet (db/migration_procedural_intelligence.sql is
    # still unapplied by design), declaring it here at all broke, in
    # production: reading a case (SELECT), listing/counting cases
    # (Query.count() ignores `deferred` too), AND creating a new case
    # (INSERT) -- confirmed directly against the live database. Restore
    # this exactly as it was (see git history / the Phase 2 session) once
    # the migration has actually been applied:
    #
    #   case_type_id: Mapped[int | None] = mapped_column(
    #       ForeignKey("case_types.id", ondelete="SET NULL"), default=None
    #   )
    #   case_type: Mapped["CaseType | None"] = relationship()
    #
    # `procedures.py::_matching_rules` reads this via `getattr(case,
    # "case_type_id", None)` rather than `case.case_type_id` specifically
    # so it degrades to "no case-type scoping possible" instead of an
    # AttributeError while this is commented out -- that code path is
    # unreachable anyway pre-migration (its own tables don't exist), so
    # this has no live effect either way.
    parties_ar: Mapped[str]
    parties_en: Mapped[str | None] = mapped_column(default=None)
    civil_id: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(Enum("active", "closed"), default="active")
    stage: Mapped[str] = mapped_column(
        Enum("new", "prep", "pleading", "judgment", "execution", "closed"), default="new"
    )
    # --- procedural_status_id (finer-grained status, rolls up to `stage`) ---
    # TEMPORARILY REMOVED as a real mapped column, for exactly the same
    # reason as case_type_id above -- see that comment. `stage` itself is
    # untouched and keeps being read/written everywhere it already was.
    # Restore once the migration has landed:
    #
    #   procedural_status_id: Mapped[int | None] = mapped_column(
    #       ForeignKey("case_statuses.id", ondelete="SET NULL"), default=None
    #   )
    #   procedural_status: Mapped["CaseStatus | None"] = relationship()
    assigned_lawyer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    summary_ar: Mapped[str | None] = mapped_column(Text, default=None)
    summary_en: Mapped[str | None] = mapped_column(Text, default=None)
    next_hearing_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    # --- last_official_check_at ---
    # TEMPORARILY REMOVED as a real mapped column, for exactly the same
    # reason as case_type_id above. Restore once the migration has landed:
    #
    #   last_official_check_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), onupdate=datetime.utcnow
    )

    court: Mapped[Court] = relationship()
    assigned_lawyer: Mapped[User | None] = relationship()
    timeline: Mapped[list["CaseTimeline"]] = relationship(
        back_populates="case", order_by="CaseTimeline.sort_order", cascade="all, delete-orphan"
    )
    notes: Mapped[list["CaseNote"]] = relationship(
        back_populates="case", order_by="CaseNote.created_at.desc()", cascade="all, delete-orphan"
    )
    sessions: Mapped[list["CourtSession"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    experts: Mapped[list["Expert"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    executions: Mapped[list["ExecutionFile"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    watchers: Mapped[list["CaseWatcher"]] = relationship(back_populates="case", cascade="all, delete-orphan")
    reminders: Mapped[list["CaseReminder"]] = relationship(
        back_populates="case", cascade="all, delete-orphan", foreign_keys="CaseReminder.case_id"
    )
    procedures: Mapped[list["CaseProcedure"]] = relationship(
        back_populates="case", order_by="CaseProcedure.occurred_at", cascade="all, delete-orphan"
    )
    deadlines: Mapped[list["CaseDeadline"]] = relationship(back_populates="case", cascade="all, delete-orphan")


class CaseTimeline(Base):
    __tablename__ = "case_timeline"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    step_title_ar: Mapped[str]
    step_title_en: Mapped[str | None] = mapped_column(default=None)
    step_date: Mapped[datetime] = mapped_column(DateTime)
    is_done: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    case: Mapped[Case] = relationship(back_populates="timeline")


class CaseNote(Base):
    __tablename__ = "case_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    note_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="notes")
    author: Mapped[User] = relationship()


class CourtSession(Base):
    __tablename__ = "court_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    circuit_ar: Mapped[str]
    circuit_en: Mapped[str | None] = mapped_column(default=None)
    courtroom: Mapped[str | None] = mapped_column(default=None)
    session_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(
        Enum("scheduled", "done", "postponed", "cancelled"), default="scheduled"
    )
    outcome_notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="sessions")


class Expert(Base):
    __tablename__ = "experts"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    file_no: Mapped[str] = mapped_column(unique=True)
    expert_name: Mapped[str]
    specialty_ar: Mapped[str | None] = mapped_column(default=None)
    specialty_en: Mapped[str | None] = mapped_column(default=None)
    assigned_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Enum("scheduled", "in_progress", "completed"), default="scheduled")
    report_summary: Mapped[str | None] = mapped_column(Text, default=None)

    case: Mapped[Case] = relationship(back_populates="experts")


class ExecutionFile(Base):
    __tablename__ = "execution_files"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    file_no: Mapped[str] = mapped_column(unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    currency: Mapped[str] = mapped_column(default="KWD")
    status: Mapped[str] = mapped_column(Enum("in_progress", "closed", "suspended"), default="in_progress")
    last_action_ar: Mapped[str | None] = mapped_column(default=None)
    last_action_en: Mapped[str | None] = mapped_column(default=None)
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    case: Mapped[Case] = relationship(back_populates="executions")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    file_name: Mapped[str]
    file_type: Mapped[str]
    # --- doc_class_id (legal classification: pleading / judgment / power of
    # attorney / expert report / ...) ---
    # TEMPORARILY REMOVED as a real mapped column -- same reason as
    # Case.case_type_id (see that comment for the full explanation): no
    # mapped_column configuration (`deferred`, omitting `default=`) stops
    # SQLAlchemy from selecting/inserting a column that doesn't exist yet
    # on the live table, and this one doesn't exist on `documents` until
    # db/migration_procedural_intelligence.sql is applied. Confirmed
    # directly against production that declaring it broke both listing
    # documents and uploading a new one. Restore once the migration has
    # landed:
    #
    #   doc_class_id: Mapped[int | None] = mapped_column(
    #       ForeignKey("doc_classes.id", ondelete="SET NULL"), default=None
    #   )
    #   doc_class: Mapped["DocClass | None"] = relationship()
    file_size: Mapped[int]
    storage_path: Mapped[str]
    status: Mapped[str] = mapped_column(Enum("pending", "approved", "rejected"), default="pending")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="documents")
    uploader: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=None)
    target_role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), default=None
    )
    # 'deadline' is added, not substituted, for existing values -- used by
    # the deadlines UI to visually distinguish a procedural-deadline notice
    # from an ordinary hearing/task reminder; the underlying alert itself
    # still comes through as a 'reminder'-type Notification from the
    # existing escalation.py engine (see the CaseReminder.type comment
    # above) — this value is reserved for future direct use.
    type: Mapped[str] = mapped_column(Enum("hearing", "status", "document", "system", "reminder", "deadline"))
    message_ar: Mapped[str]
    message_en: Mapped[str | None] = mapped_column(default=None)
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class ImportedRecord(Base):
    __tablename__ = "imported_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(Enum("case", "session", "expert", "execution"))
    source_ref_id: Mapped[int]
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))


class CaseWatcher(Base):
    __tablename__ = "case_watchers"

    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(Enum("import", "manual"), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="watchers")
    user: Mapped[User] = relationship()


class CaseReminder(Base):
    __tablename__ = "case_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    # 'procedural_deadline' is added, not substituted, for existing values --
    # a reminder of this type is created by procedures.py from a confirmed
    # CaseDeadline and then rides the *existing* escalation.py 7/3/1 engine
    # unchanged (it filters on status='open', not on type).
    type: Mapped[str] = mapped_column(
        Enum("follow_up", "status_update_request", "procedural_deadline"), default="follow_up"
    )
    requested_stage: Mapped[str | None] = mapped_column(
        Enum("new", "prep", "pleading", "judgment", "execution", "closed"), default=None
    )
    due_at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str]
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assigned_to: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(Enum("open", "done", "dismissed"), default="open")
    escalation_level: Mapped[int] = mapped_column(default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="reminders", foreign_keys=[case_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    assignee: Mapped[User] = relationship(foreign_keys=[assigned_to])


class DocumentUploadGrant(Base):
    __tablename__ = "document_upload_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    client_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[str] = mapped_column(Enum("active", "used", "revoked", "expired"), default="active")

    case: Mapped[Case] = relationship()
    client: Mapped[User] = relationship(foreign_keys=[client_user_id])
    granter: Mapped[User] = relationship(foreign_keys=[granted_by])


class UserCaseLink(Base):
    """Explicit Admin-controlled link between a portal user (typically a
    Client) and a case, independent of the civil_id match on `cases.civil_id`.
    Supports many users per case and many cases per user. `can_upload` is a
    standing (non-expiring unless `can_upload_until` is set) upload
    permission, separate from the one-time `DocumentUploadGrant` window.
    """

    __tablename__ = "user_case_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    can_upload: Mapped[bool] = mapped_column(default=False)
    can_upload_until: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    linked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    linked_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    status: Mapped[str] = mapped_column(Enum("active", "revoked"), default="active")
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    case: Mapped[Case] = relationship()
    linker: Mapped["User | None"] = relationship(foreign_keys=[linked_by])
    revoker: Mapped["User | None"] = relationship(foreign_keys=[revoked_by])


# =========================================================================
# Procedural Intelligence
#   Current Status -> Latest Event -> Required Next Procedure ->
#   Responsible User -> Deadline -> Reminder/Notification -> Completion
#
# See db/migration_procedural_intelligence.sql for the DDL these map onto
# (that file is the source of truth for column types/constraints — this is
# a straight ORM mirror of it) and backend/app/procedures.py for the engine
# that reads/writes these tables. Every table below that asserts a fact
# rather than just naming a category carries `source_tier`, so the UI can
# always show whether something is verified-official, merely inferred,
# entered by firm staff, AI-suggested, or unverified — see Phase 1
# blueprint section 4.1. This principle is enforced by these columns
# existing at all, not by convention.
# =========================================================================

SOURCE_TIER = Enum("official_verified", "official_inferred", "firm_entered", "ai_suggested", "unverified")


class CaseType(Base):
    """Hierarchical case-type taxonomy (civil, commercial, labour, ...).

    Additive alongside `cases.category_ar/en`, which stays free text and
    unread by this feature — case_type_id is a nullable, independent
    column on Case (see above), so no existing case's category display
    changes because this table exists.
    """

    __tablename__ = "case_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("case_types.id", ondelete="SET NULL"), default=None)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    source_tier: Mapped[str] = mapped_column(SOURCE_TIER, default="unverified")
    is_enabled: Mapped[bool] = mapped_column(default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)

    parent: Mapped["CaseType | None"] = relationship(remote_side="CaseType.id")


class CourtCircuit(Base):
    """A circuit/chamber within a Court. Left unseeded by design — the
    current official circuit catalogue was not verifiable from an official
    source (Phase 1 blueprint 2.4) and must not be invented; firm staff
    populate this as real circuits are confirmed, e.g. from a case's own
    `court_sessions.circuit_ar/en` free text."""

    __tablename__ = "court_circuits"

    id: Mapped[int] = mapped_column(primary_key=True)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id", ondelete="CASCADE"))
    name_ar: Mapped[str]
    name_en: Mapped[str]
    source_tier: Mapped[str] = mapped_column(SOURCE_TIER, default="unverified")
    is_enabled: Mapped[bool] = mapped_column(default=True)

    court: Mapped[Court] = relationship()


class ProcedureType(Base):
    """Canonical procedural events (case_filed, judgment_issued,
    appeal_filed, ...) — the vocabulary every CaseProcedure and
    ProcedureRule speaks. Deliberately has no source_tier: these are
    category labels the firm defines for its own workflow, not assertions
    about Kuwaiti law (the law lives in ProcedureRule instead)."""

    __tablename__ = "procedure_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    is_terminal: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class CaseStatus(Base):
    """Fine-grained procedural status, each mapped to exactly one of the
    six existing `cases.stage` values so `stage` can always be derived from
    it — `stage` itself keeps being written directly wherever it already
    is; nothing here removes that."""

    __tablename__ = "case_statuses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    maps_to_stage: Mapped[str] = mapped_column(
        Enum("new", "prep", "pleading", "judgment", "execution", "closed")
    )
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=0)


class DocClass(Base):
    """Legal document classification (pleading, judgment, power of
    attorney, expert report, ...). `Document.doc_class_id`, which points
    here, is temporarily commented out on the Document class pending the
    Procedural Intelligence migration — see that class's comment."""

    __tablename__ = "doc_classes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]


class OfficialSource(Base):
    """A named official Kuwait channel (MOJ e-services, Sahel, Sahel
    Business, the MOJ site itself). `access_mode`/`requires_captcha` record,
    in the schema itself, *why* this application cannot automate a sync
    against it today (Phase 1 blueprint section 2.1) — 'api_authorised' is
    the seam a future authorised integration would flip on, with no schema
    change needed."""

    __tablename__ = "official_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    base_url: Mapped[str]
    access_mode: Mapped[str] = mapped_column(
        Enum("manual_authenticated", "api_authorised", "none"), default="manual_authenticated"
    )
    requires_captcha: Mapped[bool] = mapped_column(default=False)
    terms_url: Mapped[str | None] = mapped_column(default=None)
    is_enabled: Mapped[bool] = mapped_column(default=True)


class OfficialSourceCheck(Base):
    """One row per Assisted Manual Sync observation: a human lawyer/staff
    member opened the deep link to `source`, authenticated as themselves,
    looked, and recorded what they saw. Never written by any automated
    scraper or CAPTCHA-solving code — there is none in this application."""

    __tablename__ = "official_source_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    source_id: Mapped[int] = mapped_column(ForeignKey("official_sources.id"))
    checked_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))
    outcome: Mapped[str] = mapped_column(Enum("no_change", "change_recorded", "not_found", "blocked"))
    evidence_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    resulting_procedure_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_procedures.id", ondelete="SET NULL"), default=None
    )
    raw_note: Mapped[str | None] = mapped_column(Text, default=None)

    case: Mapped[Case] = relationship()
    source: Mapped[OfficialSource] = relationship()
    checker: Mapped[User] = relationship(foreign_keys=[checked_by])


class CaseProcedure(Base):
    """Append-only procedural event log — this table IS "Latest Event" in
    the requested chain. A correction never UPDATEs or DELETEs a past row;
    it inserts a new one with `supersedes_id` pointing at the row it
    corrects, so the audit history of what the firm believed and when is
    never lost."""

    __tablename__ = "case_procedures"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    procedure_type_id: Mapped[int] = mapped_column(ForeignKey("procedure_types.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    recorded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(
        Enum("firm_entered", "official_manual", "official_api", "migrated"), default="firm_entered"
    )
    source_tier: Mapped[str] = mapped_column(SOURCE_TIER, default="firm_entered")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    observed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    official_ref: Mapped[str | None] = mapped_column(default=None)
    evidence_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )
    notes_ar: Mapped[str | None] = mapped_column(Text, default=None)
    notes_en: Mapped[str | None] = mapped_column(Text, default=None)
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_procedures.id", ondelete="SET NULL"), default=None
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="procedures")
    procedure_type: Mapped[ProcedureType] = relationship()
    recorder: Mapped[User] = relationship(foreign_keys=[recorded_by])
    observer: Mapped["User | None"] = relationship(foreign_keys=[observed_by])
    deadlines_triggered: Mapped[list["CaseDeadline"]] = relationship(
        back_populates="triggered_by", foreign_keys="CaseDeadline.triggered_by_procedure_id"
    )


class ProcedureRule(Base):
    """The brain, as data, never as code: "when X just happened, Y is due
    in N days." Computes nothing until `is_enabled=1`, and may only become
    enabled together with `verified_by_user_id` + `verified_at` (enforced in
    routers/rules.py, not merely by this column existing) — enabling a rule
    asserts a legal fact and is audit-logged. See seed_procedure_rules.sql
    for why, e.g., the Cassation-appeal rule ships as two competing,
    equally-disabled candidates rather than a single guessed value."""

    __tablename__ = "procedure_rules"
    __table_args__ = (UniqueConstraint("code", "version", name="uq_pr_code_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str]
    version: Mapped[int] = mapped_column(SmallInteger, default=1)
    case_type_id: Mapped[int | None] = mapped_column(ForeignKey("case_types.id", ondelete="SET NULL"), default=None)
    court_level_code: Mapped[str | None] = mapped_column(
        Enum("cassation", "appeal", "first_instance", "misdemeanor", "family", "execution"), default=None
    )
    trigger_procedure_type_id: Mapped[int] = mapped_column(ForeignKey("procedure_types.id"))
    expected_procedure_type_id: Mapped[int] = mapped_column(ForeignKey("procedure_types.id"))
    deadline_days: Mapped[int] = mapped_column(SmallInteger)
    day_basis: Mapped[str] = mapped_column(Enum("calendar", "kuwait_business"), default="calendar")
    counts_from: Mapped[str] = mapped_column(
        Enum("occurrence", "notification", "judgment_date"), default="occurrence"
    )
    responsible_role_code: Mapped[str | None] = mapped_column(default=None)
    legal_basis_ar: Mapped[str | None] = mapped_column(default=None)
    legal_basis_en: Mapped[str | None] = mapped_column(default=None)
    legal_citation: Mapped[str | None] = mapped_column(default=None)
    source_url: Mapped[str | None] = mapped_column(default=None)
    source_tier: Mapped[str] = mapped_column(SOURCE_TIER, default="unverified")
    is_enabled: Mapped[bool] = mapped_column(default=False)
    verified_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    effective_from: Mapped[date | None] = mapped_column(Date, default=None)
    effective_to: Mapped[date | None] = mapped_column(Date, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case_type: Mapped["CaseType | None"] = relationship()
    trigger_procedure_type: Mapped[ProcedureType] = relationship(foreign_keys=[trigger_procedure_type_id])
    expected_procedure_type: Mapped[ProcedureType] = relationship(foreign_keys=[expected_procedure_type_id])
    verifier: Mapped["User | None"] = relationship(foreign_keys=[verified_by_user_id])


class CaseDeadline(Base):
    """A materialised deadline instance — this table IS "Deadline" in the
    requested chain. Keyed unique on (triggered_by_procedure_id, rule_id,
    rule_version) so re-running the engine over the same event against the
    same rule version never creates a duplicate (mirrors the existing
    escalation.py `_notify_once` idempotency contract). `confidence` is
    'confirmed' only when produced by an enabled, lawyer-verified rule;
    everything else is 'provisional' and excluded from hard escalation."""

    __tablename__ = "case_deadlines"
    __table_args__ = (
        UniqueConstraint("triggered_by_procedure_id", "rule_id", "rule_version", name="uq_cd_trigger_rule_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    triggered_by_procedure_id: Mapped[int] = mapped_column(ForeignKey("case_procedures.id", ondelete="CASCADE"))
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("procedure_rules.id", ondelete="SET NULL"), default=None)
    rule_version: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    deadline_type_code: Mapped[str] = mapped_column()
    due_at: Mapped[datetime] = mapped_column(DateTime)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    confidence: Mapped[str] = mapped_column(Enum("confirmed", "provisional"), default="provisional")
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    status: Mapped[str] = mapped_column(
        Enum("open", "met", "missed", "waived", "superseded"), default="open"
    )
    completed_by_procedure_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_procedures.id", ondelete="SET NULL"), default=None
    )
    reminder_id: Mapped[int | None] = mapped_column(ForeignKey("case_reminders.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"))

    case: Mapped[Case] = relationship(back_populates="deadlines")
    triggered_by: Mapped[CaseProcedure] = relationship(
        foreign_keys=[triggered_by_procedure_id], back_populates="deadlines_triggered"
    )
    rule: Mapped["ProcedureRule | None"] = relationship()
    responsible_user: Mapped["User | None"] = relationship(foreign_keys=[responsible_user_id])
    confirmer: Mapped["User | None"] = relationship(foreign_keys=[confirmed_by])
    reminder: Mapped["CaseReminder | None"] = relationship()
