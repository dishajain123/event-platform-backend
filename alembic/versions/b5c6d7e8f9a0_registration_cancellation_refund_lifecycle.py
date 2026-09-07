"""add registration cancellation and refund lifecycle metadata"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    registration_status = postgresql.ENUM(
        "STARTED",
        "SUBMITTED",
        "PENDING_VERIFICATION",
        "PENDING_PAYMENT",
        "REFUND_PENDING",
        "REFUND_FAILED",
        "APPROVED",
        "CONFIRMED",
        "CHECKED_IN",
        "COMPLETED",
        "REJECTED",
        "CANCELLED",
        name="registrationstatus",
    )
    registration_status.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("registrations") as batch:
        batch.add_column(sa.Column("cancellation_deadline_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("cancelled_by", sa.UUID(), nullable=True))
        batch.add_column(sa.Column("cancellation_reason", sa.Text(), nullable=True))
    with op.batch_alter_table("refunds") as batch:
        batch.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_registrations_cancelled_by_users",
        "registrations",
        "users",
        ["cancelled_by"],
        ["id"],
    )

    # PostgreSQL enum values must be added explicitly when the enum already
    # exists. The create call above is harmless on an existing database.
    op.execute("ALTER TYPE registrationstatus ADD VALUE IF NOT EXISTS 'REFUND_PENDING'")
    op.execute("ALTER TYPE registrationstatus ADD VALUE IF NOT EXISTS 'REFUND_FAILED'")


def downgrade() -> None:
    op.drop_constraint("fk_registrations_cancelled_by_users", "registrations", type_="foreignkey")
    with op.batch_alter_table("refunds") as batch:
        batch.drop_column("failure_reason")
    with op.batch_alter_table("registrations") as batch:
        batch.drop_column("cancellation_reason")
        batch.drop_column("cancelled_by")
        batch.drop_column("cancelled_at")
        batch.drop_column("cancellation_requested_at")
        batch.drop_column("cancellation_deadline_at")
