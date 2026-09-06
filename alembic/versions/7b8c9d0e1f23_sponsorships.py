"""sponsorship inquiries and confirmed event sponsors"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "7b8c9d0e1f23"
down_revision: Union[str, None] = "6a7b8c9d0e12"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires enum types to exist before they are referenced by
    # CREATE TABLE or ALTER TABLE statements.
    postgresql.ENUM(
        "NEW", "REVIEWING", "APPROVED", "CONFIRMED", "REJECTED", "CLOSED",
        name="sponsorshipinquirystatus",
    ).create(op.get_bind(), checkfirst=True)
    postgresql.ENUM("CONFIRMED", "ACTIVE", "INACTIVE", name="sponsorstatus").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "sponsorship_categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "sponsorship_packages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("benefits", sa.JSON(), nullable=False),
        sa.Column("minimum_offer", sa.Numeric(12, 2), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["sponsorship_categories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sponsorship_inquiries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("contact_person", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("business_details", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("package_id", sa.Uuid(), nullable=True),
        sa.Column("offer_details", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "status",
            postgresql.ENUM(
                "NEW", "REVIEWING", "APPROVED", "CONFIRMED", "REJECTED", "CLOSED",
                name="sponsorshipinquirystatus",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["sponsorship_categories.id"]),
        sa.ForeignKeyConstraint(["package_id"], ["sponsorship_packages.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sponsorship_inquiries_user_id", "sponsorship_inquiries", ["user_id"])
    op.create_index("ix_sponsorship_inquiries_status", "sponsorship_inquiries", ["status"])
    op.create_table(
        "sponsorship_inquiry_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inquiry_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["inquiry_id"], ["sponsorship_inquiries.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("inquiry_id", "event_id", name="uq_sponsorship_inquiry_event"),
    )
    op.create_index("ix_sponsorship_inquiry_events_inquiry_id", "sponsorship_inquiry_events", ["inquiry_id"])
    op.create_index("ix_sponsorship_inquiry_events_event_id", "sponsorship_inquiry_events", ["event_id"])

    with op.batch_alter_table("sponsors") as batch:
        batch.add_column(
            sa.Column(
                "status",
                postgresql.ENUM("CONFIRMED", "ACTIVE", "INACTIVE", name="sponsorstatus", create_type=False),
                nullable=False,
                server_default="CONFIRMED",
            )
        )
        batch.add_column(sa.Column("category", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch.add_column(sa.Column("offer_details", sa.Text(), nullable=True))
        batch.add_column(sa.Column("benefits", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("website_url", sa.String(length=500), nullable=True))
        batch.add_column(sa.Column("contact_email", sa.String(length=320), nullable=True))
        batch.add_column(sa.Column("inquiry_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key("fk_sponsors_inquiry_id", "sponsorship_inquiries", ["inquiry_id"], ["id"])
        batch.create_unique_constraint("uq_sponsor_event_inquiry", ["event_id", "inquiry_id"])


def downgrade() -> None:
    with op.batch_alter_table("sponsors") as batch:
        batch.drop_constraint("fk_sponsors_inquiry_id", type_="foreignkey")
        batch.drop_constraint("uq_sponsor_event_inquiry", type_="unique")
        for column in ("inquiry_id", "contact_email", "website_url", "benefits", "offer_details", "description", "category", "status"):
            batch.drop_column(column)
    op.drop_table("sponsorship_inquiry_events")
    op.drop_table("sponsorship_inquiries")
    op.drop_table("sponsorship_packages")
    op.drop_table("sponsorship_categories")
    sa.Enum(name="sponsorshipinquirystatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="sponsorstatus").drop(op.get_bind(), checkfirst=True)
