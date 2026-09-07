"""Add event-scoped operational incidents."""

from alembic import op
import sqlalchemy as sa

from app.core.base_model import UUIDType

revision = "i4d5e6f7a8b9"
down_revision = "h3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", UUIDType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", UUIDType, nullable=False),
        sa.Column("reporter_user_id", UUIDType, nullable=False),
        sa.Column("assigned_user_id", UUIDType, nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "CLOSED", "CANCELLED", name="incidentstatus"), nullable=False),
        sa.Column("severity", sa.Enum("LOW", "MEDIUM", "HIGH", "CRITICAL", name="incidentseverity"), nullable=False),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("in_progress_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_incidents_event_status_created", "incidents", ["event_id", "status", "created_at", "id"])
    op.create_index("ix_incidents_event_severity_created", "incidents", ["event_id", "severity", "created_at", "id"])
    op.create_index("ix_incidents_assignee_status", "incidents", ["assigned_user_id", "status", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_incidents_assignee_status", table_name="incidents")
    op.drop_index("ix_incidents_event_severity_created", table_name="incidents")
    op.drop_index("ix_incidents_event_status_created", table_name="incidents")
    op.drop_table("incidents")
    op.execute("DROP TYPE IF EXISTS incidentseverity")
    op.execute("DROP TYPE IF EXISTS incidentstatus")
