import asyncio
from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from takt.database import session_factory
from takt.social import friends
from takt.social.errors import SocialError
from takt.social.models import FriendRequest, Friendship
from takt.social.queries import period_dates
from takt.social.ranking import leaderboard
from takt.time_accounting import commands
from takt.time_accounting.access import AccessDenied
from takt.time_accounting.models import (
    AttendanceRecord,
    AuditRecord,
    BreakRecord,
    User,
    WorkSchedule,
)
from takt.time_accounting.storage import get_summary

from .helpers import client_for
from .test_identity import config, enter

ZONE = ZoneInfo("Europe/Moscow")
CLOCK = datetime(2026, 11, 10, 18, tzinfo=ZONE)


def at(value: str) -> datetime:
    return datetime.fromisoformat("2026-11-10T" + value + "+03:00")


@pytest_asyncio.fixture
async def make_users(database):
    identifiers = []

    async def make(count=1, *, participating=False, active=True):
        result = []
        async with session_factory(database)() as session, session.begin():
            for index in range(count):
                identifier = uuid4()
                user = User(
                    id=identifier,
                    telegram_id=int(identifier.int % 10**12),
                    display_name=f"Employee {index}",
                    telegram_username=f"employee_{identifier.hex[:10]}",
                    leaderboard_enabled=participating,
                    is_active=active,
                    onboarded_at=CLOCK - timedelta(days=90),
                )
                session.add(user)
                await session.flush()
                session.add(
                    WorkSchedule(
                        user_id=user.id, effective_from=date(2026, 1, 1), end_time=time(18)
                    )
                )
                result.append(user)
                identifiers.append(user.id)
        return result

    yield make
    # Other test modules share the database; only this test's users leave the ranking.
    async with session_factory(database)() as session, session.begin():
        if identifiers:
            await session.execute(
                update(User).where(User.id.in_(identifiers)).values(leaderboard_enabled=False)
            )


async def service(database, operation, *args, **kwargs):
    async with session_factory(database)() as session, session.begin():
        return await operation(session, *args, **kwargs)


async def invite(database, user, clock=CLOCK):
    return await service(database, friends.personal_invite, user.id, clock, "takt_test_bot")


async def connect(database, first, second, clock=CLOCK):
    link = await invite(database, second, clock)
    sent = await service(database, friends.send_request, first.id, link.token, clock)
    await service(database, friends.respond, second.id, sent.request.id, "accept", clock)
    return sent.request.id


async def attendance(database, user, started, ended, *, pause=None):
    async with session_factory(database)() as session, session.begin():
        record = AttendanceRecord(user_id=user.id, started_at=started, ended_at=ended)
        session.add(record)
        await session.flush()
        if pause is not None:
            session.add(
                BreakRecord(attendance_id=record.id, started_at=pause[0], ended_at=pause[1])
            )
        return record.id


async def ranking(database, user, *, period="week", scope="global", offset=0, clock=CLOCK):
    return await service(
        database,
        leaderboard,
        user.id,
        clock=clock,
        zone=ZONE,
        scope=scope,
        period=period,
        offset=offset,
    )


