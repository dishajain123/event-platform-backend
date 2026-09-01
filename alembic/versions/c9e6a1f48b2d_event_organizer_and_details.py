"""event organizer and details payload

Revision ID: c9e6a1f48b2d
Revises: 3f8b3e2a7d4e
Create Date: 2026-09-02 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e6a1f48b2d"
down_revision: Union[str, None] = "3f8b3e2a7d4e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column("organizer_user_id", sa.Uuid(), nullable=True),
    )
    op.create_index(op.f("ix_events_organizer_user_id"), "events", ["organizer_user_id"], unique=False)
    op.create_foreign_key(
        "fk_events_organizer_user_id",
        "events",
        "users",
        ["organizer_user_id"],
        ["id"],
    )

    op.add_column(
        "event_configurations",
        sa.Column(
            "details",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("event_configurations", "details")
    op.drop_constraint("fk_events_organizer_user_id", "events", type_="foreignkey")
    op.drop_index(op.f("ix_events_organizer_user_id"), table_name="events")
    op.drop_column("events", "organizer_user_id")
