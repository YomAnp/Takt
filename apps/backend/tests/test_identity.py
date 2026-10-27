import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from sqlalchemy import func, select, update

from takt.config import Settings
from takt.database import session_factory
from takt.identity.telegram import InvalidTelegramData, verify_init_data
from takt.time_accounting.models import AuditRecord, AuthSession, OwnerBinding, User

from .helpers import client_for

TOKEN = "123456:local_test_token_not_a_real_telegram_secret"


def signed(identifier=10001, username="employee", *, age=0, token=TOKEN):
    data = {
        "auth_date": str(int(datetime.now(UTC).timestamp()) - age),
        "user": json.dumps(
            {"id": identifier, "first_name": "Test", "username": username}, separators=(",", ":")
        ),
        "query_id": "test-query",
    }
    key = hmac.digest(b"WebAppData", token.encode(), "sha256")
    data["hash"] = hmac.new(
        key, "\n".join(f"{key}={data[key]}" for key in sorted(data)).encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(data)


def config(database, **kwargs):
    return Settings(
        database_url=database.url.render_as_string(hide_password=False),
        bot_token=TOKEN,
        superadmin_username="@owner",
        **kwargs,
    )


async def enter(client, identifier, username="employee"):
    result = await client.post(
        "/api/v1/auth/telegram", json={"init_data": signed(identifier, username)}
    )
    assert result.status_code == 200, result.text
    body = result.json()
    return {"Authorization": "Bearer " + body["token"]}, body["profile"]


@pytest.mark.parametrize(
    "raw",
    [
        signed(age=301),
        signed(age=-60),
        signed(token="another-token"),
        signed().replace("test-query", "tampered"),
        signed() + "&auth_date=1",
        "user={}",
    ],
)
def test_launch_data_rejects_expired_future_forged_and_duplicate_fields(raw):
    with pytest.raises(InvalidTelegramData):
        verify_init_data(raw, TOKEN, datetime.now(UTC))


def test_signed_launch_data_retains_verified_identity():
    identity = verify_init_data(signed(), TOKEN, datetime.now(UTC))
    assert identity.id == 10001 and identity.username == "employee"


@pytest.mark.asyncio
async def test_login_is_required_and_missing_bot_does_not_enable_bypass(database):
    async with client_for(
        Settings(database_url=database.url.render_as_string(hide_password=False))
    ) as client:
        assert (await client.get("/api/v1/me/state")).status_code == 401
        assert (
            await client.post("/api/v1/auth/telegram", json={"init_data": signed()})
        ).status_code == 503


@pytest.mark.asyncio
async def test_login_reuses_identity_stores_only_session_hash_and_never_starts_time(database):
    identifier = int(uuid4().int % 10**12)
    async with client_for(config(database)) as client:
        headers, user = await enter(client, identifier)
        second, same = await enter(client, identifier)
        assert same["id"] == user["id"] and same["role"] == "member"
        assert not same["onboarded"]
        state = (await client.get("/api/v1/me/state", headers=headers)).json()
        assert state["attendance"] is None
        assert (await client.post("/api/v1/auth/logout", headers=headers)).status_code == 204
        assert (await client.get("/api/v1/me", headers=headers)).status_code == 401
        assert (await client.get("/api/v1/me", headers=second)).status_code == 200
    async with session_factory(database)() as session:
        rows = (
            await session.scalars(select(AuthSession).where(AuthSession.user_id == user["id"]))
        ).all()
        assert len(rows) == 1 and len(rows[0].token_hash) == 64
        assert rows[0].token_hash != second["Authorization"].split()[-1]


@pytest.mark.asyncio
async def test_onboarding_and_complete_attendance_work_through_authenticated_http(database):
    identifier = int(uuid4().int % 10**12)
    async with client_for(config(database)) as client:
        headers, user = await enter(client, identifier)
        preferences = {"display_name": "  Employee  Name ", "end_time": "18:00"}
        saved = await client.put("/api/v1/me/preferences", headers=headers, json=preferences)
        assert saved.status_code == 200
        assert saved.json()["display_name"] == "Employee Name" and saved.json()["onboarded"]
        await client.put("/api/v1/me/preferences", headers=headers, json=preferences)
        assert (await client.get("/api/v1/me/state", headers=headers)).json()["attendance"] is None
        actual = datetime.now(UTC) - timedelta(seconds=1)
        body = {"request_id": str(uuid4()), "occurred_at": actual.isoformat()}
        arrival = await client.post("/api/v1/me/attendance/check_in", headers=headers, json=body)
        assert arrival.status_code == 200
        record = arrival.json()["attendance"]
        assert (
            await client.post("/api/v1/me/attendance/check_in", headers=headers, json=body)
        ).json() == arrival.json()
        preview = await client.post(
            "/api/v1/me/attendance/preview", headers=headers, json={"attendance_id": record["id"]}
        )
        assert preview.status_code == 200 and preview.json()["summary"]["total_seconds"] >= 1
        departure = {
            "request_id": str(uuid4()),
            "attendance_id": record["id"],
            "expected_revision": record["revision"],
            "confirmed": True,
        }
        ended = await client.post(
            "/api/v1/me/attendance/check_out", headers=headers, json=departure
        )
        assert ended.status_code == 200
        assert (await client.get("/api/v1/me/state", headers=headers)).json()["attendance"] is None
        assert len((await client.get("/api/v1/me/history", headers=headers)).json()) == 7
    async with session_factory(database)() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditRecord)
                .where(
                    AuditRecord.actor_id == user["id"], AuditRecord.action == "preferences_saved"
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_owner_claim_is_verified_and_stays_bound_after_username_change(database):
    identifier = int(uuid4().int % 10**12)
    async with client_for(config(database)) as client:
        owner_headers, owner = await enter(client, identifier, "OwNeR")
        # Other tests may already have established this installation's owner.
        async with session_factory(database)() as session, session.begin():
            binding = await session.get(OwnerBinding, 1)
            assert binding is not None
            assert str(binding.user_id) == owner["id"]
        assert owner["role"] == "superadmin"
        headers, renamed = await enter(client, identifier, "new_name")
        assert renamed["role"] == "superadmin"
        _, replacement = await enter(client, identifier + 1, "owner")
        assert replacement["role"] == "member"
        assert (await client.get("/api/v1/admin/users", headers=owner_headers)).status_code == 200
        assert (await client.get("/api/v1/admin/users", headers=headers)).status_code == 200


@pytest.mark.asyncio
async def test_admin_permissions_blocked_sessions_and_ownership_protection(database):
    identifiers = [int(uuid4().int % 10**12) for _ in range(3)]
    async with client_for(config(database)) as client:
        owner_headers, owner = await enter(client, identifiers[0], "ordinary")
        admin_headers, admin = await enter(client, identifiers[1], "candidate")
        member_headers, member = await enter(client, identifiers[2], "member")
        # Explicit role setup isolates access behaviour from installation bootstrap.
        async with session_factory(database)() as session, session.begin():
            await session.execute(
                update(User).where(User.id == owner["id"]).values(role="superadmin")
            )
        assert (await client.get("/api/v1/admin/users", headers=member_headers)).status_code == 403
        changed = await client.patch(
            "/api/v1/admin/users/" + admin["id"], headers=owner_headers, json={"role": "admin"}
        )
        assert changed.status_code == 200
        assert (await client.get("/api/v1/admin/users", headers=admin_headers)).status_code == 200
        assert (
            await client.patch(
                "/api/v1/admin/users/" + member["id"], headers=admin_headers, json={"role": "admin"}
            )
        ).status_code == 403
        assert (
            await client.patch(
                "/api/v1/admin/users/" + owner["id"],
                headers=admin_headers,
                json={"is_active": False},
            )
        ).status_code == 409
        assert (
            await client.patch(
                "/api/v1/admin/users/" + owner["id"], headers=owner_headers, json={"role": "member"}
            )
        ).status_code == 409
        assert (
            await client.patch(
                "/api/v1/admin/users/" + member["id"],
                headers=admin_headers,
                json={"is_active": False},
            )
        ).status_code == 200
        assert (await client.get("/api/v1/me", headers=member_headers)).status_code in {401, 403}
        assert (
            await client.post(
                "/api/v1/auth/telegram", json={"init_data": signed(identifiers[2], "member")}
            )
        ).status_code == 403
        assert (
            await client.patch(
                "/api/v1/admin/users/" + member["id"],
                headers=admin_headers,
                json={"is_active": True},
            )
        ).status_code == 200
        # Unblocking does not resurrect a revoked bearer token.
        assert (await client.get("/api/v1/me", headers=member_headers)).status_code == 401
        fresh, _ = await enter(client, identifiers[2], "member")
        assert (await client.get("/api/v1/me", headers=fresh)).status_code == 200
        assert (
            await client.patch(
                "/api/v1/admin/users/" + admin["id"], headers=owner_headers, json={"role": "member"}
            )
        ).status_code == 200
        assert (await client.get("/api/v1/admin/users", headers=admin_headers)).status_code == 403


@pytest.mark.asyncio
async def test_cannot_read_or_mutate_another_users_attendance(database):
    async with client_for(config(database)) as client:
        first, user = await enter(client, int(uuid4().int % 10**12))
        second, _ = await enter(client, int(uuid4().int % 10**12))
        await client.put(
            "/api/v1/me/preferences",
            headers=first,
            json={"display_name": "Employee", "end_time": "18:00"},
        )
        started = (
            await client.post(
                "/api/v1/me/attendance/check_in", headers=first, json={"request_id": str(uuid4())}
            )
        ).json()["attendance"]
        response = await client.post(
            "/api/v1/me/attendance/start_break",
            headers=second,
            json={
                "request_id": str(uuid4()),
                "attendance_id": started["id"],
                "expected_revision": started["revision"],
            },
        )
        assert response.status_code == 404
        day = datetime.now(UTC).astimezone().date().isoformat()
        assert (
            await client.get(
                "/api/v1/admin/users/" + user["id"] + "/day?work_date=" + day, headers=second
            )
        ).status_code == 403
