"""tickets.payment_id nullable for free events

Revision ID: f96ec58c88cd
Revises: b94ae379b3c6
Create Date: 2026-08-27 20:00:00.000000

Fixes a real gap found while verifying the Console's Day-of Operations
page live: tickets.payment_id was NOT NULL, but ticket issuance was
only ever wired to the payment webhook handler — meaning a free
(no-fee) event's registrations, which never create a Payment row at
all, could never receive a ticket. Check-in via QR scan was therefore
completely impossible for any free event. This migration makes the
column nullable so a ticket can be issued directly for a free,
approved registration; app/modules/tickets/service.py's
issue_ticket_for_registration() is the new code path that uses it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f96ec58c88cd"
down_revision: Union[str, None] = "b94ae379b3c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("tickets", "payment_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    op.alter_column("tickets", "payment_id", existing_type=sa.Uuid(), nullable=False)