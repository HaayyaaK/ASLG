from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from ..audit import log_activity
from ..database import get_db
from ..deps import get_permission_level, require_module, require_roles
from ..escalation import notify_task_assigned
from ..kuwait_time import kuwait_day_utc_range, parse_kuwait_date
from ..models import Case, CaseReminder, CaseWatcher, Court, Document, Expert, ExecutionFile, ImportedRecord, CourtSession, Role, User
from ..schemas import (
    AssignableUserOut,
    CaseOut,
    DocumentOut,
    ExecutionOut,
    ExpertOut,
    ImportRecordRequest,
    SearchRequestUpdateRequest,
    SessionOut,
    TrackedCaseOut,
)

router = APIRouter(prefix="/api/search", tags=["search"])

# Who a status-update request may be assigned to — same roster the reminders
# module already uses, so there is one definition of "staff" in the app.
STAFF_ROLES = ("Admin", "Lawyer", "consultant", "delegate")



def _case_ctx(case: Case) -> dict:
    """Case context for a related record's search result.

    Read live from the record's own `case` relationship (the case_id foreign
    key), so a result can never disagree with the case page: change a case's
    stage and the very next search reflects it, because nothing is cached or
    copied.
    """
    return {
        "case_stage": case.stage,
        "case_status": case.status,
        "case_parties_ar": case.parties_ar,
        "case_parties_en": case.parties_en,
        "case_court_ar": case.court.name_ar,
        "case_court_en": case.court.name_en,
    }


def _cases_scope(db: Session, user: User):
    """Cases this user may see through search.

    Defence in depth: search must never become a way around the Cases
    module's own visibility rule. Today no role has cases="own" together with
    search access (clients have search="none"), so this changes nothing in
    practice — but if a future role were granted search, it would otherwise
    have silently exposed every case in the firm.
    """
    from ..deps import get_permission_level

    if get_permission_level(db, user.role_id, "search") == "none":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to the search engine")

    q = db.query(Case)
    if get_permission_level(db, user.role_id, "cases") == "own":
        if not user.civil_id:
            return q.filter(False)
        q = q.filter(Case.civil_id == user.civil_id)
    return q


def _case_to_out(c: Case) -> CaseOut:
    return CaseOut(
        id=c.id, case_number=c.case_number, automated_number=c.automated_number,
        case_year=c.case_year,
        court_name_ar=c.court.name_ar, court_name_en=c.court.name_en,
        category_ar=c.category_ar, category_en=c.category_en,
        parties_ar=c.parties_ar, parties_en=c.parties_en, civil_id=c.civil_id,
        status=c.status, stage=c.stage, assigned_lawyer_id=c.assigned_lawyer_id,
        assigned_lawyer_name_ar=c.assigned_lawyer.name_ar if c.assigned_lawyer else None,
        assigned_lawyer_name_en=c.assigned_lawyer.name_en if c.assigned_lawyer else None,
        summary_ar=c.summary_ar, summary_en=c.summary_en, next_hearing_at=c.next_hearing_at,
        created_at=c.created_at,
    )


@router.get("/case-number", response_model=list[CaseOut])
def search_case_number(
    court_level: str | None = None,
    case_number: str | None = None,
    automated_number: str | None = None,
    case_year: str | None = None,
    party: str | None = None,
    user: User = Depends(require_module("search")),
    db: Session = Depends(get_db),
):
    q = _cases_scope(db, user).options(joinedload(Case.court), joinedload(Case.assigned_lawyer))
    if court_level:
        q = q.join(Court).filter(Court.level_code == court_level)
    # "Automated Number" now has its own column (db/migration_automated_case_
    # number.sql). It previously did not, and this filter matched it against
    # `case_number` as an alias — which meant searching by Automated Number
    # could only ever find a case whose SHORT number happened to contain the
    # same digits, i.e. almost never. It now matches the real column.
    #
    # Given together with Case Number, either one matching is still enough
    # (OR): a caller who supplies both is trying two ways to find the same
    # case, not narrowing to one that satisfies both.
    if case_number and automated_number:
        q = q.filter(
            or_(
                Case.case_number.contains(case_number),
                Case.automated_number.contains(automated_number),
            )
        )
    elif case_number:
        q = q.filter(Case.case_number.contains(case_number))
    elif automated_number:
        q = q.filter(Case.automated_number.contains(automated_number))
    if case_year:
        q = q.filter(Case.case_year == int(case_year))
    if party:
        like = f"%{party}%"
        q = q.filter(or_(Case.parties_ar.like(like), Case.parties_en.like(like), Case.civil_id.like(like)))

    rows = q.all()
    if case_number or automated_number:
        # Partial matching stays (searching "112" should still find 1123/2024),
        # but an exact hit is what the user almost always meant, so it is
        # never buried under longer numbers that merely contain it.
        #
        # Each term is compared against ITS OWN column. This used to be a
        # single `exact_target = case_number or automated_number` tested
        # against `case_number`, which was fine while Automated Number was
        # an alias for that same column — but once they became separate
        # columns, an Automated Number search would compare "202401123"
        # against case_number "1123", never match, and silently lose the
        # exact-match boost entirely.
        def _rank(c):
            exact = (case_number and c.case_number == case_number) or (
                automated_number and c.automated_number == automated_number
            )
            return (not exact, c.case_number, -c.case_year)

        rows.sort(key=_rank)
    else:
        rows.sort(key=lambda c: (c.case_number, -c.case_year))
    return [_case_to_out(c) for c in rows]


