from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from takt.time_accounting.access import load_actor
from takt.time_accounting.command_schemas import (
    AttendanceSnapshot,
    CheckoutPreview,
    CommandResult,
)
from takt.time_accounting.models import (
    AttendanceRecord,
    AuditRecord,
    BreakRecord,
    CommandReceipt,
    TimeGoal,
)
from takt.time_accounting.schemas import CalculationOutput
from takt.time_accounting.storage import MissingGoal, load_summary


class CommandConflict(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class RecordNotFound(LookupError):
    pass


class ConfirmationRequired(ValueError):
    def __init__(self, *, will_end_break: bool):
        self.will_end_break = will_end_break
        super().__init__("Confirm departure and closing the current break.")


def _utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("A command timestamp must include its UTC offset.")
    return now.astimezone(UTC)


async def _record(session: AsyncSession, actor_id: UUID, attendance_id: UUID) -> AttendanceRecord:
    record = await session.scalar(
        select(AttendanceRecord)
        .where(AttendanceRecord.id == attendance_id, AttendanceRecord.user_id == actor_id)
        .options(selectinload(AttendanceRecord.breaks))
        .execution_options(populate_existing=True)
    )
    if record is None:
        raise RecordNotFound("Attendance does not exist.")
    return record


def _active_break(record: AttendanceRecord) -> BreakRecord | None:
    return next((pause for pause in record.breaks if pause.ended_at is None), None)


def _check_revision(record: AttendanceRecord, value: object) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("A positive attendance revision is required.")
    if record.revision != value:
        raise CommandConflict("stale_revision")


def _check_clock(record: AttendanceRecord, now: datetime) -> None:
    timestamps = [record.started_at]
    for pause in record.breaks:
        timestamps.append(pause.ended_at or pause.started_at)
    if now < max(timestamps):
        raise CommandConflict("event_before_latest_entry")


@dataclass(slots=True)
class _Change:
    record: AttendanceRecord
    before: AttendanceSnapshot | None = None
    closed_break_id: UUID | None = None


async def _apply(
    session: AsyncSession,
    *,
    actor_id: UUID,
    operation: str,
    parameters: dict[str, object],
    now: datetime,
    time_zone: ZoneInfo,
) -> _Change:
    if operation == "check_in":
        previous = await session.scalar(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == actor_id)
            .order_by(AttendanceRecord.started_at.desc())
            .execution_options(populate_existing=True)
            .limit(1)
        )
        if previous is not None:
            if previous.ended_at is None:
                raise CommandConflict("already_present")
            if now < previous.ended_at:
                raise CommandConflict("event_before_latest_entry")
        goal = await session.scalar(
            select(TimeGoal.id)
            .where(
                TimeGoal.user_id == actor_id,
                TimeGoal.effective_from <= now.astimezone(time_zone).date(),
            )
            .limit(1)
        )
        if goal is None:
            raise MissingGoal("Set required time before checking in.")
        record = AttendanceRecord(
            id=uuid4(), user_id=actor_id, started_at=now, revision=1, breaks=[]
        )
        session.add(record)
        return _Change(record)

    record = await _record(session, actor_id, UUID(str(parameters["attendance_id"])))
    _check_revision(record, parameters["expected_revision"])
    before = AttendanceSnapshot.model_validate(record)
    change = _Change(record, before)

    if operation == "reopen":
        if record.ended_at is None:
            raise CommandConflict("attendance_not_finished")
        if now < record.ended_at:
            raise CommandConflict("event_before_latest_entry")
        later = await session.scalar(
            select(AttendanceRecord.id)
            .where(
                AttendanceRecord.user_id == actor_id,
                AttendanceRecord.started_at > record.started_at,
            )
            .limit(1)
        )
        if later is not None:
            raise CommandConflict("later_attendance_exists")
        closing = await session.scalar(
            select(CommandReceipt).where(
                CommandReceipt.user_id == actor_id,
                CommandReceipt.attendance_id == record.id,
                CommandReceipt.operation == "check_out",
                CommandReceipt.result["attendance"]["revision"].as_integer() == record.revision,
            )
        )
        if closing is None:
            raise CommandConflict("departure_cannot_be_restored")
        closed_break_id = CommandResult.model_validate(closing.result).closed_break_id
        record.ended_at = None
        await session.flush([record])
        if closed_break_id is not None:
            pause = next((item for item in record.breaks if item.id == closed_break_id), None)
            if pause is None:
                raise CommandConflict("break_cannot_be_restored")
            pause.ended_at = None
    else:
        if record.ended_at is not None:
            raise CommandConflict("attendance_finished")
        _check_clock(record, now)
        active_break = _active_break(record)
        if operation == "start_break":
            if active_break is not None:
                raise CommandConflict("already_on_break")
            record.breaks.append(BreakRecord(id=uuid4(), attendance_id=record.id, started_at=now))
        elif operation == "end_break":
            break_id = UUID(str(parameters["break_id"]))
            if not any(pause.id == break_id for pause in record.breaks):
                raise RecordNotFound("Break does not exist.")
            if active_break is None or active_break.id != break_id:
                raise CommandConflict("break_not_active")
            if now <= active_break.started_at:
                raise CommandConflict("end_must_follow_start")
            active_break.ended_at = now
        elif operation == "check_out":
            if parameters["confirmed"] is not True:
                raise ConfirmationRequired(will_end_break=active_break is not None)
            if now <= record.started_at:
                raise CommandConflict("end_must_follow_start")
            if active_break is not None:
                if now <= active_break.started_at:
                    raise CommandConflict("end_must_follow_start")
                active_break.ended_at = now
                change.closed_break_id = active_break.id
                # The database checks parent/break bounds on each UPDATE.
                await session.flush([active_break])
            record.ended_at = now
        else:
            raise ValueError("Unknown attendance operation.")
    record.revision += 1
    return change


