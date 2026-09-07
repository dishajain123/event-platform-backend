"""Add event-scoped ticket access policies, zones, and structured scan state."""

from alembic import op
import sqlalchemy as sa

from app.core.base_model import UUIDType

revision = "j5e6f7a8b9c0"
down_revision = "i4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for value in ("ACTIVE", "USED", "EXPIRED", "REVOKED"):
        op.execute(f"ALTER TYPE ticketstatus ADD VALUE IF NOT EXISTS '{value}'")
    op.create_table("access_zones",
        sa.Column("id", UUIDType, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", UUIDType, nullable=False), sa.Column("code", sa.String(length=80), nullable=False), sa.Column("name", sa.String(length=120), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id", "code", name="uq_access_zone_event_code"))
    op.create_index("ix_access_zones_event_id", "access_zones", ["event_id"])
    op.create_table("access_policies",
        sa.Column("id", UUIDType, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", UUIDType, nullable=False), sa.Column("access_type", sa.String(length=40), nullable=False), sa.Column("allowed_zone_ids", sa.JSON(), nullable=False), sa.Column("allows_reentry", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("max_entries", sa.Integer(), nullable=False, server_default="1"), sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True), sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id", "access_type", name="uq_access_policy_event_type"))
    op.create_index("ix_access_policies_event_id", "access_policies", ["event_id"])
    op.add_column("tickets", sa.Column("access_type", sa.String(length=40), nullable=False, server_default="general"))
    op.add_column("tickets", sa.Column("access_policy_id", UUIDType, nullable=True))
    op.add_column("tickets", sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tickets", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_tickets_access_policy", "tickets", "access_policies", ["access_policy_id"], ["id"])
    op.create_index("ix_tickets_event_access_status", "tickets", ["event_id", "access_type", "status", "created_at"])
    op.add_column("check_ins", sa.Column("entry_number", sa.Integer(), nullable=False, server_default="1"))
    op.drop_constraint("uq_checkin_ticket", "check_ins", type_="unique")
    op.create_unique_constraint("uq_checkin_ticket_entry", "check_ins", ["ticket_id", "entry_number"])


def downgrade() -> None:
    op.drop_constraint("uq_checkin_ticket_entry", "check_ins", type_="unique")
    op.create_unique_constraint("uq_checkin_ticket", "check_ins", ["ticket_id"])
    op.drop_column("check_ins", "entry_number")
    op.drop_index("ix_tickets_event_access_status", table_name="tickets")
    op.drop_constraint("fk_tickets_access_policy", "tickets", type_="foreignkey")
    for column in ("valid_until", "valid_from", "entry_count", "access_policy_id", "access_type"):
        op.drop_column("tickets", column)
    op.drop_index("ix_access_policies_event_id", table_name="access_policies")
    op.drop_table("access_policies")
    op.drop_index("ix_access_zones_event_id", table_name="access_zones")
    op.drop_table("access_zones")