@router.get("/sessions", response_model=list[SessionOut])
def search_sessions(
    circuit: str | None = None,
    session_date: str | None = None,
    case_number: str | None = None,
    user: User = Depends(require_module("search")),
    db: Session = Depends(get_db),
):
    q = db.query(CourtSession).join(Case).options(joinedload(CourtSession.case).joinedload(Case.court))
    if circuit:
        like = f"%{circuit}%"
        q = q.filter(or_(CourtSession.circuit_ar.like(like), CourtSession.circuit_en.like(like)))
    if session_date:
        # The user types a Kuwait calendar date, but session_at is stored as
        # naive UTC — a LIKE 'YYYY-MM-DD%' prefix match therefore matched the
        # UTC day, so a hearing at 01:00 Kuwait was filed under the previous
        # date and a search for its real date missed it. Match the half-open
        # UTC window covering that Kuwait day instead. An unparseable value
        # leaves the filter off rather than 500-ing on a stray query string.
        day = parse_kuwait_date(session_date)
        if day is not None:
            day_start, day_end = kuwait_day_utc_range(day)
            q = q.filter(CourtSession.session_at >= day_start, CourtSession.session_at < day_end)
    if case_number:
        q = q.filter(Case.case_number.contains(case_number))
    return [
        SessionOut(
            id=s.id, case_id=s.case_id, case_number=s.case.case_number, case_year=s.case.case_year,
            circuit_ar=s.circuit_ar, circuit_en=s.circuit_en, courtroom=s.courtroom,
            session_at=s.session_at, status=s.status, **_case_ctx(s.case),
        )
        for s in q.order_by(CourtSession.session_at.desc()).all()
    ]


@router.get("/experts", response_model=list[ExpertOut])
def search_experts(
    file_no: str | None = None,
    expert_name: str | None = None,
    case_number: str | None = None,
    user: User = Depends(require_module("search")),
    db: Session = Depends(get_db),
):
    q = db.query(Expert).join(Case).options(joinedload(Expert.case).joinedload(Case.court))
    if file_no:
        q = q.filter(Expert.file_no.contains(file_no))
    if expert_name:
        q = q.filter(Expert.expert_name.contains(expert_name))
    if case_number:
        q = q.filter(Case.case_number.contains(case_number))
    return [
        ExpertOut(
            id=e.id, case_id=e.case_id, case_number=e.case.case_number, case_year=e.case.case_year,
            file_no=e.file_no, expert_name=e.expert_name, specialty_ar=e.specialty_ar,
            specialty_en=e.specialty_en, status=e.status, **_case_ctx(e.case),
        )
        for e in q.all()
    ]


@router.get("/execution", response_model=list[ExecutionOut])
def search_execution(
    file_no: str | None = None,
    case_number: str | None = None,
    exec_status: str | None = Query(None, alias="status"),
    user: User = Depends(require_module("search")),
    db: Session = Depends(get_db),
):
    q = db.query(ExecutionFile).join(Case).options(joinedload(ExecutionFile.case).joinedload(Case.court))
    if file_no:
        q = q.filter(ExecutionFile.file_no.contains(file_no))
    if case_number:
        q = q.filter(Case.case_number.contains(case_number))
    if exec_status:
        q = q.filter(ExecutionFile.status == exec_status)
    return [
        ExecutionOut(
            id=x.id, case_id=x.case_id, case_number=x.case.case_number, case_year=x.case.case_year,
            file_no=x.file_no, amount=x.amount, currency=x.currency, status=x.status,
            last_action_ar=x.last_action_ar, last_action_en=x.last_action_en, **_case_ctx(x.case),
        )
        for x in q.all()
    ]


