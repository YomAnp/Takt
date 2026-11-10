import secrets
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from takt.social.errors import SocialError
from takt.social.models import FriendInvite, FriendRequest, Friendship
from takt.social.queries import friend_ids, friend_summaries, peer, period_dates
from takt.social.schemas import (
    FriendProfile,
    FriendRequestOutput,
    FriendsPage,
    InviteOutput,
    InvitePreview,
    Period,
    RequestResult,
)
from takt.time_accounting.access import AccessDenied, load_actor
from takt.time_accounting.models import AuditRecord, User


def pair(first: UUID, second: UUID) -> tuple[UUID, UUID]:
    low, high = sorted((first, second))
    return low, high


async def lock_pair(session: AsyncSession, actor: UUID, other: UUID) -> dict[UUID, User]:
    records = (
        await session.scalars(
            select(User)
            .where(User.id.in_([actor, other]))
            .order_by(User.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).all()
    users = {record.id: record for record in records}
    if actor not in users or not users[actor].is_active:
        raise AccessDenied("The account does not have access.")
    if other not in users or not users[other].is_active:
        raise SocialError("friend_not_found", 404)
    return users


def request_output(record: FriendRequest, other: User, actor: UUID) -> FriendRequestOutput:
    return FriendRequestOutput(
        id=record.id,
        user=peer(other),
        created_at=record.created_at,
        direction="outgoing" if record.requested_by == actor else "incoming",
    )


async def pending_pair(session: AsyncSession, low: UUID, high: UUID) -> FriendRequest | None:
    record: FriendRequest | None = await session.scalar(
        select(FriendRequest)
        .where(
            FriendRequest.user_low == low,
            FriendRequest.user_high == high,
            FriendRequest.status == "pending",
        )
        .execution_options(populate_existing=True)
    )
    return record


async def invite_owner(
    session: AsyncSession, token: str, clock: datetime
) -> tuple[FriendInvite, User]:
    row = (
        await session.execute(
            select(FriendInvite, User)
            .join(User, User.id == FriendInvite.user_id)
            .where(
                FriendInvite.token == token,
                FriendInvite.expires_at > clock,
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise SocialError("invite_expired", 404)
    return row[0], row[1]


async def personal_invite(
    session: AsyncSession,
    actor: UUID,
    clock: datetime,
    bot_username: str,
) -> InviteOutput:
    await load_actor(session, actor, lock=True)
    if not bot_username:
        raise SocialError("social_not_configured", 503)
    invite = await session.get(FriendInvite, actor)
    if invite is None:
        invite = FriendInvite(
            user_id=actor,
            token=secrets.token_urlsafe(24),
            created_at=clock,
            expires_at=clock + timedelta(days=7),
        )
        session.add(invite)
    elif invite.expires_at <= clock:
        invite.token = secrets.token_urlsafe(24)
        invite.created_at = clock
        invite.expires_at = clock + timedelta(days=7)
    return InviteOutput(
        token=invite.token,
        url=f"https://t.me/{bot_username}?start=friend_{invite.token}",
        expires_at=invite.expires_at,
    )


async def preview_invite(
    session: AsyncSession, actor: UUID, token: str, clock: datetime
) -> InvitePreview:
    await load_actor(session, actor)
    invite, owner = await invite_owner(session, token, clock)
    low, high = pair(actor, owner.id)
    friendship = await session.get(Friendship, (low, high)) if low != high else None
    pending = await pending_pair(session, low, high) if low != high else None
    return InvitePreview(
        user=peer(owner),
        expires_at=invite.expires_at,
        is_self=actor == owner.id,
        already_friends=friendship is not None,
        pending_request_id=pending.id if pending else None,
    )


async def send_request(
    session: AsyncSession, actor: UUID, token: str, clock: datetime
) -> RequestResult:
    _, owner = await invite_owner(session, token, clock)
    if actor == owner.id:
        raise SocialError("invite_self", 422)
    users = await lock_pair(session, actor, owner.id)
    low, high = pair(actor, owner.id)
    if await session.get(Friendship, (low, high)) is not None:
        return RequestResult(request=None, status="accepted")
    existing = await pending_pair(session, low, high)
    if existing is not None:
        result = request_output(existing, users[owner.id], actor)
        return RequestResult(request=result, status=result.direction)
    recent_decline = await session.scalar(
        select(FriendRequest.id)
        .where(
            FriendRequest.user_low == low,
            FriendRequest.user_high == high,
            FriendRequest.status == "declined",
            FriendRequest.updated_at > clock - timedelta(hours=24),
        )
        .limit(1)
    )
    if recent_decline is not None:
        raise SocialError("friend_request_cooldown", 429)
    sent = await session.scalar(
        select(func.count())
        .select_from(FriendRequest)
        .where(
            FriendRequest.requested_by == actor,
            FriendRequest.created_at > clock - timedelta(hours=24),
        )
    )
    outgoing = await session.scalar(
        select(func.count())
        .select_from(FriendRequest)
        .where(
            FriendRequest.requested_by == actor,
            FriendRequest.status == "pending",
            FriendRequest.user_low.in_(select(User.id).where(User.is_active.is_(True))),
            FriendRequest.user_high.in_(select(User.id).where(User.is_active.is_(True))),
        )
    )
    if (sent or 0) >= 20 or (outgoing or 0) >= 20:
        raise SocialError("friend_request_limit", 429)
    incoming = await session.scalar(
        select(func.count())
        .select_from(FriendRequest)
        .where(
            or_(FriendRequest.user_low == owner.id, FriendRequest.user_high == owner.id),
            FriendRequest.requested_by != owner.id,
            FriendRequest.status == "pending",
            FriendRequest.requested_by.in_(select(User.id).where(User.is_active.is_(True))),
        )
    )
    if (incoming or 0) >= 100:
        raise SocialError("friend_requests_full", 429)
    record = FriendRequest(
        id=uuid4(),
        user_low=low,
        user_high=high,
        requested_by=actor,
        status="pending",
        created_at=clock,
        updated_at=clock,
    )
    session.add(record)
    session.add(
        AuditRecord(
            actor_id=actor,
            action="friend_request_sent",
            details={"request_id": str(record.id), "user_id": str(owner.id)},
        )
    )
    return RequestResult(request=request_output(record, users[owner.id], actor), status="outgoing")


async def respond(
    session: AsyncSession,
    actor: UUID,
    request_id: UUID,
    action: Literal["accept", "decline", "cancel"],
    clock: datetime,
) -> None:
    record = await session.get(FriendRequest, request_id)
    if record is None or actor not in {record.user_low, record.user_high}:
        raise SocialError("friend_request_not_found", 404)
    other = record.user_high if actor == record.user_low else record.user_low
    await lock_pair(session, actor, other)
    record = await session.get(
        FriendRequest, request_id, with_for_update=True, populate_existing=True
    )
    assert record is not None
    if (action == "cancel") != (record.requested_by == actor):
        raise SocialError("friend_request_not_found", 404)
    target = {"accept": "accepted", "decline": "declined", "cancel": "cancelled"}[action]
    if record.status == target:
        return
    if record.status != "pending":
        raise SocialError("friend_request_not_pending", 409)
    record.status = target
    record.updated_at = clock
    if action == "accept":
        session.add(
            Friendship(user_low=record.user_low, user_high=record.user_high, created_at=clock)
        )
    session.add(
        AuditRecord(
            actor_id=actor,
            action="friend_request_" + target,
            details={"request_id": str(record.id), "user_id": str(other)},
        )
    )


async def remove_friend(
    session: AsyncSession,
    actor: UUID,
    other: UUID,
    *,
    friendship_id: UUID | None = None,
) -> None:
    await lock_pair(session, actor, other)
    record = await session.get(Friendship, pair(actor, other))
    if record is not None:
        if friendship_id is not None and record.id != friendship_id:
            raise SocialError("friendship_changed")
        await session.delete(record)
        session.add(
            AuditRecord(actor_id=actor, action="friend_removed", details={"user_id": str(other)})
        )


async def friends_page(
    session: AsyncSession,
    actor: UUID,
    clock: datetime,
    zone: ZoneInfo,
    offset: int,
) -> FriendsPage:
    await load_actor(session, actor)
    base = select(User).where(User.id.in_(friend_ids(actor)), User.is_active.is_(True))
    users = list(
        (
            await session.scalars(
                base.order_by(func.lower(User.display_name), User.id).offset(offset).limit(30)
            )
        ).all()
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    requests = (
        await session.scalars(
            select(FriendRequest)
            .where(
                or_(FriendRequest.user_low == actor, FriendRequest.user_high == actor),
                FriendRequest.status == "pending",
            )
            .order_by(FriendRequest.created_at.desc(), FriendRequest.id)
            .limit(120)
        )
    ).all()
    identifiers = [
        record.user_high if record.user_low == actor else record.user_low for record in requests
    ]
    others = {
        user.id: user
        for user in await session.scalars(
            select(User).where(User.id.in_(identifiers), User.is_active.is_(True))
        )
    }
    incoming: list[FriendRequestOutput] = []
    outgoing: list[FriendRequestOutput] = []
    for record in requests:
        other_id = record.user_high if record.user_low == actor else record.user_low
        if other_id not in others:
            continue
        output = request_output(record, others[other_id], actor)
        (outgoing if output.direction == "outgoing" else incoming).append(output)
    items = await friend_summaries(session, users, clock, zone)
    identifiers = [user.id for user in users]
    edges = (
        await session.scalars(
            select(Friendship).where(
                or_(
                    and_(Friendship.user_low == actor, Friendship.user_high.in_(identifiers)),
                    and_(Friendship.user_high == actor, Friendship.user_low.in_(identifiers)),
                )
            )
        )
    ).all()
    edge_ids = {
        (edge.user_high if edge.user_low == actor else edge.user_low): edge.id for edge in edges
    }
    return FriendsPage(
        items=[item.model_copy(update={"friendship_id": edge_ids[item.id]}) for item in items],
        total=total or 0,
        incoming=incoming,
        outgoing=outgoing,
        as_of=clock,
    )


async def friend_profile(
    session: AsyncSession,
    actor: UUID,
    other: UUID,
    clock: datetime,
    zone: ZoneInfo,
    period: Period,
) -> FriendProfile:
    await load_actor(session, actor)
    friendship = await session.get(Friendship, pair(actor, other))
    if friendship is None:
        raise SocialError("friend_not_found", 404)
    user = await session.scalar(select(User).where(User.id == other, User.is_active.is_(True)))
    if user is None:
        raise SocialError("friend_not_found", 404)
    summary = (await friend_summaries(session, [user], clock, zone, period))[0]
    start, end = period_dates(period, clock, zone)
    return FriendProfile(
        **summary.model_dump(exclude={"friendship_id"}),
        friendship_id=friendship.id,
        period_start=start,
        period_end=end,
    )
