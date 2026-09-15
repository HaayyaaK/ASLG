"""Kuwait business-calendar helpers.

The application stores and returns **naive UTC** everywhere (`datetime.utcnow()`
throughout, MySQL session pinned to +00:00 in `database.py`) and converts to
`Asia/Kuwait` only for display in the browser. That storage convention is
deliberate and is NOT changed here.

What this module fixes is the *interpretation* layer. Several places were
asking calendar questions — "is this today?", "which weekday is this?", "which
hearings fall on this date?" — directly against the naive-UTC value, which
answers them in UTC rather than in the timezone the firm actually works in. For
a Kuwait business day (UTC+3) the two disagree for the first three hours of
every day: 00:00-02:59 Kuwait is still the *previous* calendar day in UTC.

Kuwait has observed a fixed UTC+3 with no daylight saving since 1990, so a
constant offset is exact rather than an approximation, and no tz database
lookup is required at runtime.

Convention used below: a "naive UTC" datetime is what the database holds; a
"Kuwait wall-clock" datetime is that same instant with the offset already
applied, and is only ever used for asking calendar questions — never stored.
"""

from datetime import date, datetime, time, timedelta

# Kuwait has been a fixed UTC+3 with no DST since 1990.
KUWAIT_UTC_OFFSET = timedelta(hours=3)


def to_kuwait(naive_utc: datetime) -> datetime:
    """Naive-UTC (as stored) -> Kuwait wall-clock, still naive."""
    return naive_utc + KUWAIT_UTC_OFFSET


def to_utc(naive_kuwait: datetime) -> datetime:
    """Kuwait wall-clock -> naive UTC, suitable for storing/comparing."""
    return naive_kuwait - KUWAIT_UTC_OFFSET


def kuwait_now() -> datetime:
    """The current Kuwait wall-clock time, naive."""
    return to_kuwait(datetime.utcnow())


def kuwait_today() -> date:
    """Today's date *in Kuwait* — the firm's business date."""
    return kuwait_now().date()


def kuwait_weekday(naive_utc: datetime) -> int:
    """Weekday of a stored instant as experienced in Kuwait (Mon=0 ... Sun=6).

    Matters because a moment at 22:00 UTC on a Thursday is already 01:00 Friday
    in Kuwait — the weekend — and asking `.weekday()` on the raw UTC value would
    call it a working Thursday.
    """
    return to_kuwait(naive_utc).weekday()


# ---------------------------------------------------------------------------
# The firm's business week.
#
# This is the single source of truth for "is this a working day?". It is a
# business rule, not a timezone fact, so it lives beside the offset helpers
# rather than being re-derived at each call site.
#
#   Sunday    - first business day of the week
#   Monday    - working day
#   Tuesday   - working day
#   Wednesday - working day
#   Thursday  - working day
#   Friday    - the ONLY weekend day
#   Saturday  - working day
#
# Python's `date.weekday()` numbers Mon=0 ... Sun=6, so Friday is 4 and that
# is the entire set. Saturday (5) is deliberately absent: this firm works
# Saturdays, and an earlier revision of the escalation engine wrongly treated
# {4, 5} as the weekend, which pulled every Saturday alert a day earlier than
# it needed to be.
# ---------------------------------------------------------------------------
WEEKEND_WEEKDAYS = frozenset({4})

# Sunday first, then the rest of the week in working order. Used for anything
# that needs to present or iterate the business week in the firm's own order
# rather than the ISO Mon-first order.
BUSINESS_WEEK_ORDER = (6, 0, 1, 2, 3, 5)  # Sun, Mon, Tue, Wed, Thu, Sat


def is_kuwait_weekend(naive_utc: datetime) -> bool:
    """True when a stored instant falls on the firm's weekend (Friday only)."""
    return kuwait_weekday(naive_utc) in WEEKEND_WEEKDAYS


def is_kuwait_working_day(naive_utc: datetime) -> bool:
    """True when a stored instant falls on a working day (Sat-Thu)."""
    return not is_kuwait_weekend(naive_utc)


def kuwait_day_utc_range(day: date) -> tuple[datetime, datetime]:
    """The naive-UTC half-open range covering one Kuwait calendar day.

    Returns `(start, end)` such that a stored `session_at` belongs to `day`
    in Kuwait exactly when `start <= session_at < end`. For 2026-09-09 that is
    2026-09-08 21:00:00 <= x < 2026-09-09 21:00:00.

    A half-open range is used deliberately instead of the previous
    `datetime.combine(day, time.max)` upper bound: `time.max` is
    23:59:59.999999, which silently excludes anything landing in that final
    microsecond.
    """
    start_local = datetime.combine(day, time.min)
    return to_utc(start_local), to_utc(start_local + timedelta(days=1))


def kuwait_today_utc_range() -> tuple[datetime, datetime]:
    """`kuwait_day_utc_range` for the current Kuwait business date."""
    return kuwait_day_utc_range(kuwait_today())


def parse_kuwait_date(value: str) -> date | None:
    """Parse a 'YYYY-MM-DD' string as a Kuwait calendar date.

    Returns None for anything unparseable so callers can fall back to ignoring
    the filter rather than returning a 500 on a stray query string.
    """
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, AttributeError):
        return None
