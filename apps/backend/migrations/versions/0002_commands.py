"""Attendance revisions and idempotent command receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_commands"
down_revision = "0001_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "attendance", sa.Column("revision", sa.Integer(), server_default="1", nullable=False)
    )
    op.create_check_constraint("positive_attendance_revision", "attendance", "revision > 0")
    op.create_table(
        "time_command_receipts",
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("request_id", postgresql.UUID(), nullable=False),
        sa.Column("attendance_id", postgresql.UUID(), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("parameters", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_time_command_receipts_user_id"),
        sa.ForeignKeyConstraint(
            ["attendance_id"], ["attendance.id"], name="fk_time_command_receipts_attendance_id"
        ),
        sa.PrimaryKeyConstraint("user_id", "request_id", name="pk_time_command_receipts"),
    )
    op.create_index(
        "ix_time_command_receipts_attendance_id", "time_command_receipts", ["attendance_id"]
    )


def downgrade() -> None:
    op.drop_table("time_command_receipts")
    op.drop_constraint("positive_attendance_revision", "attendance", type_="check")
    op.drop_column("attendance", "revision")
