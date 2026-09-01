"""event categories hierarchy

Revision ID: 3f8b3e2a7d4e
Revises: f96ec58c88cd
Create Date: 2026-09-02 00:00:00.000000

Adds a backend-owned category tree for events:
- main_categories
- sub_categories
- events.main_category_id / events.sub_category_id

The legacy events.category string column is intentionally left in place
for backward compatibility while the console and future mobile client
move to the foreign-key-based hierarchy.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3f8b3e2a7d4e"
down_revision: Union[str, None] = "f96ec58c88cd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "main_categories",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_main_categories_name"),
    )
    op.create_table(
        "sub_categories",
        sa.Column("main_category_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["main_category_id"], ["main_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("main_category_id", "name", name="uq_sub_categories_main_category_name"),
    )
    op.add_column(
        "events",
        sa.Column("main_category_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "events",
        sa.Column("sub_category_id", sa.Uuid(), nullable=True),
    )
    op.create_index(op.f("ix_events_main_category_id"), "events", ["main_category_id"], unique=False)
    op.create_index(op.f("ix_events_sub_category_id"), "events", ["sub_category_id"], unique=False)
    op.create_foreign_key(
        "fk_events_main_category_id",
        "events",
        "main_categories",
        ["main_category_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_events_sub_category_id",
        "events",
        "sub_categories",
        ["sub_category_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_events_sub_category_id", "events", type_="foreignkey")
    op.drop_constraint("fk_events_main_category_id", "events", type_="foreignkey")
    op.drop_index(op.f("ix_events_sub_category_id"), table_name="events")
    op.drop_index(op.f("ix_events_main_category_id"), table_name="events")
    op.drop_column("events", "sub_category_id")
    op.drop_column("events", "main_category_id")
    op.drop_table("sub_categories")
    op.drop_table("main_categories")

