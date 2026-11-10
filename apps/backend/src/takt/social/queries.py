from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.selectable import Subquery

from takt.social.models import Friendship
from takt.social.schemas import FriendSummary, Peer, Period, SocialStatus
from takt.time_accounting.models import AttendanceRecord, User


def peer(user: User) -> Peer:
    return Peer(id=user.id, display_name=user.display_name or "Участник", photo_url=user.photo_url)


def friend_ids(user_id: UUID) -> Select[tuple[UUID]]:
    return select(
        case((Friendship.user_low == user_id, Friendship.user_high), else_=Friendship.user_low)
    ).where(or_(Friendship.user_low == user_id, Friendship.user_high == user_id))


def period_dates(period: Period, clock: datetime, zone: ZoneInfo) -> tuple[date | None, date]:
    today = clock.astimezone(zone).date()
    if period == "week":
        return today - timedelta(days=today.weekday()), today
    if period == "month":
        return today - timedelta(days=29), today
    return None, today


def confirmed_totals(period: Period, clock: datetime, zone: ZoneInfo) -> Subquery:
    """Use closed intervals, arrival dates and the same per-day precision as accounting."""
    start, _ = period_dates(period, clock, zone)
    query = select(
        AttendanceRecord.user_id.label("user_id"),
        func.floor(
            func.sum(func.extract("epoch", AttendanceRecord.ended_at - AttendanceRecord.started_at))
        ).label("seconds"),
    ).where(AttendanceRecord.ended_at.is_not(None), AttendanceRecord.ended_at <= clock)
    if start is not None:
        lower = datetime.combine(start, time.min, zone).astimezone(UTC)
        query = query.where(AttendanceRecord.started_at >= lower)
    daily = query.group_by(
        AttendanceRecord.user_id, func.date(func.timezone(zone.key, AttendanceRecord.started_at))
    ).subquery()
    return (
        select(daily.c.user_id, func.sum(daily.c.seconds).label("seconds"))
        .group_by(daily.c.user_id)
        .subquery()
    )


async def friend_summaries(
    session: AsyncSession,
    users: list[User],
    clock: datetime,
    zone: ZoneInfo,
    period: Period = "week",
) -> list[FriendSummary]:
    if not users:
        return []
    identifiers = [user.id for user in users]
    records = (
        await session.scalars(
            select(AttendanceRecord)
            .where(
                AttendanceRecord.user_id.in_(identifiers),
                AttendanceRecord.ended_at.is_(None),
                AttendanceRecord.started_at <= clock,
            )
            .options(selectinload(AttendanceRecord.breaks))
        )
    ).all()
    current = {record.user_id: record for record in records}
    totals = confirmed_totals(period, clock, zone)
    seconds = {
        row.user_id: int(row.seconds)
        for row in await session.execute(
            select(totals.c.user_id, totals.c.seconds).where(totals.c.user_id.in_(identifiers))
        )
    }
    result = []
    for user in users:
        record = current.get(user.id)
        status: SocialStatus = "away"
        since = None
        if record is not None:
            if record.started_at.astimezone(zone).date() < clock.astimezone(zone).date():
                status = "needs_checkout"
            else:
                pause = next((item for item in record.breaks if item.ended_at is None), None)
                status = (
                    "working"
                    if pause is None
                    else "smoking"
                    if pause.kind == "smoke"
                    else "on_break"
                )
                since = pause.started_at if pause else None
        result.append(
            FriendSummary(
                **peer(user).model_dump(),
                status=status,
                status_since=since,
                confirmed_seconds=seconds.get(user.id, 0),
            )
        )
    return result
