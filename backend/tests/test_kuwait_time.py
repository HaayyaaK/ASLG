"""Regression tests for the pre-existing Kuwait business-calendar helpers
(backend/app/kuwait_time.py). Written before any Procedural Intelligence
code changes this module, to prove the baseline this feature builds on
(kuwait_time._shift_off_weekend-style reasoning in escalation.py, and the
new procedures._shift_off_weekend_forward) is itself correct."""

from datetime import date, datetime

from app.kuwait_time import (
    is_kuwait_weekend,
    kuwait_day_utc_range,
    kuwait_weekday,
    parse_kuwait_date,
    to_kuwait,
    to_utc,
)


def test_friday_is_the_only_weekend_day():
    # 2026-09-18 is a Friday; every other day that week is a working day.
    friday = datetime(2026, 9, 18, 6, 0)  # 09:00 Kuwait
    assert is_kuwait_weekend(friday) is True
    for day in range(13, 20):  # Sun 13th .. Sat 19th
        if day == 18:
            continue
        assert is_kuwait_weekend(datetime(2026, 9, day, 6, 0)) is False
    # Saturday (the day after Friday) must NOT be treated as a weekend day —
    # this firm works Saturdays; a past regression treated {Fri, Sat} as the
    # weekend and pulled every Saturday alert a day earlier than intended.
    saturday = datetime(2026, 9, 19, 6, 0)
    assert is_kuwait_weekend(saturday) is False


def test_utc_to_kuwait_crosses_midnight_boundary():
    # 22:00 UTC Thursday is 01:00 Friday in Kuwait -- the weekend -- even
    # though the raw UTC value is still a Thursday.
    thu_22_utc = datetime(2026, 9, 17, 22, 0)
    assert kuwait_weekday(thu_22_utc) == 4  # Friday
    assert is_kuwait_weekend(thu_22_utc) is True


def test_kuwait_day_utc_range_is_half_open_and_offset_by_three_hours():
    start, end = kuwait_day_utc_range(date(2026, 9, 9))
    assert start == datetime(2026, 9, 8, 21, 0, 0)
    assert end == datetime(2026, 9, 9, 21, 0, 0)
    # The final microsecond of the Kuwait day must be included, not excluded
    # by an off-by-one upper bound.
    assert end - start == to_utc(datetime(2026, 9, 10)) - to_utc(datetime(2026, 9, 9))


def test_to_kuwait_and_to_utc_are_inverses():
    utc_now = datetime(2026, 9, 16, 12, 34, 56)
    assert to_utc(to_kuwait(utc_now)) == utc_now


def test_parse_kuwait_date_rejects_garbage_without_raising():
    assert parse_kuwait_date("not-a-date") is None
    assert parse_kuwait_date("") is None
    assert parse_kuwait_date("2026-09-16") == date(2026, 9, 16)
