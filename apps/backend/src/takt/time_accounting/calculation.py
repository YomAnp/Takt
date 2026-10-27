from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

State = Literal["not_started", "working", "on_break", "finished", "needs_checkout"]


class InvalidIntervals(ValueError):
    """Attendance data cannot produce a consistent calculation."""


@dataclass(frozen=True, slots=True)
class Break:
    started_at: datetime
    ended_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Attendance:
    started_at: datetime
    ended_at: datetime | None = None
    breaks: tuple[Break, ...] = ()


@dataclass(frozen=True, slots=True)
class Summary:
    work_date: date
    time_zone: str
    as_of: datetime
    state: State
    required_seconds: int
    presence_seconds: int
    break_seconds: int
    credited_seconds: int
    remaining_seconds: int
    target_reached_at: datetime | None
    estimated_completion_at: datetime | None


@dataclass(frozen=True, slots=True)
class ScheduledSummary:
    work_date: date
    time_zone: str
    as_of: datetime
    state: State
    scheduled_end_at: datetime
    seconds_until_end: int
    total_seconds: int | None
    break_seconds: int | None
    overtime_seconds: int | None
    confirmed_seconds: int
    is_provisional: bool


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidIntervals("Every timestamp must include its UTC offset.")
    return value.astimezone(UTC)


def _bounds(start: datetime, end: datetime | None, as_of: datetime) -> tuple[datetime, datetime]:
    start = _utc(start)
    finish = _utc(end) if end is not None else as_of
    if start > as_of or finish > as_of:
        raise InvalidIntervals("An attendance event cannot be in the future.")
    if finish < start or (end is not None and finish == start):
        raise InvalidIntervals("A closed interval must end after it starts.")
    return start, finish


def _validate(intervals: tuple[Attendance, ...], as_of: datetime) -> tuple[Attendance, ...]:
    ordered = sorted(intervals, key=lambda item: _utc(item.started_at))
    if sum(item.ended_at is None for item in ordered) > 1:
        raise InvalidIntervals("Only one attendance interval can remain open.")
    previous_end = None
    for item in ordered:
        start, end = _bounds(item.started_at, item.ended_at, as_of)
        if previous_end is not None and start < previous_end:
            raise InvalidIntervals("Attendance intervals must not overlap.")
        previous_end = end
        pauses = sorted(item.breaks, key=lambda pause: _utc(pause.started_at))
        if sum(pause.ended_at is None for pause in pauses) > 1:
            raise InvalidIntervals("Only one break can remain open.")
        cursor = start
        for pause in pauses:
            pause_start, pause_end = _bounds(pause.started_at, pause.ended_at, as_of)
            if pause.ended_at is None and item.ended_at is not None:
                raise InvalidIntervals("Close the break before closing attendance.")
            if pause_start < start or pause_end > end:
                raise InvalidIntervals("A break must be inside its attendance interval.")
            if pause_start < cursor:
                raise InvalidIntervals("Breaks must not overlap.")
            cursor = pause_end
    return tuple(ordered)


def _clip(start: datetime, end: datetime, lower: datetime, upper: datetime) -> timedelta:
    return max(timedelta(), min(end, upper) - max(start, lower))


def calculate(
    *,
    work_date: date,
    required_minutes: int,
    intervals: tuple[Attendance, ...],
    as_of: datetime,
    time_zone: ZoneInfo,
) -> Summary:
    """Duration-target compatibility calculation; optional breaks are informational."""
    if isinstance(required_minutes, bool) or not 1 <= required_minutes <= 1440:
        raise InvalidIntervals("Required time must be between 1 and 1440 minutes.")
    as_of = _utc(as_of)
    ordered = _validate(intervals, as_of)
    day_start = datetime.combine(work_date, time.min, time_zone).astimezone(UTC)
    day_end = datetime.combine(work_date + timedelta(days=1), time.min, time_zone).astimezone(UTC)
    presence = timedelta()
    pauses = timedelta()
    needed = timedelta(minutes=required_minutes)
    target_reached_at = None
    active = None
    for item in ordered:
        start, end = _bounds(item.started_at, item.ended_at, as_of)
        length = _clip(start, end, day_start, day_end)
        if target_reached_at is None:
            if length >= needed:
                target_reached_at = max(start, day_start) + needed
            else:
                needed -= length
        presence += length
        for pause in item.breaks:
            a, b = _bounds(pause.started_at, pause.ended_at, as_of)
            pauses += _clip(a, b, day_start, day_end)
        if item.ended_at is None and start < day_end:
            active = item
    state: State = "finished" if presence else "not_started"
    if active is not None and as_of >= day_start:
        state = (
            "needs_checkout"
            if as_of >= day_end
            else ("on_break" if any(p.ended_at is None for p in active.breaks) else "working")
        )
    remaining = max(timedelta(), timedelta(minutes=required_minutes) - presence)
    forecast = None
    if (
        state in {"working", "on_break"}
        and remaining > timedelta()
        and as_of + remaining <= day_end
    ):
        forecast = as_of + remaining
    seconds = int(presence.total_seconds())
    return Summary(
        work_date,
        time_zone.key,
        as_of,
        state,
        required_minutes * 60,
        seconds,
        int(pauses.total_seconds()),
        seconds,
        max(0, required_minutes * 60 - seconds),
        target_reached_at,
        forecast,
    )


def calculate_schedule(
    *,
    work_date: date,
    end_time: time,
    intervals: tuple[Attendance, ...],
    as_of: datetime,
    time_zone: ZoneInfo,
) -> ScheduledSummary:
    """Count a workday by arrival date, with an independent fixed local ending time."""
    if end_time.tzinfo is not None:
        raise InvalidIntervals("The ending time must be a local clock time.")
    as_of = _utc(as_of)
    ordered = _validate(intervals, as_of)
    ending = datetime.combine(work_date, end_time, time_zone).astimezone(UTC)
    records = [
        item for item in ordered if _utc(item.started_at).astimezone(time_zone).date() == work_date
    ]
    total, pauses, overtime, confirmed = (timedelta() for _ in range(4))
    active = None
    for item in records:
        start, end = _bounds(item.started_at, item.ended_at, as_of)
        total += end - start
        overtime += max(timedelta(), end - max(start, ending))
        if item.ended_at is not None:
            confirmed += end - start
        else:
            active = item
        for pause in item.breaks:
            a, b = _bounds(pause.started_at, pause.ended_at, as_of)
            pauses += b - a
    state: State = "finished" if records else "not_started"
    if active is not None:
        state = (
            "needs_checkout"
            if work_date < as_of.astimezone(time_zone).date()
            else ("on_break" if any(p.ended_at is None for p in active.breaks) else "working")
        )
    pending = state == "needs_checkout"
    return ScheduledSummary(
        work_date=work_date,
        time_zone=time_zone.key,
        as_of=as_of,
        state=state,
        scheduled_end_at=ending,
        seconds_until_end=max(0, int((ending - as_of).total_seconds())),
        total_seconds=None if pending else int(total.total_seconds()),
        break_seconds=None if pending else int(pauses.total_seconds()),
        overtime_seconds=None if pending else int(overtime.total_seconds()),
        confirmed_seconds=int(confirmed.total_seconds()),
        is_provisional=active is not None,
    )
