"""Proactive notification engine — pre-date alerts, never overdue-first.

THE BUSINESS RULE THIS ENFORCES
-------------------------------
In a real legal office an overdue-first notification is worthless: by the time
you are told, the hearing has already happened. So every dated event in this
system gets THREE notification layers and **all three land before the date**:

    Layer 1 — Early notice      (plan ahead)
    Layer 2 — Action required   (prepare now)
    Layer 3 — Final alert       (last chance)

The previous version of this module did the exact opposite — it fired at
due+0, due+1day and due+3days, i.e. all three layers only ever arrived *after*
the deadline had already been missed. That is the behaviour this rewrite
replaces.

WHAT GETS WATCHED
-----------------
1. Court hearings   (`court_sessions.session_at`, status='scheduled')
2. Task deadlines   (`case_reminders.due_at`, status='open')

Each is a genuinely different kind of date and is treated as such: a hearing is
a fixed external court appointment (miss it and the case suffers), a task
deadline is an internal commitment (miss it and a colleague is blocked).

SMART ASSIGNMENT NUDGE
----------------------
Separately from the date layers, a task that has been sitting open with no
response from its assignee gets an automatic, clearly system-labelled nudge to
the assignee, plus an FYI to whoever assigned it. These use notification
type='system' so the UI can render them distinctly from human-sent messages —
the recipient must never think a colleague personally chased them.

NO SCHEMA CHANGES
-----------------
The database account this app runs as (`aslg_app`) holds only
SELECT/INSERT/UPDATE/DELETE on its own schema — no CREATE/ALTER/DROP. So this
engine adds no tables and no columns. De-duplication is achieved by making
every generated message a pure function of (event, layer) — nothing that
varies with "now" appears in the text — and checking for that exact message
before inserting it. `_notify_once()` is therefore safe to call repeatedly,
which matters because this whole engine runs on-demand on every dashboard /
reminders / notifications request (there is no scheduler in this app).
"""

from datetime import datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from .kuwait_time import is_kuwait_weekend
from .models import Case, CaseReminder, CourtSession, Notification

# Layer offsets, in days before the event, when there is comfortable notice.
STANDARD_OFFSETS_DAYS = (7, 3, 1)

# Below this much total notice, the three layers are compressed proportionally
# (see _layer_moments) so that all three still fire before the date.
COMFORTABLE_NOTICE_DAYS = 10

# Only look this far ahead for hearings — keeps the per-request cost tiny and
# avoids emailing people about something four months out.
HEARING_HORIZON_DAYS = 30

# The firm's weekend is defined once, in kuwait_time. An alert moment landing
# on it is pulled EARLIER to the preceding working day — never later, since
# later could cross the event date. Friday is the only weekend day; Saturday is
# a working day. Evaluated against the Kuwait wall clock (see
# _shift_off_weekend), not the stored UTC value.

# Minimum spacing kept between consecutive layers when the weekend adjustment
# would otherwise make them collide or swap order.
MIN_LAYER_GAP = timedelta(hours=1)

# Smart assignment nudge: how long an open task may sit before the system
# chases it, and how far apart repeat nudges are. Capped so it can never
# become spam.
NUDGE_FIRST_AFTER_DAYS = 2
NUDGE_REPEAT_EVERY_DAYS = 2
NUDGE_MAX_COUNT = 3


def _notify_once(db: Session, user_id: int, notif_type: str, message_ar: str, message_en: str) -> bool:
    """Insert a notification unless this exact message already exists for this
    user. Returns True if it actually inserted.

    This is what makes the whole engine idempotent without a dispatch-ledger
    table: callers build messages that depend only on the event and the layer,
    never on the current time, so re-running produces byte-identical text that
    is recognised and skipped.
    """
    exists = (
        db.query(Notification.id)
        .filter(Notification.user_id == user_id, Notification.message_en == message_en)
        .first()
    )
    if exists:
        return False
    db.add(
        Notification(
            user_id=user_id,
            type=notif_type,
            message_ar=message_ar,
            message_en=message_en,
        )
    )
    return True


