from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    name_ar: Mapped[str]
    name_en: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP", onupdate=datetime.utcnow
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

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
    case_year: Mapped[int] = mapped_column(SmallInteger)
    court_id: Mapped[int] = mapped_column(ForeignKey("courts.id"))
    category_ar: Mapped[str | None] = mapped_column(default=None)
    category_en: Mapped[str | None] = mapped_column(default=None)
    parties_ar: Mapped[str]
    parties_en: Mapped[str | None] = mapped_column(default=None)
    civil_id: Mapped[str | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(Enum("active", "closed"), default="active")
    stage: Mapped[str] = mapped_column(
        Enum("new", "prep", "pleading", "judgment", "execution", "closed"), default="new"
    )
    assigned_lawyer_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    summary_ar: Mapped[str | None] = mapped_column(Text, default=None)
    summary_en: Mapped[str | None] = mapped_column(Text, default=None)
    next_hearing_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP", onupdate=datetime.utcnow
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

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
    file_size: Mapped[int]
    storage_path: Mapped[str]
    status: Mapped[str] = mapped_column(Enum("pending", "approved", "rejected"), default="pending")
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

    case: Mapped[Case] = relationship(back_populates="documents")
    uploader: Mapped[User] = relationship()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), default=None)
    target_role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), default=None
    )
    type: Mapped[str] = mapped_column(Enum("hearing", "status", "document", "system", "reminder"))
    message_ar: Mapped[str]
    message_en: Mapped[str | None] = mapped_column(default=None)
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")


class ImportedRecord(Base):
    __tablename__ = "imported_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(Enum("case", "session", "expert", "execution"))
    source_ref_id: Mapped[int]
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")


class CaseWatcher(Base):
    __tablename__ = "case_watchers"

    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    source: Mapped[str] = mapped_column(Enum("import", "manual"), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

    case: Mapped[Case] = relationship(back_populates="watchers")
    user: Mapped[User] = relationship()


class CaseReminder(Base):
    __tablename__ = "case_reminders"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Enum("follow_up", "status_update_request"), default="follow_up")
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
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")

    case: Mapped[Case] = relationship(back_populates="reminders", foreign_keys=[case_id])
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    assignee: Mapped[User] = relationship(foreign_keys=[assigned_to])


class DocumentUploadGrant(Base):
    __tablename__ = "document_upload_grants"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    client_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    granted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")
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
    linked_at: Mapped[datetime] = mapped_column(DateTime, server_default="CURRENT_TIMESTAMP")
    status: Mapped[str] = mapped_column(Enum("active", "revoked"), default="active")
    revoked_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)

    user: Mapped[User] = relationship(foreign_keys=[user_id])
    case: Mapped[Case] = relationship()
    linker: Mapped["User | None"] = relationship(foreign_keys=[linked_by])
    revoker: Mapped["User | None"] = relationship(foreign_keys=[revoked_by])
