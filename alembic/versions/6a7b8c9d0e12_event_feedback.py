"""event feedback

Revision ID: 6a7b8c9d0e12
Revises: c9e6a1f48b2d
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a7b8c9d0e12"
down_revision: Union[str, None] = "c9e6a1f48b2d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", "category", name="uq_event_feedback_user_category"),
    )
    op.create_index("ix_event_feedback_event_id", "event_feedback", ["event_id"])
    op.create_index("ix_event_feedback_user_id", "event_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_event_feedback_user_id", table_name="event_feedback")
    op.drop_index("ix_event_feedback_event_id", table_name="event_feedback")
    op.drop_table("event_feedback")
