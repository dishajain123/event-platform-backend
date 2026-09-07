"""phase 24 idempotent offline check-in operations"""
from alembic import op
import sqlalchemy as sa

revision = "z1c2d3e4f5a6"
down_revision = "y0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "uq_checkins_offline_batch_id",
        "check_ins",
        ["offline_batch_id"],
        unique=True,
        postgresql_where=sa.text("offline_batch_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_checkins_offline_batch_id", table_name="check_ins")
