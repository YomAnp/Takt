"""Timetable boundary; attendance commands never depend on this service."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol


@dataclass(frozen=True)
class Lesson:
    teacher_id: str
    teacher_name: str
    room: str
    starts_at: datetime
    ends_at: datetime


class Timetable(Protocol):
    async def for_teacher(self, teacher_id: str, day: date) -> tuple[Lesson, ...]: ...


class TimetableNotConfigured(RuntimeError):
    pass


class DisabledTimetable:
    async def for_teacher(self, teacher_id: str, day: date) -> tuple[Lesson, ...]:
        raise TimetableNotConfigured("The timetable connection is not configured.")