def _shift_off_weekend(moment: datetime) -> datetime:
    """Pull an alert moment back to the preceding working day if it lands on
    the Kuwaiti weekend. Always earlier, never later — pushing it later could
    move it past the very event it is warning about.

    The weekday is evaluated in **Kuwait** terms, not on the raw naive-UTC
    value: 22:00 UTC on a Thursday is already 01:00 Friday in Kuwait, and
    asking `.weekday()` on the stored value would call that a working Thursday
    and leave the alert on the weekend it was supposed to avoid.

    Friday is the only weekend day, so this loop steps back at most once — but
    it stays a loop so the behaviour is still correct if the business week is
    ever redefined in `kuwait_time.WEEKEND_WEEKDAYS`.
    """
    while is_kuwait_weekend(moment):
        moment -= timedelta(days=1)
    return moment


def _layer_moments(event_at: datetime, known_from: datetime) -> list[datetime]:
    """The three moments at which layers 1/2/3 should fire for an event.

    With comfortable notice these are simply 7/3/1 days before. With short
    notice (a hearing scheduled for the day after tomorrow, say) fixed offsets
    would sit in the past and all three would collapse into one instant — so
    instead the lead time is split proportionally (60% / 30% / 10% of the way
    through), which keeps three genuinely distinct, still-before-the-date
    warnings even for same-week events.

    Two guarantees hold for the returned list, in this priority order:
      1. every moment is strictly before `event_at` — the "never warn after
         the date" rule this module exists to enforce;
      2. the moments are strictly increasing, so Layer 1 always arrives before
         Layer 2 and Layer 2 before Layer 3.

    Guarantee 2 needs enforcing because the weekend adjustment moves each
    moment *earlier* independently: a Layer 3 landing on a Friday could be
    pulled back past an un-shifted Layer 2, so the recipient would receive
    "3 of 3" before "2 of 3". Weekend avoidance is a convenience, not a rule,
    so where the two conflict the ordering wins and a layer may stay on a
    weekend day.
    """
    total_notice = (event_at - known_from).total_seconds() / 86400
    if total_notice >= COMFORTABLE_NOTICE_DAYS:
        moments = [event_at - timedelta(days=d) for d in STANDARD_OFFSETS_DAYS]
    else:
        # Fractions of the remaining lead time, measured back from the event.
        moments = [event_at - timedelta(days=total_notice * f) for f in (0.6, 0.3, 0.1)]

    shifted = [_shift_off_weekend(m) for m in moments]

    # Walk backwards from the final alert, pulling any earlier layer that has
    # overtaken the one after it back in front of it again. Only ever moves a
    # moment earlier, so guarantee 1 is preserved by construction.
    for i in range(len(shifted) - 2, -1, -1):
        if shifted[i] >= shifted[i + 1]:
            shifted[i] = shifted[i + 1] - MIN_LAYER_GAP
    return shifted


def _due_layer(event_at: datetime, known_from: datetime, now: datetime) -> int:
    """Highest layer (0-3) whose moment has arrived. 0 = nothing due yet."""
    level = 0
    for i, moment in enumerate(_layer_moments(event_at, known_from), start=1):
        if now >= moment:
            level = i
    return level


# ---------------------------------------------------------------- hearings --


def _hearing_messages(case_label: str, session_at: datetime, level: int) -> tuple[str, str]:
    """Deterministic per (case, hearing datetime, layer) — no 'now'-dependent
    text, so _notify_once can recognise a repeat."""
    when = session_at.strftime("%d %b %Y, %H:%M")
    headline_en = {1: "Upcoming hearing — early notice", 2: "Hearing approaching — action required", 3: "Hearing tomorrow — final alert"}[level]
    headline_ar = {1: "جلسة قادمة — إشعار مبكر", 2: "اقتراب موعد الجلسة — مطلوب إجراء", 3: "الجلسة غداً — تنبيه أخير"}[level]
    return (
        f"{headline_ar} ({level} من 3): القضية {case_label} بتاريخ {when}",
        f"{headline_en} ({level} of 3): Case {case_label} on {when}",
    )


