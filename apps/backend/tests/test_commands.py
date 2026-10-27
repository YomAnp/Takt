import asyncio
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import selectinload

from takt.database import session_factory
from takt.time_accounting.access import AccessDenied
from takt.time_accounting.commands import (
    CommandConflict,
    ConfirmationRequired,
    RecordNotFound,
    check_in,
    check_out,
    current_attendance,
    end_break,
    preview_checkout,
    reopen_attendance,
    start_break,
)
from takt.time_accounting.models import (
    AttendanceRecord,
    AuditRecord,
    CommandReceipt,
    TimeGoal,
    User,
)
from takt.time_accounting.storage import MissingGoal, get_summary

from .helpers import at

ZONE = ZoneInfo("Europe/Moscow")


async def make_user(database, *, role="member", goal=True):
    actor = uuid4()
    async with session_factory(database)() as session, session.begin():
        session.add(User(id=actor, role=role))
        await session.flush()
        if goal:
            session.add(
                TimeGoal(user_id=actor, effective_from=date(2026, 10, 26), required_minutes=360)
            )
    return actor


async def send(database, actor, operation, now, previous=None, *, key=None, **parameters):
    if previous is not None:
        parameters.setdefault("attendance_id", previous.attendance.id)
        parameters.setdefault("expected_revision", previous.attendance.revision)
    async with session_factory(database)() as session:
        return await operation(
            session,
            actor_id=actor,
            request_id=key or uuid4(),
            now=at(now),
            time_zone=ZONE,
            **parameters,
        )


async def stored(database, actor):
    async with session_factory(database)() as session:
        return (
            await session.scalars(
                select(AttendanceRecord)
                .where(AttendanceRecord.user_id == actor)
                .order_by(AttendanceRecord.started_at)
                .options(selectinload(AttendanceRecord.breaks))
            )
        ).all()


async def counts(database, actor):
    async with session_factory(database)() as session:
        audit = await session.scalar(
            select(func.count()).select_from(AuditRecord).where(AuditRecord.actor_id == actor)
        )
        receipts = await session.scalar(
            select(func.count()).select_from(CommandReceipt).where(CommandReceipt.user_id == actor)
        )
        return audit, receipts


async def preview(database, actor, result, now):
    async with session_factory(database)() as session:
        return await preview_checkout(
            session,
            actor_id=actor,
            attendance_id=result.attendance.id,
            now=at(now),
            time_zone=ZONE,
        )


async def summary(database, actor, now):
    async with session_factory(database)() as session:
        return await get_summary(
            session,
            actor_id=actor,
            user_id=actor,
            work_date=date(2026, 10, 27),
            as_of=at(now),
            time_zone=ZONE,
        )


