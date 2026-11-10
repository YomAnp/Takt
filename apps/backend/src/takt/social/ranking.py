from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from takt.social.queries import confirmed_totals, friend_ids, period_dates
from takt.social.schemas import LeaderboardEntry, LeaderboardPage, Peer, Period, Scope
from takt.time_accounting.access import load_actor
from takt.time_accounting.models import User


async def leaderboard(
    session: AsyncSession,
    user_id: UUID,
    *,
    clock: datetime,
    zone: ZoneInfo,
    scope: Scope,
    period: Period,
    offset: int,
) -> LeaderboardPage:
    actor = await load_actor(session, user_id)
    totals = confirmed_totals(period, clock, zone)
    query = (
        select(
            User.id.label("id"),
            User.display_name,
            User.photo_url,
            totals.c.seconds,
            func.rank().over(order_by=totals.c.seconds.desc()).label("rank"),
        )
        .join(totals, totals.c.user_id == User.id)
        .where(User.is_active.is_(True), totals.c.seconds > 0)
    )
    if scope == "global":
        query = query.where(User.leaderboard_enabled.is_(True))
    else:
        query = query.where(or_(User.id == user_id, User.id.in_(friend_ids(user_id))))
    ranked = query.subquery()
    page = (
        (
            await session.execute(
                select(ranked)
                .order_by(ranked.c.seconds.desc(), func.lower(ranked.c.display_name), ranked.c.id)
                .offset(offset)
                .limit(30)
            )
        )
        .mappings()
        .all()
    )
    own = (
        (await session.execute(select(ranked).where(ranked.c.id == user_id)))
        .mappings()
        .one_or_none()
    )
    total = await session.scalar(select(func.count()).select_from(ranked))
    items = [
        LeaderboardEntry(
            rank=int(row["rank"]),
            user=Peer(
                id=row["id"],
                display_name=row["display_name"] or "Участник",
                photo_url=row["photo_url"],
            ),
            seconds=int(row["seconds"]),
            is_self=row["id"] == user_id,
        )
        for row in page
    ]
    current = (
        None
        if own is None
        else LeaderboardEntry(
            rank=int(own["rank"]),
            user=Peer(
                id=own["id"],
                display_name=own["display_name"] or "Участник",
                photo_url=own["photo_url"],
            ),
            seconds=int(own["seconds"]),
            is_self=True,
        )
    )
    start, end = period_dates(period, clock, zone)
    return LeaderboardPage(
        items=items,
        total=total or 0,
        current_user=current,
        scope=scope,
        period=period,
        period_start=start,
        period_end=end,
        participating=actor.leaderboard_enabled if scope == "global" else True,
        as_of=clock,
    )
