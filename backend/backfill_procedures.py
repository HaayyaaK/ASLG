"""One-time backfill: project existing case_timeline / court_sessions /
experts / execution_files rows into the new case_procedures event log.

    python backfill_procedures.py            # dry run, prints what it would do
    python backfill_procedures.py --apply     # actually writes the rows

WHY THIS EXISTS
----------------
Recording "Latest Event" only starting from today would make every case
that already has history look brand new the moment this feature ships —
the Procedure tab would show nothing before now for a case that has been
open for two years. This script gives every pre-existing case a real
starting position in the new event log.

WHAT IT DELIBERATELY DOES NOT DO
----------------------------------
It NEVER generates a CaseDeadline. Backfilling a deadline retroactively
would fabricate a legal position ("this appeal was due on X") the firm
never actually tracked at the time — exactly the kind of AI-invented fact
this whole feature exists to prevent. Every row this script writes is
tagged source='migrated', source_tier='unverified': visibly a projection
of old data, never presented as verified fact. A lawyer reviewing a
migrated case is expected to record a real, present-tense procedure (via
the Procedure tab or POST /api/procedures/{case_id}) to establish the
case's actual current position going forward; only that forward-looking
event will ever produce a real deadline (see procedures.py's engine).

MAPPING
-------
  case_timeline row  -> matched by exact title text against the seeded
                         ProcedureType catalogue (case-insensitive, either
                         language); unmatched titles fall back to the
                         generic 'migrated_step' type rather than being
                         guessed into a specific one they may not be.
  court_sessions row -> status 'scheduled' -> hearing_scheduled
                        status 'done'      -> hearing_held
                        status 'postponed' -> hearing_postponed
                        status 'cancelled' -> hearing_postponed (closest
                                              existing type; noted in
                                              notes_en/ar so it is never
                                              confused with a genuine
                                              postponement)
  experts row        -> expert_appointed, occurred_at = assigned_at (the
                        only real date this table carries; there is no
                        report-filed timestamp to also backfill)
  execution_files row -> execution_opened, occurred_at = last_action_at if
                        set, else the case's own created_at (an
                        approximation — noted in notes_en/ar — since this
                        table carries no opening date of its own)

Idempotent: re-running skips any (case_id, procedure_type_id, occurred_at)
combination that already exists as a source='migrated' row, so a second
run after fixing a mapping only adds what's genuinely new.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Expert names, court circuits etc. in the data this script prints are
# frequently Arabic. A plain `python backfill_procedures.py` on a Windows
# console defaults to the system codepage (often cp1252), which cannot
# encode Arabic and raises UnicodeEncodeError mid-run -- reconfiguring here
# makes console output robust regardless of the invoking shell's codepage,
# without changing behaviour on an already-UTF-8 terminal.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Case,
    CaseProcedure,
    CaseTimeline,
    CourtSession,
    ExecutionFile,
    Expert,
    ProcedureType,
    Role,
    User,
)

SESSION_STATUS_TO_PROCEDURE = {
    "scheduled": "hearing_scheduled",
    "done": "hearing_held",
    "postponed": "hearing_postponed",
    "cancelled": "hearing_postponed",
}


def _system_actor(db) -> User:
    """recorded_by is NOT NULL on case_procedures (see models.py) and there
    is no "system" user in this schema — attribute migrated rows to the
    firm's Admin account, the same convention procedures.py itself uses
    (attributing an engine-generated deadline's reminder to the human who
    caused it) applied to a backfill with no human actor at all."""
    admin = db.query(User).join(Role).filter(Role.code == "Admin").first()
    if admin is None:
        raise RuntimeError("No Admin user found -- cannot attribute migrated rows to anyone.")
    return admin


def _build_title_lookup(db) -> dict[str, ProcedureType]:
    lookup = {}
    for pt in db.query(ProcedureType).all():
        lookup[pt.name_ar.strip().lower()] = pt
        lookup[pt.name_en.strip().lower()] = pt
    return lookup


def _already_migrated(db, case_id: int, procedure_type_id: int, occurred_at) -> bool:
    return (
        db.query(CaseProcedure.id)
        .filter(
            CaseProcedure.case_id == case_id,
            CaseProcedure.procedure_type_id == procedure_type_id,
            CaseProcedure.occurred_at == occurred_at,
            CaseProcedure.source == "migrated",
        )
        .first()
        is not None
    )


def backfill(db, apply: bool) -> int:
    admin = _system_actor(db)
    title_lookup = _build_title_lookup(db)
    migrated_type = db.query(ProcedureType).filter(ProcedureType.code == "migrated_step").first()
    session_types = {
        code: db.query(ProcedureType).filter(ProcedureType.code == code).first()
        for code in set(SESSION_STATUS_TO_PROCEDURE.values())
    }
    expert_type = db.query(ProcedureType).filter(ProcedureType.code == "expert_appointed").first()
    execution_type = db.query(ProcedureType).filter(ProcedureType.code == "execution_opened").first()

    missing = [
        name for name, val in [
            ("migrated_step", migrated_type), ("expert_appointed", expert_type), ("execution_opened", execution_type),
            *[(f"hearing_* ({c})", v) for c, v in session_types.items()],
        ] if val is None
    ]
    if missing:
        raise RuntimeError(
            f"Required ProcedureType rows not found: {missing}. "
            "Apply db/migration_procedural_intelligence.sql and db/seed_procedure_rules.sql first."
        )

    planned: list[tuple] = []  # (case_id, procedure_type, occurred_at, notes_en, notes_ar)

    for step in db.query(CaseTimeline).order_by(CaseTimeline.case_id, CaseTimeline.sort_order).all():
        title = ((step.step_title_en or step.step_title_ar) or "").strip().lower()
        matched = title_lookup.get(title) or title_lookup.get((step.step_title_ar or "").strip().lower())
        ptype = matched or migrated_type
        planned.append((step.case_id, ptype, step.step_date,
                         step.step_title_en, step.step_title_ar))

    for session in db.query(CourtSession).all():
        code = SESSION_STATUS_TO_PROCEDURE.get(session.status)
        if code is None:
            continue
        ptype = session_types[code]
        note_en = f"Migrated from court_sessions #{session.id} (status={session.status})"
        note_ar = f"مرحّل من جلسة رقم {session.id} (الحالة: {session.status})"
        planned.append((session.case_id, ptype, session.session_at, note_en, note_ar))

    for expert in db.query(Expert).all():
        planned.append((expert.case_id, expert_type, expert.assigned_at,
                         f"Migrated from experts #{expert.id} ({expert.expert_name})",
                         f"مرحّل من خبير رقم {expert.id} ({expert.expert_name})"))

    for execution in db.query(ExecutionFile).all():
        case = db.get(Case, execution.case_id)
        occurred_at = execution.last_action_at or (case.created_at if case else None)
        if occurred_at is None:
            continue
        approx = "" if execution.last_action_at else " [approximate date -- no opening date recorded]"
        planned.append((execution.case_id, execution_type, occurred_at,
                         f"Migrated from execution_files #{execution.id}{approx}",
                         f"مرحّل من ملف تنفيذ رقم {execution.id}{approx}"))

    written = 0
    for case_id, ptype, occurred_at, note_en, note_ar in planned:
        if occurred_at is None:
            continue
        if _already_migrated(db, case_id, ptype.id, occurred_at):
            continue
        print(f"{'[APPLY]' if apply else '[DRY RUN]'} case={case_id} -> {ptype.code} @ {occurred_at} ({note_en})")
        if apply:
            db.add(CaseProcedure(
                case_id=case_id, procedure_type_id=ptype.id, occurred_at=occurred_at,
                recorded_by=admin.id, source="migrated", source_tier="unverified",
                notes_en=note_en, notes_ar=note_ar,
            ))
            written += 1
    if apply and written:
        db.commit()
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually write rows (default is a dry run that only prints).")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        count = backfill(db, apply=args.apply)
        if args.apply:
            print(f"\nBackfill complete: {count} case_procedures row(s) written.")
        else:
            print(f"\nDry run complete: {count} row(s) WOULD be written. Re-run with --apply to write them.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
