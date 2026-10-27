import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from takt.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('member', 'admin', 'superadmin')", name="valid_user_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str] = mapped_column(String(80), server_default="")
    telegram_username: Mapped[str | None] = mapped_column(String(64))
    onboarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        CheckConstraint("revision > 0", name="positive_attendance_revision"),
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
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
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


class CommandReceipt(Base):
    __tablename__ = "time_command_receipts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    attendance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("attendance.id"), index=True)
    operation: Mapped[str] = mapped_column(String(32))
    parameters: Mapped[dict[str, object]] = mapped_column(JSONB)
    result: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkSchedule(Base):
    __tablename__ = "work_schedules"
    __table_args__ = (UniqueConstraint("user_id", "effective_from"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    effective_from: Mapped[date] = mapped_column(Date)
    end_time: Mapped[time] = mapped_column(Time)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OwnerBinding(Base):
    __tablename__ = "owner_binding"
    __table_args__ = (CheckConstraint("id = 1", name="single_owner"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True)
