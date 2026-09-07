"""add durable payment webhook inbox and reconciliation metadata

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "d7e8f9a0b1c2"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("reconciliation_status", sa.String(length=40), nullable=False, server_default="not_required"))
    op.add_column("payments", sa.Column("reconciliation_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("payments", sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("payments", sa.Column("reconciliation_error", sa.Text(), nullable=True))
    op.add_column("refunds", sa.Column("reconciliation_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("refunds", sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("refunds", sa.Column("reconciliation_error", sa.Text(), nullable=True))

    status_enum = postgresql.ENUM("RECEIVED", "PROCESSING", "PROCESSED", "FAILED", name="webhookprocessingstatus")
    status_enum.create(op.get_bind(), checkfirst=True)
    status_column_enum = postgresql.ENUM(
        "RECEIVED", "PROCESSING", "PROCESSED", "FAILED", name="webhookprocessingstatus", create_type=False
    )
    op.create_table(
        "payment_webhook_inbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False, server_default="razorpay"),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("processing_status", status_column_enum, nullable=False, server_default="RECEIVED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("provider_event_id", name="uq_payment_webhook_provider_event"),
    )


def downgrade() -> None:
    op.drop_table("payment_webhook_inbox")
    sa.Enum(name="webhookprocessingstatus").drop(op.get_bind(), checkfirst=True)
    for table, columns in {
        "refunds": ("reconciliation_error", "last_reconciled_at", "reconciliation_attempts"),
        "payments": ("reconciliation_error", "last_reconciled_at", "reconciliation_attempts", "reconciliation_status"),
    }.items():
        for column in columns:
            op.drop_column(table, column)
