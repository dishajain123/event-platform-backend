"""phase 16 transfer lifecycle and multi-day ticket validity"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "q2f3a4b5c6d7"
down_revision: Union[str, None] = "p1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    transfer_status = postgresql.ENUM("PENDING", "ACCEPTED", "REJECTED", "CANCELLED", name="tickettransferstatus", create_type=False)
    transfer_status.create(op.get_bind(), checkfirst=True)
    op.add_column("access_policies", sa.Column("valid_dates", sa.JSON(), nullable=True))
    op.add_column("tickets", sa.Column("valid_dates", sa.JSON(), nullable=True))
    op.create_table(
        "ticket_transfers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticket_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("from_user_id", sa.Uuid(), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), nullable=False),
        sa.Column("status", transfer_status, nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["ticket_id"], ["tickets.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ticket_transfers_recipient_status", "ticket_transfers", ["to_user_id", "status", "created_at"])
    op.create_index("ix_ticket_transfers_ticket_pending", "ticket_transfers", ["ticket_id"], unique=True, postgresql_where=sa.text("status = 'PENDING'"))


def downgrade() -> None:
    op.drop_index("ix_ticket_transfers_ticket_pending", table_name="ticket_transfers")
    op.drop_index("ix_ticket_transfers_recipient_status", table_name="ticket_transfers")
    op.drop_table("ticket_transfers")
    op.drop_column("tickets", "valid_dates")
    op.drop_column("access_policies", "valid_dates")
    op.execute("DROP TYPE IF EXISTS tickettransferstatus")