@router.get("/internal")
def search_internal(
    q: str = Query(..., min_length=1),
    user: User = Depends(require_module("search")),
    db: Session = Depends(get_db),
):
    like = f"%{q}%"
    cases = (
        _cases_scope(db, user)
        .options(joinedload(Case.court), joinedload(Case.assigned_lawyer))
        .filter(
            or_(
                Case.case_number.contains(q),
                Case.parties_ar.like(like),
                Case.parties_en.like(like),
                Case.summary_ar.like(like),
                Case.summary_en.like(like),
            )
        )
        .all()
    )
    visible_case_ids = {c.id for c in cases} or None
    doc_q = db.query(Document).options(joinedload(Document.case)).filter(Document.file_name.like(like))
    # A document is only ever shown through a case the user may already see —
    # the file name alone must not become a side channel to another case.
    if get_permission_level(db, user.role_id, "cases") == "own":
        doc_q = doc_q.join(Case).filter(Case.civil_id == user.civil_id) if user.civil_id else doc_q.filter(False)
    docs = doc_q.all()
    return {
        "cases": [_case_to_out(c) for c in cases],
        "documents": [
            DocumentOut(
                id=d.id, case_id=d.case_id, case_number=f"{d.case.case_number}/{d.case.case_year}", file_name=d.file_name,
                file_type=d.file_type, file_size=d.file_size, status=d.status, uploaded_by=d.uploaded_by,
                uploaded_by_name_ar=d.uploader.name_ar, uploaded_by_name_en=d.uploader.name_en, uploaded_at=d.uploaded_at,
            )
            for d in docs
        ],
    }


SOURCE_MODELS = {"case": Case, "session": CourtSession, "expert": Expert, "execution": ExecutionFile}


