"""Add sponsor committed values and auditable deliverables."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.core.base_model import UUIDType

revision = "l7a8b9c0d1e2"
down_revision = "k6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("COMPLETED", "CANCELLED"):
        op.execute(f"ALTER TYPE sponsorstatus ADD VALUE IF NOT EXISTS '{value}'")
    op.add_column("sponsors", sa.Column("committed_value", sa.Numeric(12, 2), nullable=True))
    op.add_column("sponsors", sa.Column("paid_value", sa.Numeric(12, 2), nullable=True))
    # Create the named PostgreSQL type explicitly and prevent SQLAlchemy's
    # table DDL hook from attempting to create it a second time. This makes
    # retries safe when a prior migration attempt or an existing deployment
    # already contains the enum.
    deliverable_status = postgresql.ENUM(
        "PENDING", "IN_PROGRESS", "COMPLETED", "CANCELLED",
        name="sponsorshipdeliverablestatus", create_type=False,
    )
    deliverable_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "sponsorship_deliverables",
        sa.Column("id", UUIDType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sponsor_id", UUIDType, nullable=False),
        sa.Column("event_id", UUIDType, nullable=False),
        sa.Column("deliverable_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", deliverable_status, nullable=False, server_default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_notes", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["sponsor_id"], ["sponsors.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sponsorship_deliverables_sponsor_status_due", "sponsorship_deliverables", ["sponsor_id", "status", "due_date"])
    op.create_index("ix_sponsorship_deliverables_event_status_due", "sponsorship_deliverables", ["event_id", "status", "due_date"])


def downgrade() -> None:
    op.drop_index("ix_sponsorship_deliverables_event_status_due", table_name="sponsorship_deliverables")
    op.drop_index("ix_sponsorship_deliverables_sponsor_status_due", table_name="sponsorship_deliverables")
    op.drop_table("sponsorship_deliverables")
    op.execute("DROP TYPE IF EXISTS sponsorshipdeliverablestatus")
    op.drop_column("sponsors", "paid_value")
    op.drop_column("sponsors", "committed_value")
