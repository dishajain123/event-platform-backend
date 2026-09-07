"""Add indexes for Phase 5 bounded collection queries.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""

from alembic import op


revision = "e8f9a0b1c2d3"
down_revision = "d7e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_registrations_event_created", "registrations", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_registration_participants_name", "registration_participants", ["full_name"], if_not_exists=True)
    op.create_index("ix_payments_event_created", "payments", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_refunds_payment_status", "refunds", ["payment_id", "status"], if_not_exists=True)
    op.create_index("ix_notifications_recipient_created", "notifications", ["recipient_user_id", "created_at"], if_not_exists=True)
    op.create_index("ix_notifications_event_created", "notifications", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_feedback_event_created", "event_feedback", ["event_id", "created_at"], if_not_exists=True)
    op.create_index("ix_audit_entity_created", "audit_logs", ["entity_type", "entity_id", "created_at"], if_not_exists=True)


def downgrade() -> None:
    for name, table in (
        ("ix_audit_entity_created", "audit_logs"),
        ("ix_feedback_event_created", "event_feedback"),
        ("ix_notifications_event_created", "notifications"),
        ("ix_notifications_recipient_created", "notifications"),
        ("ix_refunds_payment_status", "refunds"),
        ("ix_payments_event_created", "payments"),
        ("ix_registration_participants_name", "registration_participants"),
        ("ix_registrations_event_created", "registrations"),
    ):
        op.drop_index(name, table_name=table)