@pytest.mark.asyncio
async def test_friendship_http_flow_requires_mutual_consent_and_keeps_work_records_private(
    database, make_users
):
    first, second, outsider = await make_users(3)
    async with client_for(config(database, bot_username="takt_test_bot")) as client:
        first_auth, _ = await enter(client, first.telegram_id, first.telegram_username)
        second_auth, _ = await enter(client, second.telegram_id, second.telegram_username)
        outsider_auth, _ = await enter(client, outsider.telegram_id, outsider.telegram_username)
        assert (await client.get("/api/v1/social/friends")).status_code == 401
        link = await client.post("/api/v1/social/invite", headers=second_auth)
        assert link.status_code == 200
        token = link.json()["token"]
        assert link.json()["url"] == "https://t.me/takt_test_bot?start=friend_" + token
        preview = await client.get("/api/v1/social/invites/" + token, headers=first_auth)
        assert preview.status_code == 200
        assert set(preview.json()["user"]) == {"id", "display_name", "photo_url"}
        assert preview.json()["already_friends"] is False
        assert (
            await client.get("/api/v1/social/friends/" + str(second.id), headers=first_auth)
        ).status_code == 404
        sent = await client.post(
            "/api/v1/social/requests", headers=first_auth, json={"invite_token": token}
        )
        assert sent.status_code == 200 and sent.json()["status"] == "outgoing"
        request_id = sent.json()["request"]["id"]
        repeated = await client.post(
            "/api/v1/social/requests", headers=first_auth, json={"invite_token": token}
        )
        assert repeated.json()["request"]["id"] == request_id
        assert (
            await client.post(f"/api/v1/social/requests/{request_id}/accept", headers=first_auth)
        ).status_code == 404
        assert (
            await client.post(f"/api/v1/social/requests/{request_id}/accept", headers=outsider_auth)
        ).status_code == 404
        page = (await client.get("/api/v1/social/friends", headers=second_auth)).json()
        assert page["items"] == [] and page["incoming"][0]["id"] == request_id
        assert (
            await client.post(f"/api/v1/social/requests/{request_id}/accept", headers=second_auth)
        ).status_code == 204
        own = (await client.get("/api/v1/social/friends", headers=first_auth)).json()
        assert own["total"] == 1 and own["items"][0]["id"] == str(second.id)
        profile = await client.get("/api/v1/social/friends/" + str(second.id), headers=first_auth)
        assert profile.status_code == 200
        assert {
            "telegram_id",
            "telegram_username",
            "breaks",
            "attendance",
            "started_at",
            "ended_at",
        }.isdisjoint(profile.json())
        private = await client.get(
            f"/api/v1/admin/users/{second.id}/day?work_date=2026-11-10", headers=first_auth
        )
        assert private.status_code == 403
        assert (
            await client.get("/api/v1/social/friends/" + str(second.id), headers=outsider_auth)
        ).status_code == 404
        assert (
            await client.delete("/api/v1/social/friends/" + str(second.id), headers=first_auth)
        ).status_code == 204
        # A delayed retry of the original acceptance cannot recreate a removed friend.
        assert (
            await client.post(f"/api/v1/social/requests/{request_id}/accept", headers=second_auth)
        ).status_code == 204
        assert (await client.get("/api/v1/social/friends", headers=first_auth)).json()["total"] == 0


@pytest.mark.asyncio
async def test_concurrent_reciprocal_requests_and_accepts_create_one_friendship(
    database, make_users
):
    first, second = await make_users(2)
    first_link, second_link = await asyncio.gather(
        invite(database, first), invite(database, second)
    )
    results = await asyncio.gather(
        service(database, friends.send_request, first.id, second_link.token, CLOCK),
        service(database, friends.send_request, second.id, first_link.token, CLOCK),
        service(database, friends.send_request, first.id, second_link.token, CLOCK),
    )
    assert len({result.request.id for result in results}) == 1
    assert {result.status for result in results} == {"incoming", "outgoing"}
    request_id = results[0].request.id
    async with session_factory(database)() as session:
        request = await session.get(FriendRequest, request_id)
        recipient = second if request.requested_by == first.id else first
    await asyncio.gather(
        service(database, friends.respond, recipient.id, request_id, "accept", CLOCK),
        service(database, friends.respond, recipient.id, request_id, "accept", CLOCK),
    )
    async with session_factory(database)() as session:
        low, high = friends.pair(first.id, second.id)
        count = await session.scalar(
            select(func.count())
            .select_from(Friendship)
            .where(
                Friendship.user_low == low,
                Friendship.user_high == high,
            )
        )
        audit = await session.scalar(
            select(func.count())
            .select_from(AuditRecord)
            .where(
                AuditRecord.actor_id == recipient.id,
                AuditRecord.action == "friend_request_accepted",
            )
        )
        assert count == audit == 1


