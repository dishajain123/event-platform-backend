"""Designate manager accounts without granting global event permissions."""
from alembic import op
import sqlalchemy as sa

revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("is_event_manager", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""UPDATE users SET is_event_manager = true WHERE id IN (
        SELECT ra.user_id FROM role_assignments ra JOIN roles r ON r.id = ra.role_id
        WHERE r.name = 'EVENT_MANAGER' AND ra.status = 'ACTIVE' AND ra.event_id IS NOT NULL
    )""")


def downgrade():
    op.drop_column("users", "is_event_manager")
