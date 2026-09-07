"""Add reusable event template snapshots."""

from alembic import op
import sqlalchemy as sa

from app.core.base_model import UUIDType

revision = "m8b9c0d1e2f3"
down_revision = "l7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_templates",
        sa.Column("id", UUIDType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("owner_user_id", UUIDType, nullable=False),
        sa.Column("organization_id", UUIDType, nullable=True),
        sa.Column("source_event_id", UUIDType, nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["source_event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_templates_owner_user_id", "event_templates", ["owner_user_id"])
    op.create_index("ix_event_templates_owner_archived", "event_templates", ["owner_user_id", "is_archived", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_event_templates_owner_archived", table_name="event_templates")
    op.drop_index("ix_event_templates_owner_user_id", table_name="event_templates")
    op.drop_table("event_templates")