def _run_hearing_alerts(db: Session, now: datetime) -> bool:
    """Three pre-hearing layers for every scheduled hearing in the horizon.

    Recipients are the people actually responsible for the case: its assigned
    lawyer, plus anyone watching it. Cancelled/completed/postponed hearings and
    hearings already in the past are skipped — warning someone about a hearing
    that already happened is exactly the failure mode this module exists to
    prevent.
    """
    horizon = now + timedelta(days=HEARING_HORIZON_DAYS)
    sessions = (
        db.query(CourtSession)
        .options(joinedload(CourtSession.case).joinedload(Case.watchers))
        .filter(
            CourtSession.status == "scheduled",
            CourtSession.session_at > now,
            CourtSession.session_at <= horizon,
        )
        .all()
    )

    changed = False
    for session in sessions:
        case = session.case
        if case is None:
            continue
        # A hearing still sitting as "scheduled" on a case that has since been
        # closed is a leftover, not a live commitment — chasing people about it
        # is exactly the kind of noise that trains users to ignore alerts.
        if case.status == "closed":
            continue

        # "Known from" is when the hearing record was created, so a hearing
        # booked months ahead gets the full 7/3/1 treatment while one booked
        # at short notice gets compressed layers instead of a silent miss.
        known_from = session.created_at or (session.session_at - timedelta(days=COMFORTABLE_NOTICE_DAYS))
        level = _due_layer(session.session_at, known_from, now)
        if level == 0:
            continue

        recipients = set()
        if case.assigned_lawyer_id:
            recipients.add(case.assigned_lawyer_id)
        for watcher in case.watchers:
            recipients.add(watcher.user_id)
        if not recipients:
            continue

        case_label = f"{case.case_number}/{case.case_year}"
        # Send every layer up to the current one: someone added to a case late
        # still gets the full context rather than only the final alert.
        for lvl in range(1, level + 1):
            msg_ar, msg_en = _hearing_messages(case_label, session.session_at, lvl)
            for user_id in recipients:
                if _notify_once(db, user_id, "hearing", msg_ar, msg_en):
                    changed = True
    return changed


# ------------------------------------------------------------------- tasks --


def _task_messages(case_label: str, note: str, due_at: datetime, level: int) -> tuple[str, str]:
    when = due_at.strftime("%d %b %Y, %H:%M")
    headline_en = {1: "Task due soon — early notice", 2: "Task due — action required", 3: "Task due tomorrow — final alert"}[level]
    headline_ar = {1: "مهمة قادمة — إشعار مبكر", 2: "اقتراب موعد المهمة — مطلوب إجراء", 3: "المهمة غداً — تنبيه أخير"}[level]
    return (
        f"{headline_ar} ({level} من 3): {note} — القضية {case_label}، الموعد {when}",
        f"{headline_en} ({level} of 3): {note} — Case {case_label}, due {when}",
    )


def _overdue_messages(case_label: str, note: str, due_at: datetime) -> tuple[str, str]:
    when = due_at.strftime("%d %b %Y, %H:%M")
    return (
        f"فات موعد المهمة: {note} — القضية {case_label}، كان الموعد {when}",
        f"Task deadline passed: {note} — Case {case_label}, was due {when}",
    )