@pytest.mark.asyncio
async def test_decline_cancel_and_old_accept_have_no_effect_on_new_request(database, make_users):
    first, second, stranger = await make_users(3)
    link = await invite(database, second)
    sent = await service(database, friends.send_request, first.id, link.token, CLOCK)
    with pytest.raises(SocialError, match="friend_request_not_found"):
        await service(database, friends.respond, second.id, sent.request.id, "cancel", CLOCK)
    with pytest.raises(SocialError, match="friend_request_not_found"):
        await service(database, friends.respond, stranger.id, sent.request.id, "decline", CLOCK)
    await service(database, friends.respond, first.id, sent.request.id, "cancel", CLOCK)
    new = await service(database, friends.send_request, first.id, link.token, CLOCK)
    assert new.request.id != sent.request.id
    with pytest.raises(SocialError, match="friend_request_not_pending"):
        await service(database, friends.respond, second.id, sent.request.id, "accept", CLOCK)
    await service(database, friends.respond, second.id, new.request.id, "decline", CLOCK)
    with pytest.raises(SocialError, match="friend_request_cooldown") as limited:
        await service(database, friends.send_request, first.id, link.token, CLOCK)
    assert limited.value.status == 429
    retry = await service(
        database, friends.send_request, first.id, link.token, CLOCK + timedelta(hours=25)
    )
    await service(
        database,
        friends.respond,
        second.id,
        retry.request.id,
        "accept",
        CLOCK + timedelta(hours=25),
    )
    await service(database, friends.remove_friend, first.id, second.id)
    another = await service(
        database, friends.send_request, first.id, link.token, CLOCK + timedelta(hours=25)
    )
    await service(
        database,
        friends.respond,
        second.id,
        retry.request.id,
        "accept",
        CLOCK + timedelta(hours=25),
    )
    async with session_factory(database)() as session:
        assert await session.get(Friendship, friends.pair(first.id, second.id)) is None
        assert (await session.get(FriendRequest, another.request.id)).status == "pending"


@pytest.mark.asyncio
async def test_delayed_remove_cannot_delete_a_recreated_friendship(database, make_users):
    first, second = await make_users(2)
    original_request = await connect(database, first, second)
    pair = friends.pair(first.id, second.id)
    async with session_factory(database)() as session:
        original_id = (await session.get(Friendship, pair)).id
    await service(database, friends.remove_friend, first.id, second.id, friendship_id=original_id)
    # Retrying a completed deletion is harmless before a new friendship exists.
    await service(database, friends.remove_friend, first.id, second.id, friendship_id=original_id)
    new_request = await connect(database, first, second)
    assert new_request != original_request
    async with session_factory(database)() as session:
        recreated_id = (await session.get(Friendship, pair)).id
    assert recreated_id != original_id
    with pytest.raises(SocialError, match="friendship_changed") as changed:
        await service(
            database, friends.remove_friend, first.id, second.id, friendship_id=original_id
        )
    assert changed.value.status == 409
    async with session_factory(database)() as session:
        assert (await session.get(Friendship, pair)).id == recreated_id
    page = await service(database, friends.friends_page, first.id, CLOCK, ZONE, 0)
    assert page.items[0].friendship_id == recreated_id


@pytest.mark.asyncio
async def test_invite_expiry_rotates_token_and_rejects_self_request(database, make_users):
    first, second = await make_users(2)
    original = await invite(database, first)
    unchanged = await invite(database, first, CLOCK + timedelta(days=6))
    assert unchanged.token == original.token
    assert original.expires_at == CLOCK + timedelta(days=7)
    with pytest.raises(SocialError, match="invite_self"):
        await service(database, friends.send_request, first.id, original.token, CLOCK)
    expired = CLOCK + timedelta(days=7)
    with pytest.raises(SocialError, match="invite_expired"):
        await service(database, friends.preview_invite, second.id, original.token, expired)
    fresh = await invite(database, first, expired)
    assert fresh.token != original.token
    assert fresh.expires_at == expired + timedelta(days=7)
    with pytest.raises(SocialError, match="invite_expired"):
        await service(database, friends.send_request, second.id, original.token, expired)


@pytest.mark.asyncio
async def test_concurrent_request_limit_cannot_be_bypassed_by_cancel(database, make_users):
    users = await make_users(22)
    actor, targets = users[0], users[1:]
    links = [await invite(database, target) for target in targets]
    results = await asyncio.gather(
        *(service(database, friends.send_request, actor.id, link.token, CLOCK) for link in links),
        return_exceptions=True,
    )
    accepted = [result for result in results if not isinstance(result, Exception)]
    rejected = [result for result in results if isinstance(result, SocialError)]
    assert len(accepted) == 20 and len(rejected) == 1
    assert rejected[0].code == "friend_request_limit" and rejected[0].status == 429
    await service(database, friends.respond, actor.id, accepted[0].request.id, "cancel", CLOCK)
    unused = next(
        link for link, result in zip(links, results, strict=True) if isinstance(result, SocialError)
    )
    with pytest.raises(SocialError, match="friend_request_limit"):
        await service(database, friends.send_request, actor.id, unused.token, CLOCK)
    later = await service(
        database, friends.send_request, actor.id, unused.token, CLOCK + timedelta(hours=25)
    )
    assert later.status == "outgoing"


