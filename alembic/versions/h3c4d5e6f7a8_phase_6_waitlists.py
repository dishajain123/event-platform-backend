"""Add event-scoped waitlist entries."""

from alembic import op
import sqlalchemy as sa

from app.core.base_model import UUIDType


revision = "h3c4d5e6f7a8"
down_revision = "g2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "waitlist_entries",
        sa.Column("id", UUIDType, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", UUIDType, nullable=False),
        sa.Column("user_id", UUIDType, nullable=False),
        sa.Column("child_id", UUIDType, nullable=True),
        sa.Column("team_id", UUIDType, nullable=True),
        sa.Column("participation_type", sa.String(length=50), nullable=False),
        sa.Column("status", sa.Enum("WAITING", "PROMOTED", "EXPIRED", "LEFT", "CLOSED", name="waitliststatus"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("promotion_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["child_id"], ["child_profiles.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", "child_id", "team_id", "participation_type", "status", name="uq_waitlist_active_identity"),
    )
    op.create_index("ix_waitlist_entries_event_id", "waitlist_entries", ["event_id"])
    op.create_index("ix_waitlist_entries_user_id", "waitlist_entries", ["user_id"])
    op.create_index("ix_waitlist_entries_status", "waitlist_entries", ["status"])
    op.create_index("ix_waitlist_entries_fifo", "waitlist_entries", ["event_id", "participation_type", "status", "joined_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_waitlist_entries_fifo", table_name="waitlist_entries")
    op.drop_index("ix_waitlist_entries_status", table_name="waitlist_entries")
    op.drop_index("ix_waitlist_entries_user_id", table_name="waitlist_entries")
    op.drop_index("ix_waitlist_entries_event_id", table_name="waitlist_entries")
    op.drop_table("waitlist_entries")
    op.execute("DROP TYPE IF EXISTS waitliststatus")
