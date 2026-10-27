from datetime import date, time

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from takt.time_accounting.calculation import State


class BreakInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: AwareDatetime
    ended_at: AwareDatetime | None = None


class AttendanceInput(BreakInput):
    breaks: list[BreakInput] = Field(default_factory=list, max_length=100)


class CalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_date: date
    required_minutes: int = Field(strict=True, ge=1, le=1440)
    intervals: list[AttendanceInput] = Field(default_factory=list, max_length=100)
    as_of: AwareDatetime | None = None


class CalculationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    work_date: date
    time_zone: str
    as_of: AwareDatetime
    state: State
    required_seconds: int
    presence_seconds: int
    break_seconds: int
    credited_seconds: int
    remaining_seconds: int
    target_reached_at: AwareDatetime | None
    estimated_completion_at: AwareDatetime | None


class ScheduledCalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    work_date: date
    end_time: time
    intervals: list[AttendanceInput] = Field(default_factory=list, max_length=100)
    as_of: AwareDatetime | None = None


class ScheduledCalculationOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    work_date: date
    time_zone: str
    as_of: AwareDatetime
    state: State
    scheduled_end_at: AwareDatetime
    seconds_until_end: int
    total_seconds: int | None
    break_seconds: int | None
    overtime_seconds: int | None
    confirmed_seconds: int
    is_provisional: bool
