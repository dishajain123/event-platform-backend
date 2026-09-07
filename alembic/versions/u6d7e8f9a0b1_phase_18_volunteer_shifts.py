"""phase 18 volunteer shifts and attendance"""
from alembic import op
import sqlalchemy as sa

revision = "u6d7e8f9a0b1"
down_revision = "t5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "volunteer_shifts",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("location", sa.String(255)), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False), sa.Column("required_count", sa.Integer(), nullable=False), sa.Column("required_role", sa.String(120)), sa.Column("status", sa.Enum("DRAFT", "OPEN", "FULL", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="volunteershiftstatus"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_volunteer_shifts_status", "volunteer_shifts", ["status"])
    op.create_index("ix_volunteer_shifts_event_status_start", "volunteer_shifts", ["event_id", "status", "starts_at"])
    op.create_table(
        "volunteer_shift_assignments",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("shift_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("volunteer_application_id", sa.UUID()), sa.Column("status", sa.Enum("REQUESTED", "APPROVED", "ACTIVE", "COMPLETED", "REJECTED", "CANCELLED", name="volunteerassignmentstatus"), nullable=False), sa.Column("requested_by", sa.UUID(), nullable=False), sa.Column("reviewed_by", sa.UUID()), sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.Column("check_in_at", sa.DateTime(timezone=True)), sa.Column("check_out_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["shift_id"], ["volunteer_shifts.id"]), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.ForeignKeyConstraint(["volunteer_application_id"], ["volunteer_applications.id"]), sa.ForeignKeyConstraint(["requested_by"], ["users.id"]), sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("shift_id", "user_id", name="uq_volunteer_shift_assignment_user"),
    )
    op.create_index("ix_volunteer_shift_assignments_status", "volunteer_shift_assignments", ["status"])
    op.create_index("ix_volunteer_shift_assignments_event_status", "volunteer_shift_assignments", ["event_id", "status", "created_at"])
    op.create_index("ix_volunteer_shift_assignments_user_status", "volunteer_shift_assignments", ["user_id", "status"])
    op.create_table(
        "volunteer_attendance",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("shift_id", sa.UUID(), nullable=False), sa.Column("assignment_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("status", sa.Enum("NOT_CHECKED_IN", "CHECKED_IN", "CHECKED_OUT", "NO_SHOW", "CANCELLED", name="volunteerattendancestatus"), nullable=False), sa.Column("first_check_in_at", sa.DateTime(timezone=True)), sa.Column("final_check_out_at", sa.DateTime(timezone=True)), sa.Column("worked_seconds", sa.Integer()), sa.Column("notes", sa.Text()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["shift_id"], ["volunteer_shifts.id"]), sa.ForeignKeyConstraint(["assignment_id"], ["volunteer_shift_assignments.id"]), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("assignment_id", name="uq_volunteer_attendance_assignment"),
    )
    op.create_index("ix_volunteer_attendance_status", "volunteer_attendance", ["status"])
    op.create_index("ix_volunteer_attendance_event_status", "volunteer_attendance", ["event_id", "status", "created_at"])


def downgrade():
    op.drop_index("ix_volunteer_attendance_event_status", table_name="volunteer_attendance")
    op.drop_index("ix_volunteer_attendance_status", table_name="volunteer_attendance")
    op.drop_table("volunteer_attendance")
    op.drop_index("ix_volunteer_shift_assignments_user_status", table_name="volunteer_shift_assignments")
    op.drop_index("ix_volunteer_shift_assignments_event_status", table_name="volunteer_shift_assignments")
    op.drop_index("ix_volunteer_shift_assignments_status", table_name="volunteer_shift_assignments")
    op.drop_table("volunteer_shift_assignments")
    op.drop_index("ix_volunteer_shifts_event_status_start", table_name="volunteer_shifts")
    op.drop_index("ix_volunteer_shifts_status", table_name="volunteer_shifts")
    op.drop_table("volunteer_shifts")
    op.execute("DROP TYPE IF EXISTS volunteerattendancestatus")
    op.execute("DROP TYPE IF EXISTS volunteerassignmentstatus")
    op.execute("DROP TYPE IF EXISTS volunteershiftstatus")
