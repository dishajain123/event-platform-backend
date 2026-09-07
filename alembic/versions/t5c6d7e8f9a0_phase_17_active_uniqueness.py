"""phase 17 active certificate and badge uniqueness"""
from alembic import op
import sqlalchemy as sa

revision = "t5c6d7e8f9a0"
down_revision = "s4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_certificates_active_recipient", "certificates", ["event_id", "template_id", "registration_id", "participant_id"], unique=True, postgresql_where=sa.text("status = 'issued'"))
    op.create_index("ix_badge_awards_active_recipient", "badge_awards", ["event_id", "badge_id", "registration_id", "participant_id"], unique=True, postgresql_where=sa.text("status = 'awarded'"))


def downgrade():
    op.drop_index("ix_badge_awards_active_recipient", table_name="badge_awards")
    op.drop_index("ix_certificates_active_recipient", table_name="certificates")
