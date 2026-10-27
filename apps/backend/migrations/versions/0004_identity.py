"""Telegram profiles, sessions and the explicitly configured owner."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_identity"
down_revision = "0003_work_schedules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("display_name", sa.String(80), nullable=False, server_default="")
    )
    op.add_column("users", sa.Column("telegram_username", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_constraint("valid_user_role", "users", type_="check")
    op.create_check_constraint(
        "valid_user_role", "users", "role IN ('member', 'admin', 'superadmin')"
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("users.id", name="fk_auth_sessions_user_id"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "owner_binding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(),
            sa.ForeignKey("users.id", name="fk_owner_binding_user_id"),
            nullable=False,
            unique=True,
        ),
        sa.CheckConstraint("id = 1", name="single_owner"),
    )


def downgrade() -> None:
    op.drop_table("owner_binding")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'superadmin'")
    op.drop_constraint("valid_user_role", "users", type_="check")
    op.create_check_constraint("valid_user_role", "users", "role IN ('member', 'admin')")
    op.drop_column("users", "onboarded_at")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "display_name")
