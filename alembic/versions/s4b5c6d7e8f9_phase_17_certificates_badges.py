"""phase 17 certificates and achievement badges"""
from alembic import op
import sqlalchemy as sa

revision = "s4b5c6d7e8f9"
down_revision = "r3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "certificate_templates",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("certificate_type", sa.String(40), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("issuer_name", sa.String(255), nullable=False), sa.Column("criteria", sa.JSON(), nullable=False), sa.Column("mutually_exclusive", sa.Boolean(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_certificate_templates_event_active", "certificate_templates", ["event_id", "is_active", "created_at"])
    op.create_table(
        "certificates",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("template_id", sa.UUID(), nullable=False), sa.Column("registration_id", sa.UUID(), nullable=False), sa.Column("participant_id", sa.UUID()), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("certificate_number", sa.String(80), nullable=False), sa.Column("verification_token", sa.String(128), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("artifact_url", sa.String(500)), sa.Column("issued_by", sa.UUID(), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revocation_reason", sa.Text()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["template_id"], ["certificate_templates.id"]), sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"]), sa.ForeignKeyConstraint(["participant_id"], ["registration_participants.id"]), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.ForeignKeyConstraint(["issued_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("certificate_number", name="uq_certificate_number"), sa.UniqueConstraint("verification_token", name="uq_certificate_verification_token"),
    )
    op.create_index("ix_certificates_event_participant", "certificates", ["event_id", "user_id", "status", "created_at"])
    op.create_index("ix_certificates_active_recipient", "certificates", ["event_id", "template_id", "registration_id", "participant_id"], unique=True, postgresql_where=sa.text("status = 'issued'"))
    op.create_table(
        "badge_definitions",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("description", sa.Text()), sa.Column("icon_reference", sa.String(500)), sa.Column("criteria", sa.JSON(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id", "name", name="uq_badge_event_name"),
    )
    op.create_table(
        "badge_awards",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("badge_id", sa.UUID(), nullable=False), sa.Column("registration_id", sa.UUID(), nullable=False), sa.Column("participant_id", sa.UUID()), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("status", sa.String(20), nullable=False), sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revocation_reason", sa.Text()),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["badge_id"], ["badge_definitions.id"]), sa.ForeignKeyConstraint(["registration_id"], ["registrations.id"]), sa.ForeignKeyConstraint(["participant_id"], ["registration_participants.id"]), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("event_id", "badge_id", "user_id", "participant_id", name="uq_badge_award_recipient"),
    )
    op.create_index("ix_badge_awards_user_event", "badge_awards", ["user_id", "event_id", "created_at"])
    op.create_index("ix_badge_awards_active_recipient", "badge_awards", ["event_id", "badge_id", "registration_id", "participant_id"], unique=True, postgresql_where=sa.text("status = 'awarded'"))


def downgrade():
    op.drop_index("ix_badge_awards_active_recipient", table_name="badge_awards"); op.drop_index("ix_badge_awards_user_event", table_name="badge_awards"); op.drop_table("badge_awards"); op.drop_table("badge_definitions"); op.drop_index("ix_certificates_active_recipient", table_name="certificates"); op.drop_index("ix_certificates_event_participant", table_name="certificates"); op.drop_table("certificates"); op.drop_index("ix_certificate_templates_event_active", table_name="certificate_templates"); op.drop_table("certificate_templates")
