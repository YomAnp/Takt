from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from takt.time_accounting.calculation import Attendance, Break, Summary, calculate
from takt.time_accounting.models import AttendanceRecord, AuditRecord, TimeGoal, User


class AccessDenied(PermissionError):
    pass


class MissingGoal(ValueError):
    pass


async def _actor(session: AsyncSession, actor_id: UUID, *, lock: bool = False) -> User:
    query = select(User).where(User.id == actor_id)
    if lock:
        query = query.with_for_update()
    actor = await session.scalar(query)
    if actor is None or not actor.is_active:
        raise AccessDenied("The account does not have access.")
    return actor


async def set_goal(
    session: AsyncSession,
    *,
    actor_id: UUID,
    required_minutes: int,
    now: datetime,
    time_zone: ZoneInfo,
) -> None:
    """Change the actor's target from today onward; retain earlier effective dates."""
    if isinstance(required_minutes, bool) or not 1 <= required_minutes <= 1440:
        raise ValueError("Required time must be between 1 and 1440 minutes.")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("The change timestamp must include its UTC offset.")
    effective_from = now.astimezone(time_zone).date()
    async with session.begin():
        await _actor(session, actor_id, lock=True)
        old_goal = await session.scalar(
            select(TimeGoal.required_minutes)
            .where(TimeGoal.user_id == actor_id, TimeGoal.effective_from <= effective_from)
            .order_by(TimeGoal.effective_from.desc())
            .limit(1)
        )
        if old_goal == required_minutes:
            return
        await session.execute(
            insert(TimeGoal)
            .values(
                user_id=actor_id, effective_from=effective_from, required_minutes=required_minutes
            )
            .on_conflict_do_update(
                index_elements=[TimeGoal.user_id, TimeGoal.effective_from],
                set_={"required_minutes": required_minutes},
            )
        )
        session.add(
            AuditRecord(
                actor_id=actor_id,
                action="time_goal_changed",
                details={
                    "previous_minutes": old_goal,
                    "required_minutes": required_minutes,
                    "effective_from": effective_from.isoformat(),
                },
            )
        )


async def get_summary(
    session: AsyncSession,
    *,
    actor_id: UUID,
    user_id: UUID,
    work_date: date,
    as_of: datetime,
    time_zone: ZoneInfo,
) -> Summary:
    """Read personal accounting, or any employee's accounting for an active admin."""
    async with session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        actor = await _actor(session, actor_id)
        if actor_id != user_id and actor.role != "admin":
            raise AccessDenied("Only an administrator can read another account's records.")
        goal = await session.scalar(
            select(TimeGoal.required_minutes)
            .where(TimeGoal.user_id == user_id, TimeGoal.effective_from <= work_date)
            .order_by(TimeGoal.effective_from.desc())
            .limit(1)
        )
        if goal is None:
            raise MissingGoal("No required time was set for this date.")
        day_start = datetime.combine(work_date, time.min, time_zone)
        day_end = datetime.combine(work_date + timedelta(days=1), time.min, time_zone)
        records = (
            await session.scalars(
                select(AttendanceRecord)
                .where(
                    AttendanceRecord.user_id == user_id,
                    AttendanceRecord.started_at < day_end,
                    or_(AttendanceRecord.ended_at.is_(None), AttendanceRecord.ended_at > day_start),
                )
                .options(selectinload(AttendanceRecord.breaks))
                .order_by(AttendanceRecord.started_at)
            )
        ).all()
        return calculate(
            work_date=work_date,
            required_minutes=goal,
            as_of=as_of,
            time_zone=time_zone,
            intervals=tuple(
                Attendance(
                    started_at=record.started_at,
                    ended_at=record.ended_at,
                    breaks=tuple(
                        Break(pause.started_at, pause.ended_at) for pause in record.breaks
                    ),
                )
                for record in records
            ),
        )
