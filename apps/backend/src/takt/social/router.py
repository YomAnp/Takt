from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from takt.database import session_factory
from takt.identity.router import actor_id
from takt.social import friends
from takt.social.ranking import leaderboard
from takt.social.schemas import (
    FriendProfile,
    FriendRequestInput,
    FriendsPage,
    InviteOutput,
    InvitePreview,
    LeaderboardPage,
    Period,
    RequestResult,
    Scope,
)

router = APIRouter(prefix="/api/v1/social", tags=["Friends and presence"])
Actor = Annotated[UUID, Depends(actor_id)]


async def read_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_factory(request.app.state.database)() as session, session.begin():
        await session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        yield session


async def write_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with session_factory(request.app.state.database)() as session, session.begin():
        yield session


ReadSession = Annotated[AsyncSession, Depends(read_session)]
WriteSession = Annotated[AsyncSession, Depends(write_session)]


@router.get("/friends", response_model=FriendsPage, operation_id="getFriendsPage")
async def list_friends(
    request: Request,
    user_id: Actor,
    session: ReadSession,
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> FriendsPage:
    return await friends.friends_page(
        session, user_id, datetime.now(UTC), ZoneInfo(request.app.state.settings.time_zone), offset
    )


@router.post("/invite", response_model=InviteOutput, operation_id="createFriendInvite")
async def create_invite(request: Request, user_id: Actor, session: WriteSession) -> InviteOutput:
    return await friends.personal_invite(
        session, user_id, datetime.now(UTC), request.app.state.settings.bot_username
    )


@router.get("/invites/{token}", response_model=InvitePreview, operation_id="previewFriendInvite")
async def inspect_invite(
    token: Annotated[str, Path(min_length=32, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")],
    user_id: Actor,
    session: ReadSession,
) -> InvitePreview:
    return await friends.preview_invite(session, user_id, token, datetime.now(UTC))


@router.post("/requests", response_model=RequestResult, operation_id="sendFriendRequest")
async def request_friend(
    body: FriendRequestInput, user_id: Actor, session: WriteSession
) -> RequestResult:
    return await friends.send_request(session, user_id, body.invite_token, datetime.now(UTC))


@router.post(
    "/requests/{request_id}/{action}", status_code=204, operation_id="respondToFriendRequest"
)
async def respond_to_request(
    request_id: UUID,
    action: Literal["accept", "decline", "cancel"],
    user_id: Actor,
    session: WriteSession,
) -> Response:
    await friends.respond(session, user_id, request_id, action, datetime.now(UTC))
    return Response(status_code=204)


@router.get("/friends/{friend_id}", response_model=FriendProfile, operation_id="getFriendProfile")
async def get_friend_profile(
    friend_id: UUID,
    request: Request,
    user_id: Actor,
    session: ReadSession,
    period: Period = "week",
) -> FriendProfile:
    return await friends.friend_profile(
        session,
        user_id,
        friend_id,
        datetime.now(UTC),
        ZoneInfo(request.app.state.settings.time_zone),
        period,
    )


@router.delete("/friends/{friend_id}", status_code=204, operation_id="removeFriend")
async def delete_friend(
    friend_id: UUID, user_id: Actor, session: WriteSession, friendship_id: UUID | None = None
) -> Response:
    await friends.remove_friend(session, user_id, friend_id, friendship_id=friendship_id)
    return Response(status_code=204)


@router.get("/leaderboard", response_model=LeaderboardPage, operation_id="getLeaderboard")
async def get_leaderboard(
    request: Request,
    user_id: Actor,
    session: ReadSession,
    scope: Scope = "global",
    period: Period = "week",
    offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0,
) -> LeaderboardPage:
    return await leaderboard(
        session,
        user_id,
        clock=datetime.now(UTC),
        zone=ZoneInfo(request.app.state.settings.time_zone),
        scope=scope,
        period=period,
        offset=offset,
    )
