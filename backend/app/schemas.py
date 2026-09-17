import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# The Automated Number's shape: a four-digit year followed by five digits.
# Mirrored in three other places on purpose -- the client input (maxlength
# and a matching regex in js/pages/cases.js), and the database's own
# ck_cases_automated_number_format CHECK. The client copy is UX, this one is
# the rule, and the database's is the backstop for any write that bypasses
# the API entirely (a manual INSERT, a restored dump, a script).
AUTOMATED_NUMBER_RE = re.compile(r"^\d{9}$")
# A case filed before the firm existed, or more than a year into the future,
# is a typo rather than a real filing -- `999900001` is a plausible slip and
# passes the regex above, but is not a year.
AUTOMATED_NUMBER_MIN_YEAR = 1970


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
    # Returned so a search result can show WHICH identifier matched, and so
    # the case-detail view can display it. `case_number`/`case_year` remain
    # the display identity ("1123/2024") everywhere they already were.
    automated_number: str
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
    automated_number: str
    # Optional on the wire, and never trusted when present: the server
    # re-derives it from automated_number's first four digits. See
    # `_derive_and_check_case_year` below.
    case_year: int | None = None
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

    @field_validator("automated_number")
    @classmethod
    def _check_automated_number(cls, v: str) -> str:
        """Format and plausibility, in that order.

        Whitespace is stripped rather than rejected: a number pasted from an
        email or a court PDF very often arrives with a trailing space, and
        failing that is a pointless obstacle. Everything else is rejected
        outright — there is no silent normalisation of digits, because
        guessing at what the user meant is how a case gets filed under the
        wrong identifier.
        """
        v = (v or "").strip()
        if not AUTOMATED_NUMBER_RE.match(v):
            raise ValueError(
                "Automated Number must be exactly 9 digits in the form YYYYNNNNN (e.g. 202400001)"
            )
        year = int(v[:4])
        max_year = datetime.utcnow().year + 1
        if not (AUTOMATED_NUMBER_MIN_YEAR <= year <= max_year):
            raise ValueError(
                f"Automated Number starts with '{year}', which is not a plausible filing year "
                f"({AUTOMATED_NUMBER_MIN_YEAR}-{max_year})"
            )
        return v

    @model_validator(mode="after")
    def _derive_and_check_case_year(self):
        """`case_year` is derived here, never taken from the client.

        The frontend shows the derived year back to the user as a read-only
        field and sends it along, but a value that arrives over HTTP is an
        assertion, not a fact: anything from a stale form to a hand-crafted
        request could carry a year that disagrees with the number it is
        supposed to come from. Since `case_year` is half of
        uq_case_number_year and is what the whole app displays as
        "1123/2024", letting the two drift apart would mean a case whose
        printed identity contradicts its own Automated Number.

        So the server recomputes it, and a mismatch is a 422 rather than a
        silent correction — if the client and server disagree about what
        case this is, that is worth surfacing, not papering over.
        """
        derived = int(self.automated_number[:4])
        if self.case_year is not None and self.case_year != derived:
            raise ValueError(
                f"case_year {self.case_year} does not match the Automated Number's year prefix ({derived})"
            )
        self.case_year = derived
        return self


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


# ---------------- Procedural Intelligence ----------------
# Current Status -> Latest Event -> Required Next Procedure ->
# Responsible User -> Deadline -> Reminder/Notification -> Completion


class CaseTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    parent_id: int | None
    code: str
    name_ar: str
    name_en: str
    source_tier: str
    is_enabled: bool


class ProcedureTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_ar: str
    name_en: str
    is_terminal: bool


class DocClassOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_ar: str
    name_en: str


class ProcedureRecordRequest(BaseModel):
    procedure_type_id: int
    occurred_at: datetime
    notes_ar: str | None = None
    notes_en: str | None = None
    official_ref: str | None = None
    evidence_document_id: int | None = None
    # Present only when this event is being recorded straight from an
    # Assisted Manual Sync observation (routers/official_sync.py) rather
    # than typed in directly — controls source/source_tier on the row.
    observed_official: bool = False


class CaseProcedureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    procedure_type_id: int
    procedure_code: str
    procedure_name_ar: str
    procedure_name_en: str
    occurred_at: datetime
    recorded_by: int
    recorded_by_name_ar: str
    recorded_by_name_en: str
    source: str
    source_tier: str
    observed_at: datetime | None
    observed_by: int | None
    official_ref: str | None
    evidence_document_id: int | None
    notes_ar: str | None
    notes_en: str | None
    supersedes_id: int | None
    created_at: datetime


class NextActionOut(BaseModel):
    """One candidate "what's due next" produced by procedures.next_actions() —
    NEVER a guess dressed up as fact: `confidence` and `source_tier` below
    tell the caller exactly how much legal weight this carries, and a case
    with no enabled matching rule simply returns an empty list rather than
    a fabricated entry."""
    rule_id: int | None
    rule_code: str | None
    expected_procedure_type_id: int
    expected_procedure_code: str
    expected_procedure_name_ar: str
    expected_procedure_name_en: str
    due_at: datetime
    confidence: str  # confirmed | provisional
    source_tier: str | None
    legal_citation: str | None
    legal_basis_ar: str | None
    legal_basis_en: str | None
    responsible_user_id: int | None


class CaseDeadlineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    case_number: str
    case_year: int
    triggered_by_procedure_id: int
    rule_id: int | None
    rule_code: str | None = None
    deadline_type_code: str
    due_at: datetime
    responsible_user_id: int | None
    responsible_user_name_ar: str | None = None
    responsible_user_name_en: str | None = None
    confidence: str
    confirmed_by: int | None
    confirmed_at: datetime | None
    status: str
    legal_citation: str | None = None
    created_at: datetime


class DeadlineConfirmRequest(BaseModel):
    due_at: datetime | None = None  # allows a lawyer to adjust the date while confirming


class DeadlineWaiveRequest(BaseModel):
    reason: str


class ProcedureRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    version: int
    case_type_id: int | None
    court_level_code: str | None
    trigger_procedure_type_id: int
    trigger_procedure_code: str
    expected_procedure_type_id: int
    expected_procedure_code: str
    deadline_days: int
    day_basis: str
    counts_from: str
    responsible_role_code: str | None
    legal_basis_ar: str | None
    legal_basis_en: str | None
    legal_citation: str | None
    source_url: str | None
    source_tier: str
    is_enabled: bool
    verified_by_user_id: int | None
    verified_by_name_ar: str | None = None
    verified_by_name_en: str | None = None
    verified_at: datetime | None
    effective_from: date | None
    effective_to: date | None
    notes: str | None


class ProcedureRuleVerifyRequest(BaseModel):
    """Enabling a rule asserts a legal fact — this is the one write this
    feature treats as consequential enough to require the caller to say so
    explicitly, not merely hold the permission for it."""
    confirm: bool
    notes: str | None = None


class OfficialSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_ar: str
    name_en: str
    base_url: str
    access_mode: str
    requires_captcha: bool
    terms_url: str | None
    is_enabled: bool


class OfficialSourceCheckRequest(BaseModel):
    source_id: int
    outcome: str  # no_change | change_recorded | not_found | blocked
    evidence_document_id: int | None = None
    raw_note: str | None = None
    # Only meaningful when outcome == 'change_recorded': records the
    # observed change as a real CaseProcedure row in the same call.
    new_procedure: ProcedureRecordRequest | None = None


class OfficialSourceCheckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    case_id: int
    source_id: int
    source_code: str
    checked_by: int
    checked_by_name_ar: str
    checked_by_name_en: str
    checked_at: datetime
    outcome: str
    evidence_document_id: int | None
    resulting_procedure_id: int | None
    raw_note: str | None
