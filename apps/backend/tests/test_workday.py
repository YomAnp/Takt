from datetime import UTC, date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from takt.database import session_factory
from takt.time_accounting.calculation import Attendance, Break, calculate_schedule
from takt.time_accounting.commands import (
    CommandConflict,
    check_in,
    check_out,
    pending_departure,
    preview_checkout,
    start_break,
)
from takt.time_accounting.models import AttendanceRecord, AuditRecord, User, WorkSchedule
from takt.time_accounting.schedule import set_schedule
from takt.time_accounting.storage import get_summary

from .helpers import at, client_for

ZONE = ZoneInfo("Europe/Moscow")
DAY = date(2026, 10, 27)


def tomorrow(value):
    return datetime.fromisoformat("2026-10-28T" + value + "+03:00")


def daily(intervals, *, now=None, day=DAY):
    return calculate_schedule(
        work_date=day,
        end_time=time(18),
        intervals=tuple(intervals),
        as_of=now or at("19:00"),
        time_zone=ZONE,
    )


def test_break_is_optional_and_does_not_reduce_total_or_extend_end():
    plain = daily([Attendance(at("09:00"), at("18:00"))])
    with_break = daily([Attendance(at("09:00"), at("18:00"), (Break(at("12:00"), at("12:30")),))])
    assert plain.total_seconds == with_break.total_seconds == 9 * 3600
    assert with_break.break_seconds == 1800
    assert with_break.scheduled_end_at == at("18:00")
    assert with_break.overtime_seconds == 0


def test_overtime_is_actual_presence_after_control_time_including_breaks():
    value = daily([Attendance(at("09:00"), at("18:30"), (Break(at("18:05"), at("18:20")),))])
    assert value.total_seconds == 9 * 3600 + 1800
    assert value.overtime_seconds == 1800
    assert value.break_seconds == 900
    assert value.confirmed_seconds == value.total_seconds


def test_old_open_day_has_no_invented_total_or_overtime():
    value = daily(
        [
            Attendance(at("08:00"), at("10:00")),
            Attendance(at("12:00")),
        ],
        now=tomorrow("10:00"),
    )
    assert value.state == "needs_checkout"
    assert value.total_seconds is value.overtime_seconds is value.break_seconds is None
    assert value.confirmed_seconds == 2 * 3600
    assert value.is_provisional is True


def test_overnight_attendance_belongs_to_arrival_day_without_double_counting():
    intervals = [Attendance(at("17:00"), tomorrow("02:00"))]
    value = daily(intervals, now=tomorrow("10:00"))
    assert value.total_seconds == 9 * 3600
    assert value.overtime_seconds == 8 * 3600
    assert daily(intervals, now=tomorrow("10:00"), day=date(2026, 10, 28)).total_seconds == 0


async def user_with_schedule(database, end=time(18)):
    actor = uuid4()
    async with session_factory(database)() as session, session.begin():
        session.add(User(id=actor))
        await session.flush()
        session.add(WorkSchedule(user_id=actor, effective_from=DAY, end_time=end))
    return actor


async def command(database, actor, operation, now, *, previous=None, key=None, **params):
    if previous is not None:
        params.update(
            attendance_id=previous.attendance.id, expected_revision=previous.attendance.revision
        )
    async with session_factory(database)() as session:
        return await operation(
            session, actor_id=actor, request_id=key or uuid4(), now=now, time_zone=ZONE, **params
        )


async def pending(database, actor, now):
    async with session_factory(database)() as session:
        return await pending_departure(session, actor_id=actor, now=now, time_zone=ZONE)


async def persisted_summary(database, actor, day=DAY):
    async with session_factory(database)() as session:
        return await get_summary(
            session,
            actor_id=actor,
            user_id=actor,
            work_date=day,
            as_of=tomorrow("10:00"),
            time_zone=ZONE,
        )


