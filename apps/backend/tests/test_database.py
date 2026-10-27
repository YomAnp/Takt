import asyncio
from datetime import date
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from takt.config import Settings
from takt.database import session_factory
from takt.time_accounting.models import AttendanceRecord, AuditRecord, BreakRecord, TimeGoal, User
from takt.time_accounting.storage import AccessDenied, get_summary, set_goal

from .helpers import at, client_for

ZONE = ZoneInfo("Europe/Moscow")
DAY = date(2026, 10, 27)


async def add_user(database, *, role="member", active=True):
    user_id = uuid4()
    async with session_factory(database)() as session, session.begin():
        session.add(User(id=user_id, role=role, is_active=active))
        await session.flush()
        session.add(
            TimeGoal(user_id=user_id, effective_from=date(2026, 10, 26), required_minutes=360)
        )
    return user_id


async def add_attendance(database, user_id: UUID):
    attendance_id = uuid4()
    async with session_factory(database)() as session, session.begin():
        session.add(AttendanceRecord(id=attendance_id, user_id=user_id, started_at=at("08:30")))
    async with session_factory(database)() as session, session.begin():
        session.add(
            BreakRecord(attendance_id=attendance_id, started_at=at("12:00"), ended_at=at("12:30"))
        )
    return attendance_id


async def read(database, actor_id: UUID, user_id: UUID, day=DAY):
    async with session_factory(database)() as session:
        return await get_summary(
            session,
            actor_id=actor_id,
            user_id=user_id,
            work_date=day,
            as_of=at("13:10"),
            time_zone=ZONE,
        )


@pytest.mark.asyncio
async def test_persisted_intervals_produce_expected_summary(database):
    owner = await add_user(database)
    await add_attendance(database, owner)
    result = await read(database, owner, owner)
    assert result.credited_seconds == 16800
    assert result.break_seconds == 1800
    assert result.estimated_completion_at == at("14:30")


@pytest.mark.asyncio
async def test_target_change_applies_today_and_forward_but_preserves_past(database):
    owner = await add_user(database)
    async with session_factory(database)() as session:
        await set_goal(
            session, actor_id=owner, required_minutes=480, now=at("13:00"), time_zone=ZONE
        )
    today = await read(database, owner, owner)
    yesterday = await read(database, owner, owner, date(2026, 10, 26))
    tomorrow = await read(database, owner, owner, date(2026, 10, 28))
    assert today.required_seconds == tomorrow.required_seconds == 480 * 60
    assert yesterday.required_seconds == 360 * 60
    async with session_factory(database)() as session:
        audit = (
            await session.scalars(select(AuditRecord).where(AuditRecord.actor_id == owner))
        ).one()
        assert audit.details["previous_minutes"] == 360
        assert audit.details["required_minutes"] == 480
    async with session_factory(database)() as session:
        await set_goal(
            session, actor_id=owner, required_minutes=480, now=at("13:01"), time_zone=ZONE
        )
    async with session_factory(database)() as session:
        assert (
            await session.scalar(
                select(func.count()).select_from(AuditRecord).where(AuditRecord.actor_id == owner)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_same_day_target_changes_keep_one_effective_rule_and_record_history(database):
    owner = await add_user(database)
    for minutes in (420, 480):
        async with session_factory(database)() as session:
            await set_goal(
                session, actor_id=owner, required_minutes=minutes, now=at("13:00"), time_zone=ZONE
            )
    assert (await read(database, owner, owner)).required_seconds == 480 * 60
    async with session_factory(database)() as session:
        rules = (await session.scalars(select(TimeGoal).where(TimeGoal.user_id == owner))).all()
        assert len(rules) == 2
        assert (
            await session.scalar(
                select(func.count()).select_from(AuditRecord).where(AuditRecord.actor_id == owner)
            )
            == 2
        )


@pytest.mark.asyncio
async def test_admin_can_read_individual_accounting_but_member_cannot(database):
    owner = await add_user(database)
    member = await add_user(database)
    admin = await add_user(database, role="admin")
    await add_attendance(database, owner)
    assert (await read(database, admin, owner)).credited_seconds == 16800
    with pytest.raises(AccessDenied):
        await read(database, member, owner)
    disabled_admin = await add_user(database, role="admin", active=False)
    with pytest.raises(AccessDenied):
        await read(database, disabled_admin, owner)


@pytest.mark.asyncio
async def test_database_rejects_two_concurrent_open_intervals(database):
    owner = await add_user(database)

    async def write():
        try:
            async with session_factory(database)() as session, session.begin():
                session.add(AttendanceRecord(user_id=owner, started_at=at("08:30")))
            return "created"
        except IntegrityError as exc:
            assert exc.orig.sqlstate == "23P01"
            return "conflict"

    assert sorted(await asyncio.gather(write(), write())) == ["conflict", "created"]


@pytest.mark.asyncio
async def test_database_rejects_overlapping_closed_intervals(database):
    owner = await add_user(database)
    async with session_factory(database)() as session, session.begin():
        session.add(AttendanceRecord(user_id=owner, started_at=at("08:00"), ended_at=at("12:00")))
    with pytest.raises(IntegrityError) as error:
        async with session_factory(database)() as session, session.begin():
            session.add(
                AttendanceRecord(user_id=owner, started_at=at("11:00"), ended_at=at("13:00"))
            )
    assert error.value.orig.sqlstate == "23P01"


@pytest.mark.asyncio
async def test_breaks_cannot_escape_attendance_or_overlap(database):
    owner = await add_user(database)
    attendance_id = await add_attendance(database, owner)
    for start, end, code in [
        ("08:00", "09:00", "23514"),
        ("12:10", "12:40", "23P01"),
    ]:
        with pytest.raises(IntegrityError) as error:
            async with session_factory(database)() as session, session.begin():
                session.add(
                    BreakRecord(attendance_id=attendance_id, started_at=at(start), ended_at=at(end))
                )
        assert error.value.orig.sqlstate == code


@pytest.mark.asyncio
async def test_parent_cannot_be_closed_before_existing_break(database):
    owner = await add_user(database)
    attendance_id = await add_attendance(database, owner)
    with pytest.raises(IntegrityError) as error:
        async with session_factory(database)() as session, session.begin():
            record = await session.get(AttendanceRecord, attendance_id)
            record.ended_at = at("11:00")
    assert error.value.orig.sqlstate == "23514"


@pytest.mark.asyncio
async def test_distinct_users_can_attend_at_the_same_time(database):
    first = await add_user(database)
    second = await add_user(database)
    await add_attendance(database, first)
    await add_attendance(database, second)
    assert (await read(database, first, first)).credited_seconds == 16800
    assert (await read(database, second, second)).credited_seconds == 16800


@pytest.mark.asyncio
async def test_api_readiness_with_migrated_postgresql(migrated_database):
    async with client_for(Settings(database_url=migrated_database)) as client:
        assert (await client.get("/health/ready")).json() == {"status": "ok"}
