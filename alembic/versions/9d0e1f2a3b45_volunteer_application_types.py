"""add volunteer and event-manager application types"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "9d0e1f2a3b45"
down_revision: Union[str, None] = "8c9d0e1f2a34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    application_type = postgresql.ENUM("VOLUNTEER", "EVENT_MANAGER", name="volunteerapplicationtype")
    application_type.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("volunteer_applications") as batch:
        batch.drop_constraint("uq_volunteer_application_event_user", type_="unique")
        batch.add_column(sa.Column(
            "application_type",
            postgresql.ENUM("VOLUNTEER", "EVENT_MANAGER", name="volunteerapplicationtype", create_type=False),
            nullable=False,
            server_default="VOLUNTEER",
        ))
        batch.create_unique_constraint(
            "uq_volunteer_application_event_user_type",
            ["event_id", "user_id", "application_type"],
        )
    op.create_index("ix_volunteer_applications_application_type", "volunteer_applications", ["application_type"])


def downgrade() -> None:
    op.drop_index("ix_volunteer_applications_application_type", table_name="volunteer_applications")
    with op.batch_alter_table("volunteer_applications") as batch:
        batch.drop_constraint("uq_volunteer_application_event_user_type", type_="unique")
        batch.drop_column("application_type")
        batch.create_unique_constraint("uq_volunteer_application_event_user", ["event_id", "user_id"])
    postgresql.ENUM(name="volunteerapplicationtype").drop(op.get_bind(), checkfirst=True)
