from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from takt.database import session_factory
from takt.identity.router import actor_id
from takt.time_accounting import commands
from takt.time_accounting.access import load_actor
from takt.time_accounting.command_schemas import (
    AttendanceSnapshot,
    CheckoutPreview,
    CommandResult,
    PendingDeparture,
)
from takt.time_accounting.models import AttendanceRecord
from takt.time_accounting.schemas import CalculationOutput, ScheduledCalculationOutput
from takt.time_accounting.storage import MissingGoal, get_summary, load_summary

router = APIRouter(prefix="/api/v1", tags=["Personal accounting"])
DaySummary = ScheduledCalculationOutput | CalculationOutput


class StateOutput(BaseModel):
    now: AwareDatetime
    time_zone: str
    attendance: AttendanceSnapshot | None
    last_finished: AttendanceSnapshot | None
    pending: PendingDeparture | None
    summary: DaySummary | None


class TimeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    attendance_id: UUID | None = None
    expected_revision: int | None = Field(default=None, strict=True, ge=1)
    break_id: UUID | None = None
    occurred_at: AwareDatetime | None = None
    confirmed: bool = False


class PreviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attendance_id: UUID
    occurred_at: AwareDatetime | None = None


async def summary_for(
    request: Request, actor: UUID, target: UUID, day: date, clock: datetime
) -> DaySummary | None:
    async with session_factory(request.app.state.database)() as session:
        try:
            result = await get_summary(
                session,
                actor_id=actor,
                user_id=target,
                work_date=day,
                as_of=clock,
                time_zone=ZoneInfo(request.app.state.settings.time_zone),
            )
        except MissingGoal:
            return None
    if hasattr(result, "scheduled_end_at"):
        return ScheduledCalculationOutput.model_validate(result)
    return CalculationOutput.model_validate(result)


@router.get("/me/state", response_model=StateOutput, operation_id="getTimeState")
async def state(request: Request, user_id: Annotated[UUID, Depends(actor_id)]) -> StateOutput:
    zone = ZoneInfo(request.app.state.settings.time_zone)
    async with session_factory(request.app.state.database)() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await load_actor(session, user_id)
        clock = datetime.now(UTC)
        current_record = await session.scalar(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == user_id, AttendanceRecord.ended_at.is_(None))
            .options(selectinload(AttendanceRecord.breaks))
        )
        record = await session.scalar(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == user_id, AttendanceRecord.ended_at.is_not(None))
            .options(selectinload(AttendanceRecord.breaks))
            .order_by(AttendanceRecord.started_at.desc())
            .limit(1)
        )
        pending = await commands.describe_pending(
            session, current_record, now=clock, time_zone=zone
        )
        try:
            calculated = await load_summary(
                session,
                user_id=user_id,
                work_date=clock.astimezone(zone).date(),
                as_of=clock,
                time_zone=zone,
            )
            summary: DaySummary | None = (
                ScheduledCalculationOutput.model_validate(calculated)
                if hasattr(calculated, "scheduled_end_at")
                else CalculationOutput.model_validate(calculated)
            )
        except MissingGoal:
            summary = None
        return StateOutput(
            now=clock,
            time_zone=zone.key,
            attendance=AttendanceSnapshot.model_validate(current_record)
            if current_record
            else None,
            last_finished=AttendanceSnapshot.model_validate(record) if record else None,
            pending=pending,
            summary=summary,
        )


@router.get("/me/history", response_model=list[DaySummary | None], operation_id="getTimeHistory")
async def history(
    request: Request, user_id: Annotated[UUID, Depends(actor_id)]
) -> list[DaySummary | None]:
    clock = datetime.now(UTC)
    today = clock.astimezone(ZoneInfo(request.app.state.settings.time_zone)).date()
    return [
        await summary_for(request, user_id, user_id, today - timedelta(days=index), clock)
        for index in range(7)
    ]


@router.post(
    "/me/attendance/preview", response_model=CheckoutPreview, operation_id="previewDeparture"
)
async def preview(
    body: PreviewInput, request: Request, user_id: Annotated[UUID, Depends(actor_id)]
) -> CheckoutPreview:
    async with session_factory(request.app.state.database)() as session:
        return await commands.preview_checkout(
            session,
            actor_id=user_id,
            attendance_id=body.attendance_id,
            now=datetime.now(UTC),
            occurred_at=body.occurred_at,
            time_zone=ZoneInfo(request.app.state.settings.time_zone),
        )


@router.post(
    "/me/attendance/{operation}", response_model=CommandResult, operation_id="recordTimeAction"
)
async def action(
    operation: Literal["check_in", "check_out", "start_break", "end_break", "reopen"],
    body: TimeCommand,
    request: Request,
    user_id: Annotated[UUID, Depends(actor_id)],
) -> CommandResult:
    clock = datetime.now(UTC)
    zone = ZoneInfo(request.app.state.settings.time_zone)
    async with session_factory(request.app.state.database)() as session:
        if operation == "check_in":
            if (
                body.attendance_id is not None
                or body.expected_revision is not None
                or body.break_id is not None
            ):
                raise HTTPException(422, detail={"code": "unexpected_command_fields"})
            return await commands.check_in(
                session,
                actor_id=user_id,
                request_id=body.request_id,
                now=clock,
                time_zone=zone,
                occurred_at=body.occurred_at,
            )
        if body.attendance_id is None or body.expected_revision is None:
            raise HTTPException(422, detail={"code": "attendance_revision_required"})
        if operation not in {"check_out"} and (body.occurred_at is not None or body.confirmed):
            raise HTTPException(422, detail={"code": "unexpected_command_fields"})
        if operation == "end_break":
            if body.break_id is None:
                raise HTTPException(422, detail={"code": "break_required"})
            return await commands.end_break(
                session,
                actor_id=user_id,
                request_id=body.request_id,
                attendance_id=body.attendance_id,
                expected_revision=body.expected_revision,
                break_id=body.break_id,
                now=clock,
                time_zone=zone,
            )
        if body.break_id is not None:
            raise HTTPException(422, detail={"code": "unexpected_command_fields"})
        if operation == "check_out":
            return await commands.check_out(
                session,
                actor_id=user_id,
                request_id=body.request_id,
                attendance_id=body.attendance_id,
                expected_revision=body.expected_revision,
                confirmed=body.confirmed,
                occurred_at=body.occurred_at,
                now=clock,
                time_zone=zone,
            )
        if operation == "start_break":
            return await commands.start_break(
                session,
                actor_id=user_id,
                request_id=body.request_id,
                attendance_id=body.attendance_id,
                expected_revision=body.expected_revision,
                now=clock,
                time_zone=zone,
            )
        return await commands.reopen_attendance(
            session,
            actor_id=user_id,
            request_id=body.request_id,
            attendance_id=body.attendance_id,
            expected_revision=body.expected_revision,
            now=clock,
            time_zone=zone,
        )


@router.get(
    "/admin/users/{target_id}/day", response_model=DaySummary | None, operation_id="getEmployeeDay"
)
async def employee_day(
    target_id: UUID, work_date: date, request: Request, user_id: Annotated[UUID, Depends(actor_id)]
) -> DaySummary | None:
    async with session_factory(request.app.state.database)() as session, session.begin():
        actor = await load_actor(session, user_id)
        if actor.role not in {"admin", "superadmin"}:
            raise HTTPException(403, detail={"code": "admin_required"})
    return await summary_for(request, user_id, target_id, work_date, datetime.now(UTC))
