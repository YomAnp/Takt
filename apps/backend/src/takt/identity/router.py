import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from takt.database import session_factory
from takt.identity.schemas import AccessChange, LoginInput, LoginOutput, Preferences, Profile
from takt.identity.telegram import InvalidTelegramData, verify_init_data
from takt.time_accounting.access import load_actor
from takt.time_accounting.models import AuditRecord, AuthSession, OwnerBinding, User, WorkSchedule

router = APIRouter(prefix="/api/v1", tags=["Identity"])
bearer = HTTPBearer(auto_error=False)


def now() -> datetime:
    return datetime.now(UTC)


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


async def actor_id(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> UUID:
    if credentials is None or len(credentials.credentials) > 128:
        raise HTTPException(401, detail={"code": "login_required"})
    async with session_factory(request.app.state.database)() as session, session.begin():
        authentication = await session.get(AuthSession, token_hash(credentials.credentials))
        if authentication is None or authentication.expires_at <= now():
            raise HTTPException(401, detail={"code": "login_required"})
        await load_actor(session, authentication.user_id)
        return authentication.user_id


async def profile(session: AsyncSession, user: User, zone: str) -> Profile:
    end = await session.scalar(
        select(WorkSchedule.end_time)
        .where(
            WorkSchedule.user_id == user.id,
            WorkSchedule.effective_from <= now().astimezone(ZoneInfo(zone)).date(),
        )
        .order_by(WorkSchedule.effective_from.desc())
        .limit(1)
    )
    return Profile.model_validate(user).model_copy(
        update={"onboarded": user.onboarded_at is not None, "end_time": end}
    )


@router.post("/auth/telegram", response_model=LoginOutput, operation_id="loginWithTelegram")
async def login(body: LoginInput, request: Request, response: Response) -> LoginOutput:
    settings = request.app.state.settings
    if settings.bot_token is None:
        raise HTTPException(503, detail={"code": "telegram_not_configured"})
    clock = now()
    try:
        identity = verify_init_data(body.init_data, settings.bot_token.get_secret_value(), clock)
    except InvalidTelegramData:
        raise HTTPException(401, detail={"code": "invalid_telegram_data"}) from None
    async with session_factory(request.app.state.database)() as session, session.begin():
        await session.execute(
            insert(User)
            .values(
                telegram_id=identity.id,
                display_name=identity.name,
                telegram_username=identity.username,
            )
            .on_conflict_do_update(
                index_elements=[User.telegram_id], set_={"telegram_username": identity.username}
            )
        )
        user = await session.scalar(
            select(User).where(User.telegram_id == identity.id).with_for_update()
        )
        assert user is not None
        if not user.is_active:
            raise HTTPException(403, detail={"code": "account_disabled"})
        owner = await session.get(OwnerBinding, 1)
        expected = settings.superadmin_username.lstrip("@").casefold()
        if (
            owner is None
            and expected
            and identity.username
            and identity.username.casefold() == expected
        ):
            await session.execute(
                insert(OwnerBinding).values(id=1, user_id=user.id).on_conflict_do_nothing()
            )
            owner = await session.get(OwnerBinding, 1, populate_existing=True)
            if owner is not None and owner.user_id == user.id:
                user.role = "superadmin"
                session.add(
                    AuditRecord(
                        actor_id=user.id, action="owner_bound", details={"telegram_id": identity.id}
                    )
                )
        token = secrets.token_urlsafe(32)
        await session.execute(delete(AuthSession).where(AuthSession.expires_at <= clock))
        # Repeated webview openings retain only a bounded number of live sessions.
        old = (
            await session.scalars(
                select(AuthSession.token_hash)
                .where(AuthSession.user_id == user.id)
                .order_by(AuthSession.expires_at.desc())
                .offset(9)
            )
        ).all()
        if old:
            await session.execute(delete(AuthSession).where(AuthSession.token_hash.in_(old)))
        session.add(
            AuthSession(
                token_hash=token_hash(token),
                user_id=user.id,
                expires_at=clock + timedelta(hours=12),
            )
        )
        result = await profile(session, user, settings.time_zone)
    response.headers["Cache-Control"] = "no-store"
    return LoginOutput(token=token, profile=result)


@router.post("/auth/logout", status_code=204, operation_id="logout")
async def logout(
    request: Request,
    user_id: Annotated[UUID, Depends(actor_id)],
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer)],
) -> Response:
    async with session_factory(request.app.state.database)() as session, session.begin():
        await session.execute(
            delete(AuthSession).where(AuthSession.token_hash == token_hash(credentials.credentials))
        )
    return Response(status_code=204)


