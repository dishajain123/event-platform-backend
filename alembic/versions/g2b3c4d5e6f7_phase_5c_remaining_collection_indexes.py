"""Indexes for remaining bounded event collections."""

from alembic import op


revision = "g2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_assistance_requests_event_created", "assistance_requests", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_media_event_sort_created", "media", ["event_id", "sort_order", "created_at"], if_not_exists=True)
    op.create_index("ix_entries_stage_created", "entries", ["current_stage_id", "created_at"], if_not_exists=True)


def downgrade() -> None:
    op.drop_index("ix_entries_stage_created", table_name="entries")
    op.drop_index("ix_media_event_sort_created", table_name="media")
    op.drop_index("ix_assistance_requests_event_created", table_name="assistance_requests")
