"""Logical deletion of category trees and their events."""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("main_categories", "sub_categories", "events"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    for table, name, columns in (
        ("main_categories", "uq_main_categories_name", ["name"]),
        ("sub_categories", "uq_sub_categories_main_category_name", ["main_category_id", "name"]),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_index(name, table, columns, unique=True, postgresql_where=sa.text("deleted_at IS NULL"))


def downgrade():
    # Fails safely if names have been reused since deletion; reconcile those
    # records before downgrading rather than discarding retained history.
    for table, name, columns in (
        ("main_categories", "uq_main_categories_name", ["name"]),
        ("sub_categories", "uq_sub_categories_main_category_name", ["main_category_id", "name"]),
    ):
        op.drop_index(name, table_name=table)
        op.create_unique_constraint(name, table, columns)
    for table in ("events", "sub_categories", "main_categories"):
        op.drop_column(table, "deleted_at")