async def _execute(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    operation: str,
    parameters: dict[str, object],
    now: datetime,
    time_zone: ZoneInfo,
) -> CommandResult:
    now = _utc(now)
    try:
        async with session.begin():
            # All commands and target changes use the same per-account lock.
            await load_actor(session, actor_id, lock=True)
            previous = await session.get(CommandReceipt, (actor_id, request_id))
            if previous is not None:
                if previous.operation != operation or previous.parameters != parameters:
                    raise CommandConflict("request_id_reused")
                return CommandResult.model_validate(previous.result)
            change = await _apply(
                session,
                actor_id=actor_id,
                operation=operation,
                parameters=parameters,
                now=now,
                time_zone=time_zone,
            )
            await session.flush()
            result = CommandResult(
                request_id=request_id,
                attendance=AttendanceSnapshot.model_validate(change.record),
                closed_break_id=change.closed_break_id,
            )
            session.add(
                CommandReceipt(
                    user_id=actor_id,
                    request_id=request_id,
                    attendance_id=change.record.id,
                    operation=operation,
                    parameters=parameters,
                    result=result.model_dump(mode="json"),
                )
            )
            session.add(
                AuditRecord(
                    actor_id=actor_id,
                    action=operation,
                    details={
                        "request_id": str(request_id),
                        "before": change.before.model_dump(mode="json") if change.before else None,
                        "after": result.attendance.model_dump(mode="json"),
                    },
                )
            )
        return result
    except IntegrityError as exc:
        if getattr(exc.orig, "sqlstate", None) in {"23P01", "23514"}:
            raise CommandConflict("conflicting_time_entries") from exc
        raise


async def check_in(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    now: datetime,
    time_zone: ZoneInfo,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="check_in",
        parameters={},
    )


async def start_break(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    attendance_id: UUID,
    expected_revision: int,
    now: datetime,
    time_zone: ZoneInfo,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="start_break",
        parameters={
            "attendance_id": str(attendance_id),
            "expected_revision": expected_revision,
        },
    )


async def end_break(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    attendance_id: UUID,
    break_id: UUID,
    expected_revision: int,
    now: datetime,
    time_zone: ZoneInfo,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="end_break",
        parameters={
            "attendance_id": str(attendance_id),
            "break_id": str(break_id),
            "expected_revision": expected_revision,
        },
    )


async def check_out(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    attendance_id: UUID,
    expected_revision: int,
    now: datetime,
    time_zone: ZoneInfo,
    confirmed: bool = False,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="check_out",
        parameters={
            "attendance_id": str(attendance_id),
            "expected_revision": expected_revision,
            "confirmed": confirmed,
        },
    )


async def reopen_attendance(
    session: AsyncSession,
    *,
    actor_id: UUID,
    request_id: UUID,
    attendance_id: UUID,
    expected_revision: int,
    now: datetime,
    time_zone: ZoneInfo,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="reopen",
        parameters={
            "attendance_id": str(attendance_id),
            "expected_revision": expected_revision,
        },
    )


async def preview_checkout(
    session: AsyncSession,
    *,
    actor_id: UUID,
    attendance_id: UUID,
    now: datetime,
    time_zone: ZoneInfo,
) -> CheckoutPreview:
    now = _utc(now)
    async with session.begin():
        await load_actor(session, actor_id, lock=True)
        record = await _record(session, actor_id, attendance_id)
        if record.ended_at is not None:
            raise CommandConflict("attendance_finished")
        _check_clock(record, now)
        summary = await load_summary(
            session,
            user_id=actor_id,
            work_date=now.astimezone(time_zone).date(),
            as_of=now,
            time_zone=time_zone,
        )
        return CheckoutPreview(
            attendance=AttendanceSnapshot.model_validate(record),
            will_end_break=_active_break(record) is not None,
            summary=CalculationOutput.model_validate(summary),
        )


async def current_attendance(session: AsyncSession, *, actor_id: UUID) -> AttendanceSnapshot | None:
    """Restore current attendance from committed state after reopening or reconnecting."""
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await load_actor(session, actor_id)
        record = await session.scalar(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == actor_id, AttendanceRecord.ended_at.is_(None))
            .options(selectinload(AttendanceRecord.breaks))
            .execution_options(populate_existing=True)
        )
        return AttendanceSnapshot.model_validate(record) if record is not None else None
