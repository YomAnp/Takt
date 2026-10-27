from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from takt.config import Settings
from takt.database import create_database
from takt.identity.router import router as identity_router
from takt.time_accounting.access import AccessDenied
from takt.time_accounting.commands import CommandConflict, ConfirmationRequired, RecordNotFound
from takt.time_accounting.personal import router as personal_router
from takt.time_accounting.router import router
from takt.time_accounting.storage import MissingGoal


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
    app.include_router(identity_router)
    app.include_router(personal_router)

    @app.middleware("http")
    async def private_responses(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AccessDenied)
    async def denied(request: Request, exc: AccessDenied) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": {"code": "account_disabled"}})

    @app.exception_handler(CommandConflict)
    async def conflict(request: Request, exc: CommandConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {"code": exc.code}})

    @app.exception_handler(ConfirmationRequired)
    async def confirmation(request: Request, exc: ConfirmationRequired) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={
                "detail": {"code": "confirmation_required", "will_end_break": exc.will_end_break}
            },
        )

    @app.exception_handler(RecordNotFound)
    async def missing(request: Request, exc: RecordNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": {"code": "record_not_found"}})

    @app.exception_handler(MissingGoal)
    async def missing_goal(request: Request, exc: MissingGoal) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": {"code": "schedule_required"}})

    @app.get("/health", tags=["Health"], operation_id="getHealth")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["Health"], operation_id="getReadiness")
    async def readiness(request: Request) -> dict[str, str]:
        try:
            async with request.app.state.database.connect() as connection:
                await connection.execute(
                    text("SELECT 1 FROM work_schedules, auth_sessions, owner_binding LIMIT 0")
                )
        except SQLAlchemyError:
            raise HTTPException(status_code=503, detail="Database is not ready.") from None
        return {"status": "ok"}

    return app
