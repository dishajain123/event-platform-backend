"""Optional event cover image (normalized 16:9 JPEG via object storage)."""
from alembic import op
import sqlalchemy as sa

revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("events", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column("events", sa.Column("image_storage_key", sa.String(length=255), nullable=True))


def downgrade():
    op.drop_column("events", "image_storage_key")
    op.drop_column("events", "image_url")
