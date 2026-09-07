"""Add venue availability/capacity and transactional schedule metadata."""

from alembic import op
import sqlalchemy as sa

from app.core.base_model import UUIDType

revision = "k6f7a8b9c0d1"
down_revision = "j5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("venues", sa.Column("capacity", sa.Integer(), nullable=True))
    op.add_column("venues", sa.Column("availability", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("venues", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_index("ix_venues_shared_id", "venues", ["id", "is_shared"])

    schedule_status = sa.Enum("SCHEDULED", "CANCELLED", "COMPLETED", name="schedulestatus")
    schedule_status.create(op.get_bind(), checkfirst=True)
    op.add_column("schedule_items", sa.Column("resource_key", sa.String(length=120), nullable=True))
    op.add_column("schedule_items", sa.Column("expected_capacity", sa.Integer(), nullable=True))
    op.add_column("schedule_items", sa.Column("status", schedule_status, nullable=False, server_default="SCHEDULED"))
    op.create_index("ix_schedule_items_venue_window", "schedule_items", ["venue_id", "start_time", "end_time", "status"])
    op.create_index("ix_schedule_items_resource_window", "schedule_items", ["resource_key", "start_time", "end_time", "status"])


def downgrade() -> None:
    op.drop_index("ix_schedule_items_resource_window", table_name="schedule_items")
    op.drop_index("ix_schedule_items_venue_window", table_name="schedule_items")
    op.drop_column("schedule_items", "status")
    op.drop_column("schedule_items", "expected_capacity")
    op.drop_column("schedule_items", "resource_key")
    op.execute("DROP TYPE IF EXISTS schedulestatus")
    op.drop_index("ix_venues_shared_id", table_name="venues")
    op.drop_column("venues", "is_shared")
    op.drop_column("venues", "availability")
    op.drop_column("venues", "capacity")
