"""phase 23 participant discovery dismissal state"""
from alembic import op
import sqlalchemy as sa

revision = "y0b1c2d3e4f5"
down_revision = "x9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "networking_dismissals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("requester_id", sa.UUID(), nullable=False),
        sa.Column("participant_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "requester_id", "participant_id", name="uq_networking_dismissal_event_requester_participant"),
    )
    op.create_index("ix_networking_dismissals_event_requester", "networking_dismissals", ["event_id", "requester_id", "created_at"])


def downgrade():
    op.drop_index("ix_networking_dismissals_event_requester", table_name="networking_dismissals")
    op.drop_table("networking_dismissals")
