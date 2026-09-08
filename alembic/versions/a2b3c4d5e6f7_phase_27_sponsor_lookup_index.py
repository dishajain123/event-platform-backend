"""phase 27 add the sponsorship inquiry lookup index"""

from alembic import op


revision = "a2b3c4d5e6f7"
down_revision = "z1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_sponsors_inquiry_id",
        "sponsors",
        ["inquiry_id"],
        if_not_exists=True,
    )


def downgrade():
    op.drop_index("ix_sponsors_inquiry_id", table_name="sponsors")
