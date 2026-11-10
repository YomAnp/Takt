from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Period = Literal["week", "month", "all"]
Scope = Literal["global", "friends"]
SocialStatus = Literal["working", "on_break", "smoking", "away", "needs_checkout"]


class Peer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    photo_url: str | None = None


class FriendSummary(Peer):
    friendship_id: UUID | None = None
    status: SocialStatus
    status_since: AwareDatetime | None
    confirmed_seconds: int = Field(ge=0)


class FriendProfile(FriendSummary):
    period_start: date | None
    period_end: date


class FriendRequestOutput(BaseModel):
    id: UUID
    user: Peer
    created_at: AwareDatetime
    direction: Literal["incoming", "outgoing"]


class FriendsPage(BaseModel):
    items: list[FriendSummary]
    total: int
    incoming: list[FriendRequestOutput]
    outgoing: list[FriendRequestOutput]
    as_of: AwareDatetime


class InviteOutput(BaseModel):
    token: str
    url: str
    expires_at: AwareDatetime


class InvitePreview(BaseModel):
    user: Peer
    expires_at: AwareDatetime
    is_self: bool
    already_friends: bool
    pending_request_id: UUID | None


class FriendRequestInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_token: str = Field(pattern=r"^[A-Za-z0-9_-]{32,64}$")


class RequestResult(BaseModel):
    request: FriendRequestOutput | None
    status: Literal["incoming", "outgoing", "accepted"]


class LeaderboardEntry(BaseModel):
    rank: int
    user: Peer
    seconds: int = Field(ge=0)
    is_self: bool


class LeaderboardPage(BaseModel):
    items: list[LeaderboardEntry]
    total: int
    current_user: LeaderboardEntry | None
    scope: Scope
    period: Period
    period_start: date | None
    period_end: date
    participating: bool
    as_of: AwareDatetime
