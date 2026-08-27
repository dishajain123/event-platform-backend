"""phase 9 fixes: staff-rbac bridge and team-registration link

Revision ID: b94ae379b3c6
Revises: 3c7d1b2f4a99
Create Date: 2026-08-27 00:00:00.000000

Adds the columns needed to fix two audit findings:
1. staff_assignments.role_name + linked_role_assignment_id — bridges
   a Staff invitation to a real RBAC RoleAssignment once accepted,
   instead of the previous free-text role_label having no connection
   to the permission system at all.
2. teams.registration_id — links a submitted team to the underlying
   Registration record that Payments/Tickets/Check-in actually key off,
   so team participation can be paid for and ticketed like every other
   participation type.

role_name is added as nullable so existing rows (if any) aren't broken
by this migration; application code treats it as required for all new
staff assignments going forward.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b94ae379b3c6"
down_revision: Union[str, None] = "3c7d1b2f4a99"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Reuses the existing 'rolename' Postgres enum type created in Phase 1
    # for roles.name — create_type=False stops Alembic trying (and failing)
    # to CREATE TYPE a second time for the same enum.
    role_name_enum = sa.Enum(
        "SUPER_ADMIN", "OPERATIONS_ADMIN", "FINANCE_ADMIN", "FINANCE_OPERATOR",
        "FINANCE_AUDITOR", "EVENT_MANAGER", "EVENT_COORDINATOR", "STAFF_LEAD",
        "STAFF_MEMBER", name="rolename", create_type=False,
    )
    op.add_column("staff_assignments", sa.Column("role_name", role_name_enum, nullable=True))
    op.add_column(
        "staff_assignments",
        sa.Column("linked_role_assignment_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_staff_assignments_linked_role_assignment_id",
        "staff_assignments",
        "role_assignments",
        ["linked_role_assignment_id"],
        ["id"],
    )

    op.add_column("teams", sa.Column("registration_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_teams_registration_id",
        "teams",
        "registrations",
        ["registration_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_teams_registration_id", "teams", type_="foreignkey")
    op.drop_column("teams", "registration_id")

    op.drop_constraint(
        "fk_staff_assignments_linked_role_assignment_id", "staff_assignments", type_="foreignkey"
    )
    op.drop_column("staff_assignments", "linked_role_assignment_id")
    op.drop_column("staff_assignments", "role_name")