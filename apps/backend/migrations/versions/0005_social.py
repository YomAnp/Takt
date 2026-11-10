"""Optional public ranking, friends and named breaks; retain existing attendance."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_social"
down_revision = "0004_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("photo_url", sa.String(2048), nullable=True))
    op.add_column(
        "users",
        sa.Column("leaderboard_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "breaks", sa.Column("kind", sa.String(16), server_default="regular", nullable=False)
    )
    op.create_check_constraint("valid_break_kind", "breaks", "kind IN ('regular', 'smoke')")
    op.create_index("ix_attendance_started_at", "attendance", ["started_at"])
    op.create_table(
        "friend_invites",
        sa.Column("user_id", postgresql.UUID(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "friend_requests",
        sa.Column("id", postgresql.UUID(), primary_key=True),
        sa.Column("user_low", postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_high", postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("requested_by", postgresql.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("user_low < user_high", name="ordered_request_pair"),
        sa.CheckConstraint("requested_by IN (user_low, user_high)", name="request_party"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled')",
            name="valid_friend_request_status",
        ),
    )
    op.create_index(
        "uq_friend_requests_pending_pair",
        "friend_requests",
        ["user_low", "user_high"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_friend_requests_sender_created", "friend_requests", ["requested_by", "created_at"]
    )
    op.create_table(
        "friendships",
        sa.Column("id", postgresql.UUID(), nullable=False, unique=True),
        sa.Column("user_low", postgresql.UUID(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("user_high", postgresql.UUID(), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("user_low < user_high", name="ordered_friend_pair"),
    )


def downgrade() -> None:
    op.drop_table("friendships")
    op.drop_table("friend_requests")
    op.drop_table("friend_invites")
    op.drop_index("ix_attendance_started_at", table_name="attendance")
    op.drop_constraint("valid_break_kind", "breaks", type_="check")
    op.drop_column("breaks", "kind")
    op.drop_column("users", "leaderboard_enabled")
    op.drop_column("users", "photo_url")