@pytest.mark.asyncio
async def test_late_arrival_and_missed_departure_use_actual_times_and_then_allow_new_day(database):
    actor = await user_with_schedule(database)
    arrival = await command(database, actor, check_in, at("10:00"), occurred_at=at("09:00"))
    assert arrival.attendance.started_at == at("09:00")
    recovery = await pending(database, actor, tomorrow("10:00"))
    assert recovery.work_date == DAY
    assert recovery.scheduled_end_at == at("18:00")
    assert recovery.can_use_scheduled_end is True
    async with session_factory(database)() as session:
        preview = await preview_checkout(
            session,
            actor_id=actor,
            attendance_id=arrival.attendance.id,
            now=tomorrow("10:00"),
            occurred_at=recovery.scheduled_end_at,
            time_zone=ZONE,
        )
    assert preview.proposed_end_at == at("18:00")
    assert preview.summary.total_seconds == 9 * 3600
    ended = await command(
        database,
        actor,
        check_out,
        tomorrow("10:00"),
        previous=arrival,
        occurred_at=recovery.scheduled_end_at,
        confirmed=True,
    )
    assert ended.attendance.ended_at == at("18:00")
    result = await persisted_summary(database, actor)
    assert result.total_seconds == 9 * 3600 and result.overtime_seconds == 0
    assert await pending(database, actor, tomorrow("10:00")) is None
    today = await command(database, actor, check_in, tomorrow("10:00"))
    assert today.attendance.id != arrival.attendance.id
    async with session_factory(database)() as session:
        audit = await session.scalar(
            select(AuditRecord).where(
                AuditRecord.actor_id == actor, AuditRecord.action == "check_out"
            )
        )
        assert audit.details["recorded_at"] != audit.details["after"]["ended_at"]


@pytest.mark.asyncio
async def test_missed_late_departure_counts_overtime_without_manual_extra_input(database):
    actor = await user_with_schedule(database)
    arrival = await command(database, actor, check_in, at("09:00"))
    await command(
        database,
        actor,
        check_out,
        tomorrow("10:00"),
        previous=arrival,
        occurred_at=at("19:15"),
        confirmed=True,
    )
    result = await persisted_summary(database, actor)
    assert result.total_seconds == (10 * 60 + 15) * 60
    assert result.overtime_seconds == 75 * 60


@pytest.mark.asyncio
async def test_changing_today_schedule_preserves_yesterdays_recovery_time(database):
    actor = await user_with_schedule(database)
    await command(database, actor, check_in, at("09:00"))
    async with session_factory(database)() as session:
        await set_schedule(
            session, actor_id=actor, end_time=time(17), now=tomorrow("08:00"), time_zone=ZONE
        )
    assert (await pending(database, actor, tomorrow("10:00"))).scheduled_end_at == at("18:00")
    assert (await persisted_summary(database, actor)).scheduled_end_at == at("18:00")
    future = await persisted_summary(database, actor, date(2026, 10, 28))
    assert future.scheduled_end_at == tomorrow("17:00")


@pytest.mark.asyncio
async def test_control_time_cannot_silently_discard_later_break(database):
    actor = await user_with_schedule(database)
    arrival = await command(database, actor, check_in, at("09:00"))
    paused = await command(database, actor, start_break, at("18:10"), previous=arrival)
    recovery = await pending(database, actor, tomorrow("10:00"))
    assert recovery.can_use_scheduled_end is False
    with pytest.raises(CommandConflict, match="event_before_latest_entry"):
        await command(
            database,
            actor,
            check_out,
            tomorrow("10:00"),
            previous=paused,
            occurred_at=at("18:00"),
            confirmed=True,
        )
    async with session_factory(database)() as session:
        record = await session.get(AttendanceRecord, arrival.attendance.id)
        assert record.ended_at is None


@pytest.mark.asyncio
async def test_manual_timestamps_reject_future_and_reuse_of_changed_request(database):
    actor = await user_with_schedule(database)
    with pytest.raises(CommandConflict, match="event_in_future"):
        await command(database, actor, check_in, at("10:00"), occurred_at=at("10:01"))
    key = uuid4()
    arrival = await command(
        database, actor, check_in, at("10:00"), occurred_at=at("09:00"), key=key
    )
    retry = await command(
        database, actor, check_in, at("10:01"), occurred_at=at("09:00").astimezone(UTC), key=key
    )
    assert retry == arrival
    with pytest.raises(CommandConflict, match="request_id_reused"):
        await command(database, actor, check_in, at("10:02"), occurred_at=at("09:05"), key=key)
    with pytest.raises(CommandConflict, match="event_in_future"):
        await command(
            database,
            actor,
            check_out,
            at("17:00"),
            previous=arrival,
            occurred_at=at("18:00"),
            confirmed=True,
        )


