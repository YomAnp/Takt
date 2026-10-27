from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from takt.config import Settings
from takt.database import create_database
from takt.time_accounting.router import router


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_database(settings)
        app.state.database = engine
        try:
            yield
        finally:
            await engine.dispose()

    app = FastAPI(
        title="Takt API",
        version="0.1.0",
        lifespan=lifespan,
        description="Attendance time accounting for MGRI employees.",
    )
    app.state.settings = settings
    app.include_router(router)

    @app.get("/health", tags=["Health"], operation_id="getHealth")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], operation_id="getReadiness")
    async def readiness(request: Request) -> dict[str, str]:
        try:
            async with request.app.state.database.connect() as connection:
                await connection.execute(text("SELECT 1 FROM time_goals LIMIT 0"))
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Database is not ready.") from None
        return {"status": "ok"}

    return app