def _run_task_alerts(db: Session, now: datetime) -> bool:
    """Three pre-due layers for open tasks, plus a single safety-net notice if
    a deadline passes anyway.

    `case_reminders.escalation_level` is reused as the high-water mark of which
    layer has been reached (its old meaning was "how overdue"; it is now "how
    far through the pre-due sequence"). Existing rows carrying old values stay
    harmless — a stale 3 simply means "all pre-alerts considered sent", which
    is the correct outcome for something already past its date.
    """
    open_reminders = (
        db.query(CaseReminder)
        .options(joinedload(CaseReminder.case))
        .filter(CaseReminder.status == "open")
        .all()
    )

    changed = False
    for reminder in open_reminders:
        case = reminder.case
        if case is None or reminder.due_at is None:
            continue
        case_label = f"{case.case_number}/{case.case_year}"

        if reminder.due_at <= now:
            # The deadline passed. Do NOT invent a "future" reminder for it —
            # say plainly that it is past and let a human deal with it. Sent
            # once, to the assignee and whoever assigned it.
            msg_ar, msg_en = _overdue_messages(case_label, reminder.note, reminder.due_at)
            for user_id in {reminder.assigned_to, reminder.created_by}:
                if _notify_once(db, user_id, "reminder", msg_ar, msg_en):
                    changed = True
            continue

        level = _due_layer(reminder.due_at, reminder.created_at or now, now)
        if level == 0:
            continue

        # Layer 1 goes to the assignee; from layer 2 the person who assigned it
        # is looped in; layer 3 also reaches the case's lawyer, so nothing
        # reaches its deadline without the responsible lawyer having seen it.
        for lvl in range(1, level + 1):
            recipients = {reminder.assigned_to}
            if lvl >= 2:
                recipients.add(reminder.created_by)
            if lvl >= 3 and case.assigned_lawyer_id:
                recipients.add(case.assigned_lawyer_id)
            msg_ar, msg_en = _task_messages(case_label, reminder.note, reminder.due_at, lvl)
            for user_id in recipients:
                if _notify_once(db, user_id, "reminder", msg_ar, msg_en):
                    changed = True

        if level > reminder.escalation_level:
            reminder.escalation_level = level
            changed = True
    return changed


# ------------------------------------------------------- smart nudge (req 9) --


def _nudge_messages(case_label: str, note: str, index: int) -> tuple[tuple[str, str], tuple[str, str]]:
    """(assignee message, creator FYI message) for nudge number `index`.

    The wording is deliberately explicit that a system sent this. The lawyer
    must not read their copy as "I chased them", and the employee must not read
    theirs as a personal message from their boss.
    """
    assignee = (
        f"متابعة تلقائية ({index}): لم يتم تحديث المهمة المسندة إليك بعد — {note} (القضية {case_label}). "
        "يرجى مراجعتها وتحديث الحالة.",
        f"Smart Follow-up ({index}): your assigned task has not received an update yet — {note} "
        f"(Case {case_label}). Please review it and provide a status update.",
    )
    creator = (
        f"متابعة تلقائية من النظام ({index}): لم يقدّم الموظف المكلّف تحديثاً بعد بخصوص \"{note}\" "
        f"(القضية {case_label}). تم إرسال تذكير تلقائي نيابةً عنك.",
        f"System follow-up ({index}): the assigned employee has not provided an update yet on \"{note}\" "
        f"(Case {case_label}). A reminder was sent automatically on your behalf.",
    )
    return assignee, creator


