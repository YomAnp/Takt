import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from takt.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role IN ('member', 'admin')", name="valid_user_role"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    role: Mapped[str] = mapped_column(String(16), server_default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TimeGoal(Base):
    __tablename__ = "time_goals"
    __table_args__ = (
        UniqueConstraint("user_id", "effective_from"),
        CheckConstraint("required_minutes BETWEEN 1 AND 1440", name="valid_required_minutes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    required_minutes: Mapped[int] = mapped_column(Integer)


class AttendanceRecord(Base):
    __tablename__ = "attendance"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="positive_attendance"),
        ExcludeConstraint(
            ("user_id", "="),
            (func.tstzrange(text("started_at"), text("ended_at"), text("'[)'")), "&&"),
            using="gist",
            name="attendance_no_overlap",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    breaks: Mapped[list["BreakRecord"]] = relationship(
        back_populates="attendance", lazy="raise", order_by="BreakRecord.started_at"
    )


class BreakRecord(Base):
    __tablename__ = "breaks"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at > started_at", name="positive_break"),
        ExcludeConstraint(
            ("attendance_id", "="),
            (func.tstzrange(text("started_at"), text("ended_at"), text("'[)'")), "&&"),
            using="gist",
            name="breaks_no_overlap",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    attendance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attendance.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attendance: Mapped[AttendanceRecord] = relationship(back_populates="breaks")


class AuditRecord(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
