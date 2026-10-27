from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from takt.time_accounting.calculation import Attendance, Break, InvalidIntervals, calculate

from .helpers import at

DAY = date(2026, 10, 27)
MOSCOW = ZoneInfo("Europe/Moscow")


def summary(intervals: tuple[Attendance, ...], as_of: str = "13:10"):
    return calculate(
        work_date=DAY,
        required_minutes=360,
        intervals=intervals,
        as_of=at(as_of),
        time_zone=MOSCOW,
    )


def test_time_with_completed_break():
    value = summary((Attendance(at("08:30"), breaks=(Break(at("12:00"), at("12:30")),)),))
    assert value.presence_seconds == 280 * 60
    assert value.break_seconds == 30 * 60
    assert value.credited_seconds == 280 * 60
    assert value.remaining_seconds == 80 * 60
    assert value.estimated_completion_at == at("14:30")
    assert value.state == "working"


def test_optional_break_is_recorded_without_pausing_total_time():
    intervals = (Attendance(at("08:30"), breaks=(Break(at("12:00")),)),)
    first = summary(intervals, "12:10")
    later = summary(intervals, "13:10")
    assert first.credited_seconds == 220 * 60
    assert later.credited_seconds == 280 * 60
    assert later.break_seconds == 70 * 60
    assert later.estimated_completion_at == at("14:30")
    assert later.state == "on_break"


def test_finished_attendance_does_not_keep_growing():
    intervals = (Attendance(at("08:30"), at("12:00")),)
    assert (
        summary(intervals, "13:10").credited_seconds == summary(intervals, "20:00").credited_seconds
    )
    assert summary(intervals).state == "finished"


def test_multiple_intervals_and_actual_target_completion():
    value = summary(
        (
            Attendance(at("08:00"), at("11:00")),
            Attendance(at("12:00"), at("16:00"), (Break(at("13:00"), at("13:30")),)),
        ),
        "17:00",
    )
    assert value.credited_seconds == 420 * 60
    assert value.remaining_seconds == 0
    assert value.target_reached_at == at("15:00")
    assert value.estimated_completion_at is None


def test_midnight_clips_day_without_fabricating_checkout():
    start = datetime.fromisoformat("2026-10-27T23:00:00+03:00")
    now = datetime.fromisoformat("2026-10-28T01:00:00+03:00")
    value = calculate(
        work_date=DAY,
        required_minutes=360,
        intervals=(Attendance(start),),
        as_of=now,
        time_zone=MOSCOW,
    )
    assert value.credited_seconds == 3600
    assert value.state == "needs_checkout"
    assert value.estimated_completion_at is None


def test_daylight_saving_counts_elapsed_time_in_utc():
    value = calculate(
        work_date=date(2026, 10, 25),
        required_minutes=240,
        intervals=(
            Attendance(
                datetime.fromisoformat("2026-10-25T01:00:00+02:00"),
                datetime.fromisoformat("2026-10-25T04:00:00+01:00"),
            ),
        ),
        as_of=datetime(2026, 10, 25, 5, tzinfo=UTC),
        time_zone=ZoneInfo("Europe/Berlin"),
    )
    assert value.credited_seconds == 4 * 3600
    assert value.remaining_seconds == 0


def test_subsecond_totals_preserve_remaining_time():
    start = at("08:30")
    value = calculate(
        work_date=DAY,
        required_minutes=360,
        intervals=(Attendance(start),),
        as_of=start + timedelta(microseconds=500000),
        time_zone=MOSCOW,
    )
    assert value.credited_seconds + value.remaining_seconds == value.required_seconds


@pytest.mark.parametrize(
    "intervals",
    [
        (Attendance(at("10:00"), at("09:00")),),
        (Attendance(at("10:00"), at("10:00")),),
        (Attendance(at("08:00"), at("12:00")), Attendance(at("11:00"), at("13:00"))),
        (Attendance(at("08:00")), Attendance(at("09:00"))),
        (Attendance(at("08:00"), breaks=(Break(at("07:59"), at("09:00")),)),),
        (Attendance(at("08:00"), at("12:00"), (Break(at("10:00")),)),),
        (
            Attendance(
                at("08:00"),
                breaks=(
                    Break(at("10:00"), at("11:00")),
                    Break(at("10:30"), at("12:00")),
                ),
            ),
        ),
        (Attendance(at("14:00")),),
        (Attendance(datetime(2026, 10, 27, 8)),),
    ],
)
def test_invalid_records_are_rejected(intervals):
    with pytest.raises(InvalidIntervals):
        summary(intervals)


def test_empty_day_has_no_forecast():
    value = summary(())
    assert value.state == "not_started"
    assert value.credited_seconds == 0
    assert value.remaining_seconds == 6 * 3600
    assert value.estimated_completion_at is None