def _as_naive_utc(value: datetime) -> datetime:
    """Normalise an incoming datetime to naive UTC.

    The browser sends `new Date(...).toISOString()`, which ends in "Z" and so
    parses as timezone-aware, while every datetime stored and compared in this
    app is naive UTC (see database.py, which pins the MySQL session to +00:00).
    Mixing the two raises "can't compare offset-naive and offset-aware
    datetimes", so aware values are converted rather than rejected — the client
    is not doing anything wrong by sending a correct ISO timestamp.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _resolve_case_id(db: Session, source_type: str, source_ref_id: int) -> int:
    """Every trackable search result ultimately hangs off a case — a hearing,
    an expert assignment and an execution file all carry case_id. Tracking
    resolves to that case, which is the thing a lawyer actually follows."""
    model = SOURCE_MODELS.get(source_type)
    if model is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown source_type")
    record = db.get(model, source_ref_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Record not found")
    case_id = record.id if source_type == "case" else getattr(record, "case_id", None)
    if case_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This record is not linked to a case")
    return case_id


@router.post("/import", status_code=status.HTTP_201_CREATED)
def import_record(payload: ImportRecordRequest, user: User = Depends(require_module("search")), db: Session = Depends(get_db)):
    """Track ("pin") a search result.

    This used to write an `imported_records` row plus a `case_watchers` row and
    return `{"imported": true}` — but nothing in the application ever read
    `imported_records`, and the watcher flag was only visible as a bookmark
    deep inside the case-detail modal. So the button appeared to do nothing:
    the item showed up in no list, no notification, and nowhere under Reminders
    & Follow-ups. The storage was fine; the surfacing was missing.

    The write is unchanged (still an audit trail of what was imported), but the
    response now returns the resolved case so the caller can reflect the
    tracked state immediately, and GET /tracked below finally exposes the list.
    """
    case_id = _resolve_case_id(db, payload.source_type, payload.source_ref_id)

    db.add(ImportedRecord(source_type=payload.source_type, source_ref_id=payload.source_ref_id, imported_by=user.id))

    already_tracked = db.get(CaseWatcher, (case_id, user.id)) is not None
    if payload.watch and not already_tracked:
        db.add(CaseWatcher(case_id=case_id, user_id=user.id, source="import"))

    db.commit()

    # Logged after the commit — the 404/400 paths in _resolve_case_id above
    # raise before anything is written, so a rejected request never records a
    # successful track. Unlike watch/unwatch this DOES record every successful
    # call rather than only state changes, because every call really does
    # write an `imported_records` row; `already_tracked` in the meta makes a
    # repeat press self-evident rather than hiding it.
    case = db.get(Case, case_id)
    log_activity(
        db, user.id, "case_track", entity_type="case", entity_id=case_id,
        meta={
            "case": f"{case.case_number}/{case.case_year}" if case else None,
            "source_type": payload.source_type,
            "source_ref_id": payload.source_ref_id,
            "already_tracked": already_tracked,
        },
    )
    return {"imported": True, "case_id": case_id, "already_tracked": already_tracked}


@router.delete("/track/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def untrack_case(case_id: int, user: User = Depends(require_module("search")), db: Session = Depends(get_db)):
    """Lets a mis-click be undone — previously there was no way to stop
    tracking something imported from search."""
    watcher = db.get(CaseWatcher, (case_id, user.id))
    # Only a tracking entry that actually existed and was removed is recorded,
    # so repeating the call is silent rather than filling the log with
    # untracks that untracked nothing.
    if watcher is not None:
        source = watcher.source
        db.delete(watcher)
        db.commit()
        case = db.get(Case, case_id)
        log_activity(
            db, user.id, "case_untrack", entity_type="case", entity_id=case_id,
            meta={
                "case": f"{case.case_number}/{case.case_year}" if case else None,
                "was_added_by": source,
            },
        )


@router.get("/tracked", response_model=list[TrackedCaseOut])
def list_tracked(user: User = Depends(require_module("search")), db: Session = Depends(get_db)):
    """The list that "Import to Tracking List" always implied existed but
    never had. Powers both the tracked-state badge on search results and the
    Tracked tab."""
    rows = (
        db.query(CaseWatcher)
        .options(joinedload(CaseWatcher.case))
        .filter(CaseWatcher.user_id == user.id)
        .order_by(CaseWatcher.created_at.desc())
        .all()
    )
    return [
        TrackedCaseOut(
            case_id=w.case_id, case_number=w.case.case_number, case_year=w.case.case_year,
            parties_ar=w.case.parties_ar, parties_en=w.case.parties_en, stage=w.case.stage,
            next_hearing_at=w.case.next_hearing_at, source=w.source,
        )
        for w in rows
        if w.case is not None
    ]


@router.get("/assignable-staff", response_model=list[AssignableUserOut])
def list_assignable_staff(user: User = Depends(require_roles("Admin", "Lawyer")), db: Session = Depends(get_db)):
    """Staff roster for the "Request Update" picker.

    Deliberately separate from /api/reminders/assignable-users, which is
    restricted to firm owners: a non-owner Lawyer must still be able to ask a
    delegate for an update on their own case, which is the whole point of this
    feature.
    """
    rows = (
        db.query(User)
        .join(Role)
        .filter(Role.code.in_(STAFF_ROLES), User.is_active == True)  # noqa: E712
        .order_by(User.name_en)
        .all()
    )
    return [AssignableUserOut(id=u.id, name_ar=u.name_ar, name_en=u.name_en, role_code=u.role.code) for u in rows]


@router.post("/request-update", status_code=status.HTTP_201_CREATED)
def request_update(
    payload: SearchRequestUpdateRequest,
    user: User = Depends(require_roles("Admin", "Lawyer")),
    db: Session = Depends(get_db),
):
    """Ask a named colleague for a status update on a search result.

    Restricted to Admin and Lawyer at the API level, not merely in the UI —
    this hands work to another person, which ordinary users and delegates have
    no business doing.

    Reuses the existing CaseReminder model rather than inventing a parallel
    task system, so the request lands in Reminders & Follow-ups exactly like
    every other task, participates in the same pre-due notification layers, and
    gets chased by the same smart-nudge logic if it goes unanswered.

    It deliberately does NOT touch case.stage or the case timeline: asking
    someone for an update is not itself legal progress.
    """
    case_id = _resolve_case_id(db, payload.source_type, payload.source_ref_id)
    case = db.get(Case, case_id)

    assignee = db.get(User, payload.assigned_to)
    if assignee is None or not assignee.is_active or assignee.role.code not in STAFF_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Please choose an active staff member to ask")

    due_at = _as_naive_utc(payload.due_at)
    if due_at <= datetime.utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The due date must be in the future")

    case_label = f"{case.case_number}/{case.case_year}"
    note = (payload.message or "").strip() or f"Status update requested for case {case_label}"

    reminder = CaseReminder(
        case_id=case_id,
        type="status_update_request",
        requested_stage=None,  # asking for an update never pre-decides the new stage
        due_at=due_at,
        note=note,
        created_by=user.id,
        assigned_to=payload.assigned_to,
    )
    db.add(reminder)

    if payload.also_track and db.get(CaseWatcher, (case_id, user.id)) is None:
        db.add(CaseWatcher(case_id=case_id, user_id=user.id, source="import"))

    db.commit()
    db.refresh(reminder)

    notify_task_assigned(db, reminder, user.name_en)
    log_activity(
        db, user.id, "status_update_requested", entity_type="case", entity_id=case_id,
        meta={"assigned_to": payload.assigned_to, "source_type": payload.source_type},
    )
    return {"created": True, "reminder_id": reminder.id, "case_id": case_id}
