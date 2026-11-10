import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from takt.database import Base


class FriendInvite(Base):
    __tablename__ = "friend_invites"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FriendRequest(Base):
    __tablename__ = "friend_requests"
    __table_args__ = (
        CheckConstraint("user_low < user_high", name="ordered_request_pair"),
        CheckConstraint("requested_by IN (user_low, user_high)", name="request_party"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled')",
            name="valid_friend_request_status",
        ),
        Index(
            "uq_friend_requests_pending_pair",
            "user_low",
            "user_high",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_friend_requests_sender_created", "requested_by", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_low: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    user_high: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Friendship(Base):
    __tablename__ = "friendships"
    __table_args__ = (CheckConstraint("user_low < user_high", name="ordered_friend_pair"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, default=uuid.uuid4, unique=True)
    user_low: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    user_high: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
