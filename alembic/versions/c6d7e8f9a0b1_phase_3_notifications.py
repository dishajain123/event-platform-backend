"""add production notification delivery state and user controls

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("notification_type", sa.String(length=80), nullable=False, server_default="operational"))
    op.add_column("notifications", sa.Column("dedupe_key", sa.String(length=255), nullable=True))
    op.add_column("notifications", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("notifications", sa.Column("last_error", sa.Text(), nullable=True))
    op.add_column("notifications", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("notifications", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True))
    op.create_unique_constraint("uq_notifications_dedupe_key", "notifications", ["dedupe_key"])

    platform_enum = postgresql.ENUM("ANDROID", "IOS", "WEB", "OTHER", name="devicetokenplatform")
    platform_enum.create(op.get_bind(), checkfirst=True)
    platform_column_enum = postgresql.ENUM(
        "ANDROID", "IOS", "WEB", "OTHER", name="devicetokenplatform", create_type=False
    )
    op.create_table(
        "notification_device_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", platform_column_enum, nullable=False, server_default="OTHER"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token", name="uq_notification_device_token"),
    )
    op.create_index("ix_notification_device_tokens_user_id", "notification_device_tokens", ["user_id"])

    op.create_table(
        "notification_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_reminders", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("registration_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("cancellation_refund_updates", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("event_changes", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("operational_notifications", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("marketing_notifications", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_notification_preference_user"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_index("ix_notification_device_tokens_user_id", table_name="notification_device_tokens")
    op.drop_table("notification_device_tokens")
    op.drop_constraint("uq_notifications_dedupe_key", "notifications", type_="unique")
    for column in ("delivered_at", "failed_at", "last_error", "attempt_count", "dedupe_key", "notification_type"):
        op.drop_column("notifications", column)
    sa.Enum(name="devicetokenplatform").drop(op.get_bind(), checkfirst=True)
