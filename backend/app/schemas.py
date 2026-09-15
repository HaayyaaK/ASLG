from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name_en: str
    name_ar: str
    username: str
    email: str | None = None
    occupation: str | None = None
    role_code: str
    civil_id: str | None = None
    is_owner: bool = False
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class AssignableUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name_ar: str
    name_en: str
    role_code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
    permissions: dict[str, str]


class UserCreateRequest(BaseModel):
    name_en: str
    name_ar: str
    username: str
    email: str | None = None
    occupation: str | None = None
    role_code: str
    civil_id: str | None = None
    is_owner: bool = False
    password: str


class UserUpdateRequest(BaseModel):
    name_en: str | None = None
    name_ar: str | None = None
    email: str | None = None
    occupation: str | None = None
    role_code: str | None = None
    civil_id: str | None = None
    is_owner: bool | None = None
    is_active: bool | None = None


class PasswordResetRequest(BaseModel):
    new_password: str


class BulkUserActionRequest(BaseModel):
    user_ids: list[int]
    action: str  # "activate" | "deactivate" | "reset_password"
    new_password: str | None = None


# ---------------- Cases ----------------


class CaseTimelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    step_title_ar: str
    step_title_en: str | None
    step_date: datetime
    is_done: bool


class CaseNoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    author_id: int
    author_name_ar: str
    author_name_en: str
    note_text: str
    created_at: datetime


class CaseNoteCreateRequest(BaseModel):
    note_text: str


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_number: str
    case_year: int
    court_name_ar: str
    court_name_en: str
    category_ar: str | None
    category_en: str | None
    parties_ar: str
    parties_en: str | None
    civil_id: str | None
    status: str
    stage: str
    assigned_lawyer_id: int | None
    assigned_lawyer_name_ar: str | None = None
    assigned_lawyer_name_en: str | None = None
    summary_ar: str | None
    summary_en: str | None
    next_hearing_at: datetime | None
    is_watching: bool = False


class CaseDetailOut(CaseOut):
    timeline: list[CaseTimelineOut] = []
    notes: list[CaseNoteOut] = []


class CaseStageUpdateRequest(BaseModel):
    stage: str


class CaseCreateRequest(BaseModel):
    case_number: str
    case_year: int
    court_id: int
    category_ar: str | None = None
    category_en: str | None = None
    parties_ar: str
    parties_en: str | None = None
    civil_id: str | None = None
    assigned_lawyer_id: int | None = None
    summary_ar: str | None = None
    summary_en: str | None = None
    stage: str = "new"
    next_hearing_at: datetime | None = None


class CourtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    level_code: str
    name_ar: str
    name_en: str


# ---------------- Search ----------------


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    case_year: int
    circuit_ar: str
    circuit_en: str | None
    courtroom: str | None
    session_at: datetime
    status: str
    # --- Case context, resolved through the record's own case_id foreign key
    # (court_sessions/experts/execution_files -> cases.id). Carrying it on the
    # result means a search hit always shows WHICH case it belongs to and that
    # case's CURRENT state, instead of a bare number the user must go and look
    # up — and because it is read live from the related row, it can never show
    # a stale stage after someone updates the case.
    case_stage: str
    case_status: str
    case_parties_ar: str
    case_parties_en: str | None
    case_court_ar: str
    case_court_en: str


class ExpertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    case_year: int
    file_no: str
    expert_name: str
    specialty_ar: str | None
    specialty_en: str | None
    status: str
    # --- Case context, resolved through the record's own case_id foreign key
    # (court_sessions/experts/execution_files -> cases.id). Carrying it on the
    # result means a search hit always shows WHICH case it belongs to and that
    # case's CURRENT state, instead of a bare number the user must go and look
    # up — and because it is read live from the related row, it can never show
    # a stale stage after someone updates the case.
    case_stage: str
    case_status: str
    case_parties_ar: str
    case_parties_en: str | None
    case_court_ar: str
    case_court_en: str


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    case_year: int
    file_no: str
    amount: Decimal
    currency: str
    status: str
    last_action_ar: str | None
    last_action_en: str | None
    # --- Case context, resolved through the record's own case_id foreign key
    # (court_sessions/experts/execution_files -> cases.id). Carrying it on the
    # result means a search hit always shows WHICH case it belongs to and that
    # case's CURRENT state, instead of a bare number the user must go and look
    # up — and because it is read live from the related row, it can never show
    # a stale stage after someone updates the case.
    case_stage: str
    case_status: str
    case_parties_ar: str
    case_parties_en: str | None
    case_court_ar: str
    case_court_en: str


class ImportRecordRequest(BaseModel):
    source_type: str  # case | session | expert | execution
    source_ref_id: int
    watch: bool = True


