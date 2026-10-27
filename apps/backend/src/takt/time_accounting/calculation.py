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


def _clip(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> timedelta:
    return max(timedelta(), min(end, day_end) - max(start, day_start))


def calculate(
    *,
    work_date: date,
    required_minutes: int,
    intervals: tuple[Attendance, ...],
    as_of: datetime,
    time_zone: ZoneInfo,
) -> Summary:
    """Calculate one local calendar day without mutating or closing any records."""
    if isinstance(required_minutes, bool) or not 1 <= required_minutes <= 24 * 60:
        raise InvalidIntervals("Required time must be between 1 and 1440 minutes.")
    as_of = _utc(as_of)
    day_start = datetime.combine(work_date, time.min, time_zone).astimezone(UTC)
    day_end = datetime.combine(work_date + timedelta(days=1), time.min, time_zone).astimezone(UTC)
    attendance = sorted(intervals, key=lambda item: _utc(item.started_at))
    if sum(item.ended_at is None for item in attendance) > 1:
        raise InvalidIntervals("Only one attendance interval can remain open.")

    total_presence = timedelta()
    total_breaks = timedelta()
    credited_segments: list[tuple[datetime, datetime]] = []
    previous_end: datetime | None = None
    active: Attendance | None = None
    active_break = False

    for item in attendance:
        start, end = _bounds(item.started_at, item.ended_at, as_of)
        if previous_end is not None and start < previous_end:
            raise InvalidIntervals("Attendance intervals must not overlap.")
        previous_end = end
        if item.ended_at is None:
            active = item

        breaks = sorted(item.breaks, key=lambda pause: _utc(pause.started_at))
        if sum(pause.ended_at is None for pause in breaks) > 1:
            raise InvalidIntervals("Only one break can remain open.")
        cursor = start
        for pause in breaks:
            pause_start, pause_end = _bounds(pause.started_at, pause.ended_at, as_of)
            if pause.ended_at is None and item.ended_at is not None:
                raise InvalidIntervals("Close the break before closing attendance.")
            if pause_start < start or pause_end > end:
                raise InvalidIntervals("A break must be inside its attendance interval.")
            if pause_start < cursor:
                raise InvalidIntervals("Breaks must not overlap.")
            if pause_start > cursor:
                credited_segments.append((max(cursor, day_start), min(pause_start, day_end)))
            total_breaks += _clip(pause_start, pause_end, day_start, day_end)
            cursor = pause_end
            if pause.ended_at is None:
                active_break = True
        if end > cursor:
            credited_segments.append((max(cursor, day_start), min(end, day_end)))
        total_presence += _clip(start, end, day_start, day_end)

    credited = total_presence - total_breaks
    required = timedelta(minutes=required_minutes)
    remaining = max(timedelta(), required - credited)
    target_reached_at = None
    needed = required
    for start, end in credited_segments:
        if end <= start:
            continue
        length = end - start
        if length >= needed:
            target_reached_at = start + needed
            break
        needed -= length

    state: State = "not_started" if total_presence == timedelta() else "finished"
    active_for_day = active is not None and _utc(active.started_at) < day_end
    if active_for_day:
        if as_of >= day_end:
            state = "needs_checkout"
        elif as_of >= day_start:
            state = "on_break" if active_break else "working"

    forecast = None
    if state == "working" and remaining > timedelta() and as_of + remaining <= day_end:
        forecast = as_of + remaining

    return Summary(
        work_date=work_date,
        time_zone=time_zone.key,
        as_of=as_of,
        state=state,
        required_seconds=required_minutes * 60,
        presence_seconds=int(total_presence.total_seconds()),
        break_seconds=int(total_breaks.total_seconds()),
        credited_seconds=int(credited.total_seconds()),
        remaining_seconds=max(0, required_minutes * 60 - int(credited.total_seconds())),
        target_reached_at=target_reached_at,
        estimated_completion_at=forecast,
    )