def _run_smart_nudges(db: Session, now: datetime) -> bool:
    """Chase open tasks that have gone quiet.

    Cadence is derived from how long the task has been open, capped at
    NUDGE_MAX_COUNT, and each nudge index is sent exactly once (via
    _notify_once). The moment the assignee resolves the task it leaves the
    `status == 'open'` query and the cycle stops by itself — there is no
    separate "stop nudging" flag to get out of sync.
    """
    open_reminders = (
        db.query(CaseReminder)
        .options(joinedload(CaseReminder.case))
        .filter(CaseReminder.status == "open")
        .all()
    )

    changed = False
    for reminder in open_reminders:
        case = reminder.case
        if case is None or reminder.created_at is None:
            continue
        if reminder.assigned_to == reminder.created_by:
            continue  # self-assigned: nobody to chase, nobody to FYI

        days_open = (now - reminder.created_at).total_seconds() / 86400
        if days_open < NUDGE_FIRST_AFTER_DAYS:
            continue

        index = 1 + int((days_open - NUDGE_FIRST_AFTER_DAYS) // NUDGE_REPEAT_EVERY_DAYS)
        index = min(index, NUDGE_MAX_COUNT)

        case_label = f"{case.case_number}/{case.case_year}"
        (a_ar, a_en), (c_ar, c_en) = _nudge_messages(case_label, reminder.note, index)
        if _notify_once(db, reminder.assigned_to, "system", a_ar, a_en):
            changed = True
        if _notify_once(db, reminder.created_by, "system", c_ar, c_en):
            changed = True
    return changed


# --------------------------------------------------- assignment handoff --


def notify_task_assigned(db: Session, reminder: CaseReminder, assigner_name: str) -> None:
    """Tell the assignee, at the moment of assignment, that they have been
    given something to do.

    Without this the assignee learned nothing until a pre-due layer fired (or,
    under the old engine, until it was already overdue) — they had to think to
    go and look at the Reminders page. type='status' marks it as a real
    human-originated hand-off, which keeps it visually distinct from the
    type='system' automatic nudges.

    Best-effort: the caller has already committed the task itself, and failing
    to post a notification must not undo that.
    """
    case = reminder.case
    case_label = f"{case.case_number}/{case.case_year}" if case else "—"
    when = reminder.due_at.strftime("%d %b %Y, %H:%M")
    kind_ar = "طلب تحديث حالة" if reminder.type == "status_update_request" else "مهمة متابعة"
    kind_en = "Status update request" if reminder.type == "status_update_request" else "Follow-up task"
    try:
        _notify_once(
            db,
            reminder.assigned_to,
            "status",
            f"{kind_ar} من {assigner_name}: {reminder.note} — القضية {case_label}، الموعد {when}",
            f"{kind_en} from {assigner_name}: {reminder.note} — Case {case_label}, due {when}",
        )
        db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("aslg.escalation").exception("Failed to notify assignee of new task")


# -------------------------------------------------- document review handoff --


def notify_document_reviewed(
    db: Session,
    *,
    recipient_id: int,
    file_name: str,
    case_label: str,
    new_status: str,
    reviewer_name: str,
    reason: str | None = None,
) -> None:
    """Tell whoever uploaded a document that it has been approved or rejected.

    Written straight to the recipient's own `user_id` (never a role broadcast),
    so a client who uploaded through a temporary grant learns the outcome
    without anyone else seeing it.

    Deliberately does NOT go through `_notify_once`. That helper dedupes on
    (user_id, message_en), which is right for the engine — it re-runs on every
    page load and must not re-announce the same layer. A review is a one-shot
    human action instead, already guarded by the caller refusing to re-apply a
    status the document is in, so each notification here corresponds to a real
    state change. Routing it through _notify_once would silently swallow the
    second notice in a genuine approve -> reject -> approve sequence.

    Best-effort, like the other hand-off notifier: the review itself is the
    thing that matters and must not be rolled back because a notification row
    failed to insert.
    """
    verb_ar = "اعتماد" if new_status == "approved" else "رفض"
    verb_en = "approved" if new_status == "approved" else "rejected"
    tail_ar = f" — السبب: {reason}" if reason else ""
    tail_en = f" — Reason: {reason}" if reason else ""
    try:
        db.add(
            Notification(
                user_id=recipient_id,
                type="document",
                message_ar=f"تمت مراجعة مستند: تم {verb_ar} \"{file_name}\" في القضية {case_label} بواسطة {reviewer_name}{tail_ar}",
                message_en=f"Document reviewed: \"{file_name}\" on case {case_label} was {verb_en} by {reviewer_name}{tail_en}",
                is_read=False,
                created_at=datetime.utcnow(),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("aslg.escalation").exception("Failed to notify uploader of document review")


# -------------------------------------------------- linked-client case updates --

# Kept in sync by hand with js/i18n.js's stage_* keys — this backend has no
# access to the frontend's i18n dictionary, so the bilingual pairs are
# duplicated here exactly, the same way every other notifier in this module
# already hand-writes its own Arabic/English text.
_STAGE_LABELS = {
    "new": ("جديدة", "New"),
    "prep": ("تحت الإعداد", "Preparation"),
    "pleading": ("مرافعة", "Pleading"),
    "judgment": ("صدر حكم", "Judgment Issued"),
    "execution": ("تنفيذ", "Execution"),
    "closed": ("مغلقة", "Closed"),
}


def case_client_recipient_ids(db: Session, case: Case) -> set[int]:
    """Every portal user who should hear about this case's updates.

    Union of the original civil_id match (`users.civil_id == cases.civil_id`)
    and the explicit `user_case_links` (status='active') added by an Admin or
    the case's own Lawyer. A `set`, not a list, so someone connected both ways
    is still exactly one recipient — one real-world event must never produce
    two notifications to the same person.
    """
    from .models import User, UserCaseLink  # local import: keeps this module's own import list unchanged for its other, older callers

    civil_ids: set[int] = set()
    if case.civil_id:
        civil_ids = {row.id for row in db.query(User.id).filter(User.civil_id == case.civil_id).all()}

    linked_ids = {
        row.user_id
        for row in db.query(UserCaseLink.user_id)
        .filter(UserCaseLink.case_id == case.id, UserCaseLink.status == "active")
        .all()
    }
    return civil_ids | linked_ids


def notify_case_stage_changed(db: Session, case: Case, old_stage: str, new_stage: str) -> None:
    """Tell every linked client (civil_id match and/or explicit link) that
    their case moved to a new stage.

    Content is deliberately limited to the case number and the stage
    transition — never the internal notes/summary a stage change might be
    linked to in a lawyer's own head.

    Best-effort and not deduped through `_notify_once`: like the document
    review notice, this is a one-shot human action (the caller already
    refuses to no-op on an unchanged stage — see the `old_stage == new_stage`
    guard below), not a repeatedly-evaluated proactive check.
    """
    if old_stage == new_stage:
        return
    recipients = case_client_recipient_ids(db, case)
    if not recipients:
        return
    case_label = f"{case.case_number}/{case.case_year}"
    old_ar, old_en = _STAGE_LABELS.get(old_stage, (old_stage, old_stage))
    new_ar, new_en = _STAGE_LABELS.get(new_stage, (new_stage, new_stage))
    msg_ar = f"تم تحديث حالة القضية {case_label} من «{old_ar}» إلى «{new_ar}»"
    msg_en = f'Case {case_label} status updated from "{old_en}" to "{new_en}"'
    try:
        for user_id in recipients:
            db.add(
                Notification(
                    user_id=user_id, type="status", message_ar=msg_ar, message_en=msg_en,
                    is_read=False, created_at=datetime.utcnow(),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("aslg.escalation").exception("Failed to notify linked clients of stage change")


def notify_case_note_added(db: Session, case: Case) -> None:
    """Tell every linked client a note was added to their case.

    Never includes the note's own text — notes can carry internal-only legal
    commentary not meant for a client's eyes; only the fact that one exists
    is shared.
    """
    recipients = case_client_recipient_ids(db, case)
    if not recipients:
        return
    case_label = f"{case.case_number}/{case.case_year}"
    msg_ar = f"تمت إضافة ملاحظة جديدة إلى قضيتك {case_label}"
    msg_en = f"A new note was added to your case {case_label}"
    try:
        for user_id in recipients:
            db.add(
                Notification(
                    user_id=user_id, type="status", message_ar=msg_ar, message_en=msg_en,
                    is_read=False, created_at=datetime.utcnow(),
                )
            )
        db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("aslg.escalation").exception("Failed to notify linked clients of new note")


# ------------------------------------------------------------------ entry --


def run_reminder_escalations(db: Session) -> None:
    """Run every proactive check. Called on-demand from the dashboard,
    reminders and notifications endpoints — there is no scheduler in this app,
    and every insert is idempotent, so running it often is safe and cheap.

    Deliberately swallows its own failures: a notification engine must never
    take down the page the user actually asked for.
    """
    now = datetime.utcnow()
    try:
        changed = False
        changed |= _run_hearing_alerts(db, now)
        changed |= _run_task_alerts(db, now)
        changed |= _run_smart_nudges(db, now)
        if changed:
            db.commit()
    except Exception:
        db.rollback()
        import logging

        logging.getLogger("aslg.escalation").exception("Proactive notification run failed")