@router.get("/me", response_model=Profile, operation_id="getProfile")
async def me(request: Request, user_id: Annotated[UUID, Depends(actor_id)]) -> Profile:
    async with session_factory(request.app.state.database)() as session, session.begin():
        user = await load_actor(session, user_id)
        return await profile(session, user, request.app.state.settings.time_zone)


@router.put("/me/preferences", response_model=Profile, operation_id="savePreferences")
async def preferences(
    body: Preferences, request: Request, user_id: Annotated[UUID, Depends(actor_id)]
) -> Profile:
    zone = request.app.state.settings.time_zone
    clock = now()
    effective = clock.astimezone(ZoneInfo(zone)).date()
    async with session_factory(request.app.state.database)() as session, session.begin():
        user = await load_actor(session, user_id, lock=True)
        before = await profile(session, user, zone)
        if (
            before.display_name != body.display_name
            or before.end_time != body.end_time
            or not before.onboarded
        ):
            user.display_name = body.display_name
            user.onboarded_at = user.onboarded_at or clock
            await session.execute(
                insert(WorkSchedule)
                .values(user_id=user.id, effective_from=effective, end_time=body.end_time)
                .on_conflict_do_update(
                    index_elements=[WorkSchedule.user_id, WorkSchedule.effective_from],
                    set_={"end_time": body.end_time},
                )
            )
            session.add(
                AuditRecord(
                    actor_id=user.id,
                    action="preferences_saved",
                    details={
                        "before": before.model_dump(mode="json"),
                        "end_time": body.end_time.isoformat(),
                        "display_name": body.display_name,
                        "effective_from": effective.isoformat(),
                    },
                )
            )
        return await profile(session, user, zone)


@router.get("/admin/users", response_model=list[Profile], operation_id="listUsers")
async def users(
    request: Request,
    user_id: Annotated[UUID, Depends(actor_id)],
    q: Annotated[str, Query(max_length=80)] = "",
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[Profile]:
    async with session_factory(request.app.state.database)() as session, session.begin():
        actor = await load_actor(session, user_id)
        if actor.role not in {"admin", "superadmin"}:
            raise HTTPException(403, detail={"code": "admin_required"})
        query = select(User).order_by(User.created_at, User.id).offset(offset).limit(30)
        if q:
            # Treat search text literally, rather than as SQL LIKE wildcards.
            search = (
                "%"
                + q.lstrip("@").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            query = query.where(
                or_(
                    User.display_name.ilike(search, escape="\\"),
                    User.telegram_username.ilike(search.lstrip("@"), escape="\\"),
                )
            )
        records = (await session.scalars(query)).all()
        return [
            await profile(session, record, request.app.state.settings.time_zone)
            for record in records
        ]


@router.patch("/admin/users/{target_id}", response_model=Profile, operation_id="manageUser")
async def manage(
    target_id: UUID,
    body: AccessChange,
    request: Request,
    user_id: Annotated[UUID, Depends(actor_id)],
) -> Profile:
    async with session_factory(request.app.state.database)() as session, session.begin():
        records = (
            await session.scalars(
                select(User)
                .where(User.id.in_([user_id, target_id]))
                .order_by(User.id)
                .with_for_update()
            )
        ).all()
        actor = next((item for item in records if item.id == user_id and item.is_active), None)
        target = next((item for item in records if item.id == target_id), None)
        if actor is None or actor.role not in {"admin", "superadmin"}:
            raise HTTPException(403, detail={"code": "admin_required"})
        if target is None:
            raise HTTPException(404, detail={"code": "user_not_found"})
        if target.id == actor.id or target.role == "superadmin":
            raise HTTPException(409, detail={"code": "protected_account"})
        if body.role is not None and actor.role != "superadmin":
            raise HTTPException(403, detail={"code": "owner_required"})
        if target.role == "admin" and actor.role != "superadmin":
            raise HTTPException(403, detail={"code": "owner_required"})
        before = {"role": target.role, "is_active": target.is_active}
        if body.role is not None:
            target.role = body.role
        if body.is_active is not None:
            target.is_active = body.is_active
        after = {"role": target.role, "is_active": target.is_active}
        if before != after:
            if not target.is_active:
                await session.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
            session.add(
                AuditRecord(
                    actor_id=actor.id,
                    action="access_changed",
                    details={"user_id": str(target.id), "before": before, "after": after},
                )
            )
        return await profile(session, target, request.app.state.settings.time_zone)
