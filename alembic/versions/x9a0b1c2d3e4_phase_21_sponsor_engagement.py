"""phase 21 sponsor engagement and lead analytics"""
from alembic import op
import sqlalchemy as sa

revision = "x9a0b1c2d3e4"
down_revision = "w8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sponsor_engagements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sponsor_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("participant_id", sa.UUID(), nullable=False),
        sa.Column("captured_by", sa.UUID(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engagement_type", sa.Enum("LEAD_CAPTURE", "BOOTH_VISIT", "SESSION_INTEREST", "SPONSOR_INTERACTION", name="sponsorengagementtype"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("consent_status", sa.Enum("NOT_GIVEN", "GIVEN", "WITHDRAWN", name="sponsorconsentstatus"), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_source", sa.String(length=80), nullable=True),
        sa.Column("lead_status", sa.Enum("CAPTURED", "QUALIFIED", "CONTACTED", "CONVERTED", "DISMISSED", "UNSUBSCRIBED", name="sponsorleadstatus"), nullable=False),
        sa.ForeignKeyConstraint(["sponsor_id"], ["sponsors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["participant_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["captured_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sponsor_id", "event_id", "participant_id", "engagement_type", name="uq_sponsor_engagement_identity"),
    )
    op.create_index("ix_sponsor_engagements_event_sponsor_status", "sponsor_engagements", ["event_id", "sponsor_id", "lead_status", "captured_at"])
    op.create_index("ix_sponsor_engagements_event_participant", "sponsor_engagements", ["event_id", "participant_id", "captured_at"])
    op.create_index("ix_sponsor_engagements_sponsor_type", "sponsor_engagements", ["sponsor_id", "engagement_type", "captured_at"])


def downgrade():
    op.drop_index("ix_sponsor_engagements_sponsor_type", table_name="sponsor_engagements")
    op.drop_index("ix_sponsor_engagements_event_participant", table_name="sponsor_engagements")
    op.drop_index("ix_sponsor_engagements_event_sponsor_status", table_name="sponsor_engagements")
    op.drop_table("sponsor_engagements")
    op.execute("DROP TYPE IF EXISTS sponsorleadstatus")
    op.execute("DROP TYPE IF EXISTS sponsorconsentstatus")
    op.execute("DROP TYPE IF EXISTS sponsorengagementtype")
