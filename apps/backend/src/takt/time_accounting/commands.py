from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from takt.time_accounting.access import load_actor
from takt.time_accounting.calculation import ScheduledSummary
from takt.time_accounting.command_schemas import (
    AttendanceSnapshot,
    CheckoutPreview,
    CommandResult,
    PendingDeparture,
)
from takt.time_accounting.models import (
    AttendanceRecord,
    AuditRecord,
    BreakRecord,
    CommandReceipt,
    TimeGoal,
    WorkSchedule,
)
from takt.time_accounting.schemas import CalculationOutput, ScheduledCalculationOutput
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


def _event_parameters(
    parameters: dict[str, object], occurred_at: datetime | None
) -> dict[str, object]:
    if occurred_at is not None:
        parameters["occurred_at"] = _utc(occurred_at).isoformat()
    return parameters


def _event_time(parameters: dict[str, object], now: datetime) -> datetime:
    value = parameters.get("occurred_at")
    result = _utc(datetime.fromisoformat(str(value))) if value is not None else now
    if result > now:
        raise CommandConflict("event_in_future")
    return result


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


def _check_departure(record: AttendanceRecord, event_at: datetime) -> None:
    _check_clock(record, event_at)
    pause = _active_break(record)
    if event_at <= record.started_at or (pause is not None and event_at <= pause.started_at):
        raise CommandConflict("end_must_follow_start")


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
    event_at = _event_time(parameters, now)
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
            if event_at < previous.ended_at:
                raise CommandConflict("event_before_latest_entry")
        goal = await session.scalar(
            select(TimeGoal.id)
            .where(
                TimeGoal.user_id == actor_id,
                TimeGoal.effective_from <= event_at.astimezone(time_zone).date(),
            )
            .limit(1)
        )
        if goal is None:
            goal = await session.scalar(
                select(WorkSchedule.id)
                .where(
                    WorkSchedule.user_id == actor_id,
                    WorkSchedule.effective_from <= event_at.astimezone(time_zone).date(),
                )
                .limit(1)
            )
        if goal is None:
            raise MissingGoal("Set the working-day end time before checking in.")
        record = AttendanceRecord(
            id=uuid4(), user_id=actor_id, started_at=event_at, revision=1, breaks=[]
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
        if event_at < record.ended_at:
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
        _check_clock(record, event_at)
        active_break = _active_break(record)
        if operation == "start_break":
            if active_break is not None:
                raise CommandConflict("already_on_break")
            record.breaks.append(
                BreakRecord(id=uuid4(), attendance_id=record.id, started_at=event_at)
            )
        elif operation == "end_break":
            break_id = UUID(str(parameters["break_id"]))
            if not any(pause.id == break_id for pause in record.breaks):
                raise RecordNotFound("Break does not exist.")
            if active_break is None or active_break.id != break_id:
                raise CommandConflict("break_not_active")
            if event_at <= active_break.started_at:
                raise CommandConflict("end_must_follow_start")
            active_break.ended_at = event_at
        elif operation == "check_out":
            if parameters["confirmed"] is not True:
                raise ConfirmationRequired(will_end_break=active_break is not None)
            _check_departure(record, event_at)
            if active_break is not None:
                active_break.ended_at = event_at
                change.closed_break_id = active_break.id
                # The database checks parent/break bounds on each UPDATE.
                await session.flush([active_break])
            record.ended_at = event_at
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
                        "recorded_at": now.isoformat(),
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
    occurred_at: datetime | None = None,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="check_in",
        parameters=_event_parameters({}, occurred_at),
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
    occurred_at: datetime | None = None,
) -> CommandResult:
    return await _execute(
        session,
        actor_id=actor_id,
        request_id=request_id,
        now=now,
        time_zone=time_zone,
        operation="check_out",
        parameters=_event_parameters(
            {
                "attendance_id": str(attendance_id),
                "expected_revision": expected_revision,
                "confirmed": confirmed,
            },
            occurred_at,
        ),
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
    occurred_at: datetime | None = None,
) -> CheckoutPreview:
    now = _utc(now)
    event_at = _event_time(_event_parameters({}, occurred_at), now)
    async with session.begin():
        await load_actor(session, actor_id, lock=True)
        record = await _record(session, actor_id, attendance_id)
        if record.ended_at is not None:
            raise CommandConflict("attendance_finished")
        _check_departure(record, event_at)
        summary = await load_summary(
            session,
            user_id=actor_id,
            work_date=record.started_at.astimezone(time_zone).date(),
            as_of=now,
            time_zone=time_zone,
            proposed_checkout=(record.id, event_at),
        )
        return CheckoutPreview(
            attendance=AttendanceSnapshot.model_validate(record),
            will_end_break=_active_break(record) is not None,
            summary=(
                ScheduledCalculationOutput.model_validate(summary)
                if isinstance(summary, ScheduledSummary)
                else CalculationOutput.model_validate(summary)
            ),
            proposed_end_at=event_at,
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


async def pending_departure(
    session: AsyncSession, *, actor_id: UUID, now: datetime, time_zone: ZoneInfo
) -> PendingDeparture | None:
    now = _utc(now)
    async with session.begin():
        await load_actor(session, actor_id, lock=True)
        record = await session.scalar(
            select(AttendanceRecord)
            .where(AttendanceRecord.user_id == actor_id, AttendanceRecord.ended_at.is_(None))
            .options(selectinload(AttendanceRecord.breaks))
            .execution_options(populate_existing=True)
        )
        return await describe_pending(session, record, now=now, time_zone=time_zone)


async def describe_pending(
    session: AsyncSession,
    record: AttendanceRecord | None,
    *,
    now: datetime,
    time_zone: ZoneInfo,
) -> PendingDeparture | None:
    """Describe recovery inside the caller's authorized snapshot transaction."""
    if record is None:
        return None
    work_date = record.started_at.astimezone(time_zone).date()
    if work_date >= now.astimezone(time_zone).date():
        return None
    end_time = await session.scalar(
        select(WorkSchedule.end_time)
        .where(WorkSchedule.user_id == record.user_id, WorkSchedule.effective_from <= work_date)
        .order_by(WorkSchedule.effective_from.desc())
        .limit(1)
    )
    ending = datetime.combine(work_date, end_time, time_zone).astimezone(UTC) if end_time else None
    can_use = ending is not None and record.started_at < ending <= now
    if can_use and ending is not None:
        try:
            _check_clock(record, ending)
            pause = _active_break(record)
            can_use = pause is None or ending > pause.started_at
        except CommandConflict:
            can_use = False
    return PendingDeparture(
        attendance=AttendanceSnapshot.model_validate(record),
        work_date=work_date,
        scheduled_end_at=ending,
        can_use_scheduled_end=can_use,
    )
