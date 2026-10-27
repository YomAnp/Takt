from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from httpx import ASGITransport, AsyncClient

from takt.app import create_app
from takt.config import Settings


def at(value: str) -> datetime:
    return datetime.fromisoformat("2026-10-27T" + value + "+03:00")


@asynccontextmanager
async def client_for(settings: Settings | None = None) -> AsyncIterator[AsyncClient]:
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client