@pytest.mark.asyncio
async def test_complete_day_is_persisted_and_calculated(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    pause = await send(database, actor, start_break, "12:00", arrival)
    resumed = await send(
        database, actor, end_break, "12:30", pause, break_id=pause.attendance.breaks[0].id
    )
    confirmation = await preview(database, actor, resumed, "14:00")
    assert confirmation.summary.credited_seconds == 330 * 60
    assert confirmation.summary.remaining_seconds == 30 * 60
    assert confirmation.will_end_break is False
    departure = await send(database, actor, check_out, "15:00", resumed, confirmed=True)
    assert departure.attendance.revision == 4
    assert departure.attendance.ended_at == at("15:00")
    result = await summary(database, actor, "17:00")
    assert result.credited_seconds == 390 * 60
    assert result.state == "finished"
    assert await counts(database, actor) == (4, 4)


@pytest.mark.asyncio
async def test_every_successful_command_can_be_retried_without_duplicate_writes(database):
    actor = await make_user(database)

    async def retry(operation, now, previous=None, **parameters):
        key = uuid4()
        result = await send(database, actor, operation, now, previous, key=key, **parameters)
        repeated = await send(database, actor, operation, "18:00", previous, key=key, **parameters)
        assert repeated == result
        return result

    arrival = await retry(check_in, "08:30")
    pause = await retry(start_break, "12:00", arrival)
    resumed = await retry(end_break, "12:30", pause, break_id=pause.attendance.breaks[0].id)
    departure = await retry(check_out, "15:00", resumed, confirmed=True)
    reopened = await retry(reopen_attendance, "15:01", departure)
    assert reopened.attendance.ended_at is None
    assert await counts(database, actor) == (5, 5)
    assert len(await stored(database, actor)) == 1


@pytest.mark.asyncio
async def test_concurrent_retry_of_one_request_creates_only_one_attendance(database):
    actor = await make_user(database)
    key = uuid4()
    first, second = await asyncio.gather(
        send(database, actor, check_in, "08:30", key=key),
        send(database, actor, check_in, "08:30", key=key),
    )
    assert first == second
    assert len(await stored(database, actor)) == 1
    assert await counts(database, actor) == (1, 1)


@pytest.mark.asyncio
async def test_two_distinct_concurrent_checkins_have_one_winner(database):
    actor = await make_user(database)
    results = await asyncio.gather(
        send(database, actor, check_in, "08:30"),
        send(database, actor, check_in, "08:30"),
        return_exceptions=True,
    )
    errors = [value for value in results if isinstance(value, CommandConflict)]
    assert len(errors) == 1 and errors[0].code == "already_present"
    assert len(await stored(database, actor)) == 1
    assert await counts(database, actor) == (1, 1)


@pytest.mark.asyncio
async def test_competing_break_and_departure_cannot_both_apply_to_one_revision(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    results = await asyncio.gather(
        send(database, actor, start_break, "12:00", arrival),
        send(database, actor, check_out, "12:00", arrival, confirmed=True),
        return_exceptions=True,
    )
    errors = [value for value in results if isinstance(value, CommandConflict)]
    assert len(errors) == 1 and errors[0].code == "stale_revision"
    (record,) = await stored(database, actor)
    assert record.revision == 2
    assert record.ended_at is None or not any(pause.ended_at is None for pause in record.breaks)
    assert await counts(database, actor) == (2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("on_break", [False, True])
async def test_departure_requires_confirmation_and_leaves_no_failed_write(database, on_break):
    actor = await make_user(database)
    current = await send(database, actor, check_in, "08:30")
    if on_break:
        current = await send(database, actor, start_break, "12:00", current)
    before = await counts(database, actor)
    confirmation = await preview(database, actor, current, "13:00")
    assert confirmation.will_end_break is on_break
    with pytest.raises(ConfirmationRequired) as error:
        await send(database, actor, check_out, "13:00", current)
    assert error.value.will_end_break is on_break
    (record,) = await stored(database, actor)
    assert record.ended_at is None and record.revision == current.attendance.revision
    assert await counts(database, actor) == before


@pytest.mark.asyncio
async def test_departure_during_break_and_undo_restore_both_original_states(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    pause = await send(database, actor, start_break, "12:00", arrival)
    confirmation = await preview(database, actor, pause, "13:00")
    assert confirmation.summary.credited_seconds == 270 * 60
    assert confirmation.will_end_break is True
    departure = await send(database, actor, check_out, "13:00", pause, confirmed=True)
    assert departure.closed_break_id == pause.attendance.breaks[0].id
    (record,) = await stored(database, actor)
    assert record.ended_at == record.breaks[0].ended_at == at("13:00")
    reopened = await send(database, actor, reopen_attendance, "13:05", departure)
    assert reopened.attendance.ended_at is None
    assert reopened.attendance.breaks[0].ended_at is None
    result = await summary(database, actor, "14:00")
    assert result.credited_seconds == 330 * 60
    assert result.state == "on_break"
    assert await counts(database, actor) == (4, 4)
    async with session_factory(database)() as session:
        audits = (
            await session.scalars(
                select(AuditRecord).where(
                    AuditRecord.actor_id == actor, AuditRecord.action.in_(["check_out", "reopen"])
                )
            )
        ).all()
        by_action = {item.action: item.details for item in audits}
        assert by_action["check_out"]["before"]["breaks"][0]["ended_at"] is None
        assert by_action["check_out"]["after"]["breaks"][0]["ended_at"] is not None
        assert by_action["reopen"]["before"]["ended_at"] is not None
        assert by_action["reopen"]["after"]["ended_at"] is None
        assert by_action["reopen"]["after"]["breaks"][0]["ended_at"] is None


@pytest.mark.asyncio
async def test_stale_confirmation_does_not_close_a_new_break(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    confirmation = await preview(database, actor, arrival, "12:00")
    await send(database, actor, start_break, "12:01", arrival)
    with pytest.raises(CommandConflict, match="stale_revision"):
        await send(
            database,
            actor,
            check_out,
            "12:02",
            attendance_id=arrival.attendance.id,
            expected_revision=confirmation.attendance.revision,
            confirmed=True,
        )
    (record,) = await stored(database, actor)
    assert record.ended_at is None and record.breaks[0].ended_at is None


@pytest.mark.asyncio
async def test_delayed_departure_retry_after_undo_does_not_close_it_again(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    key = uuid4()
    departure = await send(database, actor, check_out, "15:00", arrival, key=key, confirmed=True)
    reopened = await send(database, actor, reopen_attendance, "15:01", departure)
    repeated = await send(database, actor, check_out, "15:02", arrival, key=key, confirmed=True)
    assert repeated == departure
    (record,) = await stored(database, actor)
    assert record.ended_at is None and record.revision == reopened.attendance.revision
    assert await counts(database, actor) == (3, 3)


@pytest.mark.asyncio
async def test_undo_does_not_reopen_an_independently_finished_break(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    pause = await send(database, actor, start_break, "12:00", arrival)
    resumed = await send(
        database, actor, end_break, "12:30", pause, break_id=pause.attendance.breaks[0].id
    )
    departure = await send(database, actor, check_out, "15:00", resumed, confirmed=True)
    reopened = await send(database, actor, reopen_attendance, "15:01", departure)
    assert reopened.attendance.breaks[0].ended_at == at("12:30")
    assert (await summary(database, actor, "15:02")).state == "working"


@pytest.mark.asyncio
async def test_cannot_undo_earlier_departure_after_new_attendance(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    departure = await send(database, actor, check_out, "12:00", arrival, confirmed=True)
    await send(database, actor, check_in, "13:00")
    with pytest.raises(CommandConflict, match="later_attendance_exists"):
        await send(database, actor, reopen_attendance, "13:05", departure)
    records = await stored(database, actor)
    assert records[0].ended_at == at("12:00") and records[1].ended_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["member", "admin"])
async def test_commands_cannot_modify_someone_elses_attendance(database, role):
    owner = await make_user(database)
    other = await make_user(database, role=role)
    arrival = await send(database, owner, check_in, "08:30")
    for operation, parameters in [
        (start_break, {}),
        (check_out, {"confirmed": True}),
        (reopen_attendance, {}),
        (end_break, {"break_id": uuid4()}),
    ]:
        with pytest.raises(RecordNotFound):
            await send(database, other, operation, "12:00", arrival, **parameters)
    with pytest.raises(RecordNotFound):
        await preview(database, other, arrival, "12:00")
    assert await counts(database, other) == (0, 0)


@pytest.mark.asyncio
async def test_request_id_is_bound_to_operation_and_parameters(database):
    actor = await make_user(database)
    key = uuid4()
    arrival = await send(database, actor, check_in, "08:30", key=key)
    with pytest.raises(CommandConflict, match="request_id_reused"):
        await send(database, actor, start_break, "12:00", arrival, key=key)
    key = uuid4()
    await send(database, actor, check_out, "15:00", arrival, key=key, confirmed=True)
    with pytest.raises(CommandConflict, match="request_id_reused"):
        await send(database, actor, check_out, "15:01", arrival, key=key, confirmed=False)


@pytest.mark.asyncio
async def test_idempotency_keys_are_scoped_to_the_account(database):
    first = await make_user(database)
    second = await make_user(database)
    key = uuid4()
    a = await send(database, first, check_in, "08:30", key=key)
    b = await send(database, second, check_in, "08:30", key=key)
    assert a.attendance.id != b.attendance.id


@pytest.mark.asyncio
async def test_disabled_account_cannot_replay_even_in_a_reused_session(database):
    actor = await make_user(database)
    key = uuid4()
    async with session_factory(database)() as session:
        cached_actor = await session.get(User, actor)
        await session.commit()
        assert cached_actor.is_active is True
        await check_in(session, actor_id=actor, request_id=key, now=at("08:30"), time_zone=ZONE)
        async with session_factory(database)() as admin_session, admin_session.begin():
            await admin_session.execute(
                update(User).where(User.id == actor).values(is_active=False)
            )
        with pytest.raises(AccessDenied):
            await check_in(session, actor_id=actor, request_id=key, now=at("08:31"), time_zone=ZONE)
    assert await counts(database, actor) == (1, 1)


@pytest.mark.asyncio
async def test_first_checkin_requires_saved_target(database):
    actor = await make_user(database, goal=False)
    with pytest.raises(MissingGoal):
        await send(database, actor, check_in, "08:30")
    assert await stored(database, actor) == []
    assert await counts(database, actor) == (0, 0)


@pytest.mark.asyncio
async def test_backdated_or_zero_duration_commands_leave_records_unchanged(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    with pytest.raises(CommandConflict, match="event_before_latest_entry"):
        await send(database, actor, start_break, "08:00", arrival)
    with pytest.raises(CommandConflict, match="end_must_follow_start"):
        await send(database, actor, check_out, "08:30", arrival, confirmed=True)
    pause = await send(database, actor, start_break, "12:00", arrival)
    with pytest.raises(CommandConflict, match="end_must_follow_start"):
        await send(
            database, actor, end_break, "12:00", pause, break_id=pause.attendance.breaks[0].id
        )
    assert await counts(database, actor) == (2, 2)
    async with session_factory(database)() as session:
        with pytest.raises(ValueError, match="UTC offset"):
            await check_in(
                session,
                actor_id=actor,
                request_id=uuid4(),
                now=datetime(2026, 10, 27, 8),
                time_zone=ZONE,
            )


@pytest.mark.asyncio
async def test_reconnect_restores_current_state_instead_of_last_receipt(database):
    actor = await make_user(database)
    arrival = await send(database, actor, check_in, "08:30")
    paused = await send(database, actor, start_break, "12:00", arrival)
    async with session_factory(database)() as session:
        assert await current_attendance(session, actor_id=actor) == paused.attendance
    departure = await send(database, actor, check_out, "13:00", paused, confirmed=True)
    async with session_factory(database)() as session:
        assert await current_attendance(session, actor_id=actor) is None
    reopened = await send(database, actor, reopen_attendance, "13:01", departure)
    async with session_factory(database)() as session:
        state = await current_attendance(session, actor_id=actor)
        assert state == reopened.attendance
        assert state.revision != departure.attendance.revision
        assert state.breaks[0].ended_at is None
