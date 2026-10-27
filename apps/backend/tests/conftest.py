import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from takt.config import Settings
from takt.database import create_database
from takt.runtime import new_event_loop

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def migrated_database():
    url = os.environ.get("TAKT_TEST_DATABASE_URL")
    if not url:
        pytest.fail(
            "Set TAKT_TEST_DATABASE_URL to a dedicated PostgreSQL database ending in _test."
        )
    parsed = make_url(url)
    if parsed.drivername != "postgresql+psycopg" or not (parsed.database or "").endswith("_test"):
        pytest.fail("Database tests require a PostgreSQL test database with the _test suffix.")
    previous = os.environ.get("TAKT_DATABASE_URL")
    os.environ["TAKT_DATABASE_URL"] = url
    try:
        config = Config(str(BACKEND / "alembic.ini"))
        command.upgrade(config, "head")
        command.check(config)
        command.downgrade(config, "base")
        command.upgrade(config, "0001_time")
        user_id, attendance_id = uuid4(), uuid4()
        connection_args = parsed.translate_connect_args(username="user", database="dbname")
        with psycopg.connect(**connection_args) as connection:
            connection.execute("INSERT INTO users (id) VALUES (%s)", (user_id,))
            connection.execute(
                "INSERT INTO attendance (id, user_id, started_at) VALUES (%s, %s, %s)",
                (attendance_id, user_id, "2026-10-27T08:30:00+03:00"),
            )
        command.upgrade(config, "head")
        command.check(config)
        with psycopg.connect(**connection_args) as connection:
            record = connection.execute(
                "SELECT user_id, ended_at, revision FROM attendance WHERE id = %s",
                (attendance_id,),
            ).fetchone()
            assert record == (user_id, None, 1), "Upgrade changed an existing attendance record"
        command.downgrade(config, "0001_time")
        with psycopg.connect(**connection_args) as connection:
            assert connection.execute(
                "SELECT user_id, ended_at FROM attendance WHERE id = %s", (attendance_id,)
            ).fetchone() == (user_id, None)
        command.upgrade(config, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("TAKT_DATABASE_URL", None)
        else:
            os.environ["TAKT_DATABASE_URL"] = previous


@pytest_asyncio.fixture
async def database(migrated_database: str):
    engine = create_database(Settings(database_url=migrated_database))
    try:
        yield engine
    finally:
        await engine.dispose()


def pytest_asyncio_loop_factories():
    return {"selector": new_event_loop}
