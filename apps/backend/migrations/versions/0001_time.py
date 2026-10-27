"""Initial time accounting schema."""

from alembic import op

revision = "0001_time"
down_revision = None
branch_labels = None
depends_on = None

STATEMENTS = (
    """CREATE EXTENSION IF NOT EXISTS btree_gist""",
    """CREATE TABLE users (
	id UUID NOT NULL,
	telegram_id BIGINT,
	role VARCHAR(16) DEFAULT 'member' NOT NULL,
	is_active BOOLEAN DEFAULT true NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_users PRIMARY KEY (id),
	CONSTRAINT valid_user_role CHECK (role IN ('member', 'admin')),
	CONSTRAINT uq_users_telegram_id UNIQUE (telegram_id)
)""",
    """CREATE TABLE attendance (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_attendance PRIMARY KEY (id),
	CONSTRAINT positive_attendance CHECK (ended_at IS NULL OR ended_at > started_at),
	CONSTRAINT attendance_no_overlap EXCLUDE USING gist (user_id WITH =,
        tstzrange(started_at, ended_at, '[)') WITH &&),
	CONSTRAINT fk_attendance_user_id FOREIGN KEY(user_id) REFERENCES users (id)
)""",
    """CREATE TABLE audit_log (
	id UUID NOT NULL,
	actor_id UUID NOT NULL,
	action VARCHAR(64) NOT NULL,
	details JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	CONSTRAINT pk_audit_log PRIMARY KEY (id),
	CONSTRAINT fk_audit_log_actor_id FOREIGN KEY(actor_id) REFERENCES users (id)
)""",
    """CREATE TABLE time_goals (
	id UUID NOT NULL,
	user_id UUID NOT NULL,
	effective_from DATE NOT NULL,
	required_minutes INTEGER NOT NULL,
	CONSTRAINT pk_time_goals PRIMARY KEY (id),
	CONSTRAINT uq_time_goals_user_id UNIQUE (user_id, effective_from),
	CONSTRAINT valid_required_minutes CHECK (required_minutes BETWEEN 1 AND 1440),
	CONSTRAINT fk_time_goals_user_id FOREIGN KEY(user_id) REFERENCES users (id)
)""",
    """CREATE TABLE breaks (
	id UUID NOT NULL,
	attendance_id UUID NOT NULL,
	started_at TIMESTAMP WITH TIME ZONE NOT NULL,
	ended_at TIMESTAMP WITH TIME ZONE,
	CONSTRAINT pk_breaks PRIMARY KEY (id),
	CONSTRAINT positive_break CHECK (ended_at IS NULL OR ended_at > started_at),
	CONSTRAINT breaks_no_overlap EXCLUDE USING gist (attendance_id WITH =,
        tstzrange(started_at, ended_at, '[)') WITH &&),
	CONSTRAINT fk_breaks_attendance_id FOREIGN KEY(attendance_id) REFERENCES attendance (id)
)""",
    """CREATE INDEX ix_breaks_attendance_id ON breaks (attendance_id)""",
    """CREATE FUNCTION validate_break_bounds() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent attendance%ROWTYPE;
BEGIN
  SELECT * INTO parent FROM attendance WHERE id = NEW.attendance_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Attendance does not exist' USING ERRCODE = '23503';
  END IF;
  IF NEW.started_at < parent.started_at OR
     (parent.ended_at IS NOT NULL AND
       (NEW.ended_at IS NULL OR NEW.ended_at > parent.ended_at)) THEN
    RAISE EXCEPTION 'Break must remain inside attendance' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$""",
    """CREATE TRIGGER check_break_bounds BEFORE INSERT OR UPDATE ON breaks
FOR EACH ROW EXECUTE FUNCTION validate_break_bounds()""",
    """CREATE FUNCTION validate_attendance_bounds() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM breaks WHERE attendance_id = NEW.id AND
      (started_at < NEW.started_at OR
        (NEW.ended_at IS NOT NULL AND (ended_at IS NULL OR ended_at > NEW.ended_at)))
  ) THEN
    RAISE EXCEPTION 'Attendance must contain all its breaks' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$""",
    """CREATE TRIGGER check_attendance_bounds BEFORE UPDATE ON attendance
FOR EACH ROW EXECUTE FUNCTION validate_attendance_bounds()""",
)


def upgrade() -> None:
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("breaks")
    op.drop_table("attendance")
    op.drop_table("time_goals")
    op.drop_table("users")
    op.execute("DROP FUNCTION validate_break_bounds()")
    op.execute("DROP FUNCTION validate_attendance_bounds()")
