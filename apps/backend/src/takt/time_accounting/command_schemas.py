from datetime import date
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from takt.time_accounting.schemas import CalculationOutput, ScheduledCalculationOutput


class BreakSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    started_at: AwareDatetime
    ended_at: AwareDatetime | None


class AttendanceSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    revision: int = Field(ge=1)
    started_at: AwareDatetime
    ended_at: AwareDatetime | None
    breaks: tuple[BreakSnapshot, ...]


class CommandResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    request_id: UUID
    attendance: AttendanceSnapshot
    closed_break_id: UUID | None = None


class CheckoutPreview(BaseModel):
    model_config = ConfigDict(frozen=True)

    attendance: AttendanceSnapshot
    will_end_break: bool
    summary: CalculationOutput | ScheduledCalculationOutput
    proposed_end_at: AwareDatetime


class PendingDeparture(BaseModel):
    attendance: AttendanceSnapshot
    work_date: date
    scheduled_end_at: AwareDatetime | None
    can_use_scheduled_end: bool