@pytest.mark.asyncio
async def test_stateless_day_endpoint_returns_fixed_end_and_overtime():
    async with client_for() as client:
        response = await client.post(
            "/api/v1/time/day",
            json={
                "work_date": "2026-10-27",
                "end_time": "18:00",
                "as_of": "2026-10-27T19:00:00+03:00",
                "intervals": [
                    {
                        "started_at": "2026-10-27T09:00:00+03:00",
                        "ended_at": "2026-10-27T18:30:00+03:00",
                    }
                ],
            },
        )
    assert response.status_code == 200
    assert response.json()["total_seconds"] == 34200
    assert response.json()["overtime_seconds"] == 1800


@pytest.mark.asyncio
async def test_overnight_preview_uses_proposed_departure_without_saving_it(database):
    actor = await user_with_schedule(database)
    arrival = await command(database, actor, check_in, at("17:00"))
    paused = await command(database, actor, start_break, at("23:30"), previous=arrival)
    async with session_factory(database)() as session:
        preview = await preview_checkout(
            session,
            actor_id=actor,
            attendance_id=arrival.attendance.id,
            now=tomorrow("10:00"),
            occurred_at=tomorrow("02:00"),
            time_zone=ZONE,
        )
    assert preview.summary.total_seconds == 9 * 3600
    assert preview.summary.break_seconds == 150 * 60
    assert preview.summary.overtime_seconds == 8 * 3600
    assert preview.summary.state == "finished"
    assert preview.will_end_break is True
    assert preview.attendance.ended_at is None
    assert preview.attendance.breaks[0].ended_at is None
    assert (await persisted_summary(database, actor)).state == "needs_checkout"
    ended = await command(
        database,
        actor,
        check_out,
        tomorrow("10:00"),
        previous=paused,
        occurred_at=tomorrow("02:00"),
        confirmed=True,
    )
    assert ended.attendance.ended_at == ended.attendance.breaks[0].ended_at == tomorrow("02:00")
    actual = await persisted_summary(database, actor)
    assert actual.total_seconds == preview.summary.total_seconds
    assert actual.overtime_seconds == preview.summary.overtime_seconds


@pytest.mark.asyncio
async def test_preview_rejects_same_invalid_departure_as_checkout(database):
    actor = await user_with_schedule(database)
    arrival = await command(database, actor, check_in, at("09:00"))
    async with session_factory(database)() as session:
        with pytest.raises(CommandConflict, match="end_must_follow_start"):
            await preview_checkout(
                session,
                actor_id=actor,
                attendance_id=arrival.attendance.id,
                now=at("10:00"),
                occurred_at=at("09:00"),
                time_zone=ZONE,
            )


def test_current_open_break_keeps_total_running_with_fixed_ending():
    intervals = [Attendance(at("09:00"), breaks=(Break(at("12:00")),))]
    first = daily(intervals, now=at("12:10"))
    later = daily(intervals, now=at("12:40"))
    assert first.state == later.state == "on_break"
    assert first.is_provisional is later.is_provisional is True
    assert first.total_seconds == 190 * 60
    assert later.total_seconds == 220 * 60
    assert later.break_seconds == 40 * 60
    assert later.confirmed_seconds == 0
    assert first.scheduled_end_at == later.scheduled_end_at == at("18:00")


@pytest.mark.asyncio
async def test_control_time_does_not_close_day_or_allow_duplicate_arrival(database):
    actor = await user_with_schedule(database)
    await command(database, actor, check_in, at("09:00"))
    assert await pending(database, actor, at("19:00")) is None
    with pytest.raises(CommandConflict, match="already_present"):
        await command(database, actor, check_in, tomorrow("09:00"))
    recovery = await pending(database, actor, tomorrow("10:00"))
    assert recovery.attendance.ended_at is None
    assert (await persisted_summary(database, actor)).total_seconds is None
