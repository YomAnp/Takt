from datetime import datetime, time
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from takt.time_accounting.access import load_actor
from takt.time_accounting.models import AuditRecord, WorkSchedule


async def set_schedule(
    session: AsyncSession,
    *,
    actor_id: UUID,
    end_time: time,
    now: datetime,
    time_zone: ZoneInfo,
) -> None:
    """Keep one local ending time until the user changes it; preserve earlier dates."""
    if end_time.tzinfo is not None or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Use a local ending time and an offset-aware change timestamp.")
    effective_from = now.astimezone(time_zone).date()
    async with session.begin():
        await load_actor(session, actor_id, lock=True)
        previous = await session.scalar(
            select(WorkSchedule.end_time)
            .where(
                WorkSchedule.user_id == actor_id,
                WorkSchedule.effective_from <= effective_from,
            )
            .order_by(WorkSchedule.effective_from.desc())
            .limit(1)
        )
        if previous == end_time:
            return
        await session.execute(
            insert(WorkSchedule)
            .values(
                user_id=actor_id,
                effective_from=effective_from,
                end_time=end_time,
            )
            .on_conflict_do_update(
                index_elements=[WorkSchedule.user_id, WorkSchedule.effective_from],
                set_={"end_time": end_time},
            )
        )
        session.add(
            AuditRecord(
                actor_id=actor_id,
                action="work_schedule_changed",
                details={
                    "previous_end_time": previous.isoformat() if previous else None,
                    "end_time": end_time.isoformat(),
                    "effective_from": effective_from.isoformat(),
                },
            )
        )
