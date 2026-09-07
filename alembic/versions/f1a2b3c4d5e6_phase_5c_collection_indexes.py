"""Indexes supporting Phase 5C bounded operations collections."""

from alembic import op


revision = "f1a2b3c4d5e6"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_checkins_event_created", "check_ins", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_volunteer_applications_event_created", "volunteer_applications", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_sponsorship_inquiry_events_event_inquiry", "sponsorship_inquiry_events", ["event_id", "inquiry_id"], if_not_exists=True)
    op.create_index("ix_teams_event_created", "teams", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_staff_assignments_event_created", "staff_assignments", ["event_id", "created_at"], if_not_exists=True)


def downgrade() -> None:
    for name, table in (
        ("ix_staff_assignments_event_created", "staff_assignments"),
        ("ix_teams_event_created", "teams"),
        ("ix_sponsorship_inquiry_events_event_inquiry", "sponsorship_inquiry_events"),
        ("ix_volunteer_applications_event_created", "volunteer_applications"),
        ("ix_checkins_event_created", "check_ins"),
    ):
        op.drop_index(name, table_name=table)
