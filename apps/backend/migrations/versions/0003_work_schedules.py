"""Effective-dated fixed workday endings."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_work_schedules"
down_revision = "0002_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "work_schedules",
        sa.Column("id", postgresql.UUID(), nullable=False),
        sa.Column("user_id", postgresql.UUID(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_work_schedules_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_work_schedules"),
        sa.UniqueConstraint("user_id", "effective_from", name="uq_work_schedules_user_id"),
    )


def downgrade() -> None:
    op.drop_table("work_schedules")