class TrackedCaseOut(BaseModel):
    """A case the current user is tracking, surfaced so the search results can
    show a real "already tracked" state instead of silently writing a row
    nobody ever sees."""
    case_id: int
    case_number: str
    case_year: int
    parties_ar: str
    parties_en: str | None
    stage: str
    next_hearing_at: datetime | None
    source: str


class SearchRequestUpdateRequest(BaseModel):
    """Admin/Lawyer "Request Update" on a search result: creates a real task in
    Reminders & Follow-ups and notifies the person it is assigned to."""
    source_type: str  # case | session | expert | execution
    source_ref_id: int
    assigned_to: int
    due_at: datetime
    message: str | None = None
    also_track: bool = True


# ---------------- Documents ----------------


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str | None = None
    file_name: str
    file_type: str
    file_size: int
    status: str
    uploaded_by: int
    uploaded_by_name_ar: str
    uploaded_by_name_en: str
    uploaded_at: datetime


class DocumentReviewRequest(BaseModel):
    """Approve or reject an uploaded document.

    `documents.status` has always been an ENUM of pending|approved|rejected and
    the UI has always rendered a status badge on every row (Arabic literally
    reads "awaiting review"), but nothing could ever move a document out of
    'pending' — so the Dashboard's "Pending Documents" counter could only ever
    grow. This request completes that half-built workflow.

    `reason` is optional free text kept for the audit trail and the uploader's
    notification. It is deliberately NOT persisted on the document row: the
    application database account holds no DDL privilege, so no column can be
    added, and inventing a place to hide it would be worse than recording it
    where an admin can actually find it (the Activity Log).
    """
    status: str  # approved | rejected
    reason: str | None = None


# ---------------- Notifications ----------------


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    message_ar: str
    message_en: str | None
    is_read: bool
    created_at: datetime


# ---------------- Reminders ----------------


class ReminderCreateRequest(BaseModel):
    case_id: int
    type: str = "follow_up"
    requested_stage: str | None = None
    due_at: datetime
    note: str
    assigned_to: int


class ReminderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    type: str
    requested_stage: str | None
    due_at: datetime
    note: str
    created_by: int
    created_by_name_ar: str
    created_by_name_en: str
    assigned_to: int
    assigned_to_name_ar: str
    assigned_to_name_en: str
    status: str
    escalation_level: int
    resolved_at: datetime | None
    created_at: datetime


class ReminderResolveRequest(BaseModel):
    status: str  # done | dismissed


# ---------------- Document Upload Grants ----------------


class GrantUploadRequest(BaseModel):
    case_id: int
    duration_minutes: int = 60


class UploadGrantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    client_user_id: int
    client_name_ar: str
    client_name_en: str
    granted_by: int
    granted_by_name_ar: str
    granted_by_name_en: str
    granted_at: datetime
    # None for a standing (source="link") permission, which has no expiry
    # unless a future can_upload_until is set — only a one-time
    # (source="grant") window is guaranteed to expire.
    expires_at: datetime | None
    used_at: datetime | None
    status: str
    # "grant" = the existing one-time DocumentUploadGrant window;
    # "link" = a standing UserCaseLink.can_upload permission. The client UI
    # renders these two sources with different, honest labels ("temporary
    # until X" vs. "standing access") rather than pretending they're the same.
    source: str = "grant"


class LinkUserRequest(BaseModel):
    user_id: int
    can_upload: bool = False


class UserCaseLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    user_id: int
    user_name_ar: str
    user_name_en: str
    can_upload: bool
    can_upload_until: datetime | None
    linked_by: int | None
    linked_by_name_ar: str | None
    linked_by_name_en: str | None
    linked_at: datetime
    status: str
    revoked_by: int | None
    revoked_by_name_ar: str | None
    revoked_by_name_en: str | None
    revoked_at: datetime | None


# ---------------- Dashboard ----------------


class DashboardStats(BaseModel):
    active_cases: int
    today_hearings: int
    pending_documents: int
    unread_notifications: int


class DashboardTaskStats(BaseModel):
    my_open_tasks: int
    overdue_tasks: int
    pending_status_requests: int
    tasks_i_assigned: int


class UpcomingHearingOut(BaseModel):
    case_id: int
    case_number: str
    case_year: int
    parties_ar: str
    parties_en: str | None
    circuit_ar: str
    circuit_en: str | None
    session_at: datetime


# ---------------- Activity / audit log (Admin only) ----------------


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int | None
    user_name_ar: str | None = None
    user_name_en: str | None = None
    action: str
    entity_type: str | None
    entity_id: int | None
    meta: dict | None = None
    ip_address: str | None
    created_at: datetime


# ---------------- System maintenance (Admin only) ----------------


class DatabaseResetRequest(BaseModel):
    confirm_phrase: str
