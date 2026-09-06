"""event-scoped volunteer applications and activation links"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "8c9d0e1f2a34"
down_revision: Union[str, None] = "7b8c9d0e1f23"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    status_enum = postgresql.ENUM(
        "SUBMITTED", "UNDER_REVIEW", "CONTACTED", "APPROVED", "REJECTED",
        name="volunteerapplicationstatus",
    )
    status_enum.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "volunteer_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("skills_experience", sa.Text(), nullable=True),
        sa.Column("availability", sa.Text(), nullable=True),
        sa.Column("preferred_responsibility", sa.String(length=255), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", postgresql.ENUM(
            "SUBMITTED", "UNDER_REVIEW", "CONTACTED", "APPROVED", "REJECTED",
            name="volunteerapplicationstatus", create_type=False,
        ), nullable=False),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_staff_assignment_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["activated_staff_assignment_id"], ["staff_assignments.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_volunteer_application_event_user"),
    )
    op.create_index("ix_volunteer_applications_event_id", "volunteer_applications", ["event_id"])
    op.create_index("ix_volunteer_applications_user_id", "volunteer_applications", ["user_id"])
    op.create_index("ix_volunteer_applications_status", "volunteer_applications", ["status"])
    op.add_column("event_configurations", sa.Column("volunteer_open", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("event_configurations", "volunteer_open")
    op.drop_index("ix_volunteer_applications_status", table_name="volunteer_applications")
    op.drop_index("ix_volunteer_applications_user_id", table_name="volunteer_applications")
    op.drop_index("ix_volunteer_applications_event_id", table_name="volunteer_applications")
    op.drop_table("volunteer_applications")
    postgresql.ENUM(name="volunteerapplicationstatus").drop(op.get_bind(), checkfirst=True)