@pytest.mark.asyncio
async def test_blocked_accounts_disappear_from_friends_invites_and_ranking(database, make_users):
    first, second = await make_users(2, participating=True)
    await connect(database, first, second)
    link = await invite(database, second)
    await attendance(database, second, at("09:00"), at("12:00"))
    async with session_factory(database)() as session, session.begin():
        await session.execute(update(User).where(User.id == second.id).values(is_active=False))
    page = await service(database, friends.friends_page, first.id, CLOCK, ZONE, 0)
    assert page.total == 0 and not page.items
    with pytest.raises(SocialError, match="friend_not_found"):
        await service(database, friends.friend_profile, first.id, second.id, CLOCK, ZONE, "week")
    with pytest.raises(SocialError, match="invite_expired"):
        await service(database, friends.preview_invite, first.id, link.token, CLOCK)
    with pytest.raises(AccessDenied):
        await service(database, friends.friends_page, second.id, CLOCK, ZONE, 0)
    result = await ranking(database, first)
    assert second.id not in {entry.user.id for entry in result.items}


async def time_command(database, operation, user, clock, previous=None, **kwargs):
    if previous is not None:
        kwargs.update(
            attendance_id=previous.attendance.id, expected_revision=previous.attendance.revision
        )
    async with session_factory(database)() as session:
        return await operation(
            session, actor_id=user.id, request_id=uuid4(), now=clock, time_zone=ZONE, **kwargs
        )


@pytest.mark.asyncio
async def test_smoking_counts_as_presence_and_checkout_undo_restores_its_kind(database, make_users):
    first, second = await make_users(2)
    await connect(database, first, second)
    arrival = await time_command(database, commands.check_in, second, at("09:00"))
    paused = await time_command(
        database, commands.start_break, second, at("12:00"), arrival, kind="smoke"
    )
    page = await service(database, friends.friends_page, first.id, at("12:15"), ZONE, 0)
    assert page.items[0].status == "smoking" and page.items[0].status_since == at("12:00")
    async with session_factory(database)() as session:
        summary = await get_summary(
            session,
            actor_id=second.id,
            user_id=second.id,
            work_date=CLOCK.date(),
            as_of=at("12:15"),
            time_zone=ZONE,
        )
    assert summary.total_seconds == 195 * 60 and summary.break_seconds == 15 * 60
    ended = await time_command(
        database, commands.check_out, second, at("12:30"), paused, confirmed=True
    )
    assert ended.attendance.breaks[0].kind == "smoke"
    assert ended.attendance.ended_at == ended.attendance.breaks[0].ended_at == at("12:30")
    reopened = await time_command(database, commands.reopen_attendance, second, at("12:35"), ended)
    assert reopened.attendance.breaks[0].kind == "smoke"
    assert reopened.attendance.breaks[0].ended_at is None
    next_day = CLOCK + timedelta(days=1)
    stale = await service(database, friends.friends_page, first.id, next_day, ZONE, 0)
    assert stale.items[0].status == "needs_checkout" and stale.items[0].status_since is None
    with pytest.raises(SocialError, match="friend_not_found"):
        await service(
            database,
            friends.friend_profile,
            (await make_users())[0].id,
            second.id,
            CLOCK,
            ZONE,
            "week",
        )


@pytest.mark.asyncio
async def test_rating_uses_local_arrival_dates_full_presence_and_only_confirmed_intervals(
    database, make_users
):
    user = (await make_users(participating=True))[0]
    await attendance(
        database,
        user,
        datetime(2026, 10, 11, 12, tzinfo=ZONE),
        datetime(2026, 10, 11, 13, tzinfo=ZONE),
    )
    await attendance(
        database, user, datetime(2026, 10, 12, tzinfo=ZONE), datetime(2026, 10, 12, 2, tzinfo=ZONE)
    )
    # Sunday-to-Monday attendance belongs to Sunday, outside the current week.
    await attendance(
        database,
        user,
        datetime(2026, 11, 8, 23, tzinfo=ZONE),
        datetime(2026, 11, 9, 0, 5, tzinfo=ZONE),
    )
    await attendance(
        database,
        user,
        datetime(2026, 11, 9, 0, 10, tzinfo=ZONE),
        datetime(2026, 11, 9, 0, 40, tzinfo=ZONE),
    )
    await attendance(database, user, at("09:00"), at("12:00"), pause=(at("10:00"), at("10:30")))
    await attendance(database, user, at("13:00"), None)
    expected = {"week": 12600, "month": 23700, "all": 27300}
    for period, seconds in expected.items():
        result = await ranking(database, user, period=period)
        assert result.current_user.seconds == seconds
        assert next(item for item in result.items if item.is_self).seconds == seconds
    assert period_dates("week", CLOCK, ZONE)[0] == date(2026, 11, 9)
    assert period_dates("month", CLOCK, ZONE)[0] == date(2026, 10, 12)


@pytest.mark.asyncio
async def test_global_ranking_is_opt_in_while_friend_ranking_never_includes_strangers(
    database, make_users
):
    actor, friend, stranger = await make_users(3)
    await connect(database, actor, friend)
    for user in (actor, friend, stranger):
        await attendance(database, user, at("09:00"), at("12:00"))
    async with session_factory(database)() as session, session.begin():
        await session.execute(
            update(User).where(User.id == stranger.id).values(leaderboard_enabled=True)
        )
    public = await ranking(database, actor)
    assert public.participating is False and public.current_user is None
    assert {item.user.id for item in public.items} == {stranger.id}
    private = await ranking(database, actor, scope="friends")
    assert private.participating is True
    assert {item.user.id for item in private.items} == {actor.id, friend.id}
    async with session_factory(database)() as session, session.begin():
        await session.execute(
            update(User).where(User.id == actor.id).values(leaderboard_enabled=True)
        )
    opted = await ranking(database, actor)
    assert opted.current_user is not None and opted.participating is True


@pytest.mark.asyncio
async def test_rank_ties_and_own_position_survive_pagination(database, make_users):
    users = await make_users(36, participating=True)
    async with session_factory(database)() as session, session.begin():
        await session.execute(
            update(User).where(User.id == users[-2].id).values(display_name="Zulu")
        )
        await session.execute(
            update(User).where(User.id == users[-1].id).values(display_name="Alpha")
        )
    for index, user in enumerate(users, start=1):
        minutes = 36 if index >= 35 else index
        await attendance(database, user, at("09:00"), at("09:00") + timedelta(minutes=minutes))
    first = await ranking(database, users[0], period="all")
    assert first.total == 36 and len(first.items) == 30
    assert [item.rank for item in first.items[:3]] == [1, 1, 3]
    assert [item.user.display_name for item in first.items[:2]] == ["Alpha", "Zulu"]
    assert first.current_user.rank == 36 and first.current_user.user.id == users[0].id
    assert users[0].id not in {item.user.id for item in first.items}
    last = await ranking(database, users[0], period="all", offset=30)
    assert len(last.items) == 6 and any(item.is_self for item in last.items)


@pytest.mark.asyncio
async def test_http_ranking_defaults_and_preferences_preserve_an_explicit_opt_in(
    database, make_users
):
    user = (await make_users())[0]
    async with client_for(config(database, bot_username="takt_test_bot")) as client:
        headers, _ = await enter(client, user.telegram_id, user.telegram_username)
        initial = await client.get("/api/v1/social/leaderboard", headers=headers)
        assert initial.status_code == 200
        assert initial.json()["scope"] == "global" and initial.json()["period"] == "week"
        assert initial.json()["participating"] is False
        assert (await client.get("/api/v1/social/leaderboard")).status_code == 401
        body = {"display_name": "Employee", "end_time": "18:00", "leaderboard_enabled": True}
        enabled = await client.put("/api/v1/me/preferences", headers=headers, json=body)
        assert enabled.status_code == 200 and enabled.json()["leaderboard_enabled"] is True
        del body["leaderboard_enabled"]
        preserved = await client.put("/api/v1/me/preferences", headers=headers, json=body)
        assert preserved.json()["leaderboard_enabled"] is True
        assert (
            await client.get("/api/v1/social/leaderboard?period=invalid", headers=headers)
        ).status_code == 422
