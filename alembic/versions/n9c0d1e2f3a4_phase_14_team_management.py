"""phase 14 team management and individual team tickets"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "n9c0d1e2f3a4"
down_revision: Union[str, None] = "m8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("teams", sa.Column("team_code", sa.String(length=32), nullable=True))
    op.add_column("teams", sa.Column("manager_user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_teams_manager_user", "teams", "users", ["manager_user_id"], ["id"])
    op.execute("UPDATE teams SET team_code = 'TEAM-' || substr(replace(id::text, '-', ''), 1, 12) WHERE team_code IS NULL")
    op.alter_column("teams", "team_code", nullable=False)
    op.create_unique_constraint("uq_teams_team_code", "teams", ["team_code"])

    member_role = postgresql.ENUM("CAPTAIN", "MANAGER", "MEMBER", name="teammemberrole", create_type=False)
    member_role.create(op.get_bind(), checkfirst=True)
    op.add_column("team_members", sa.Column("role", member_role, nullable=True))
    op.execute("UPDATE team_members SET role = (CASE WHEN is_captain THEN 'CAPTAIN' ELSE 'MEMBER' END)::teammemberrole")
    op.alter_column("team_members", "role", nullable=False)

    join_status = postgresql.ENUM("PENDING", "APPROVED", "REJECTED", name="joinrequeststatus", create_type=False)
    join_status.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "team_join_requests",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", join_status, nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_join_request_user"),
    )

    op.add_column("tickets", sa.Column("participant_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_tickets_participant", "tickets", "registration_participants", ["participant_id"], ["id"])
    op.drop_constraint("uq_ticket_registration", "tickets", type_="unique")
    op.create_unique_constraint("uq_ticket_participant", "tickets", ["participant_id"])


def downgrade() -> None:
    op.drop_constraint("uq_ticket_participant", "tickets", type_="unique")
    op.drop_constraint("fk_tickets_participant", "tickets", type_="foreignkey")
    op.drop_column("tickets", "participant_id")
    op.drop_table("team_join_requests")
    op.drop_column("team_members", "role")
    sa.Enum(name="teammemberrole").drop(op.get_bind(), checkfirst=True)
    op.drop_constraint("uq_teams_team_code", "teams", type_="unique")
    op.drop_constraint("fk_teams_manager_user", "teams", type_="foreignkey")
    op.drop_column("teams", "manager_user_id")
    op.drop_column("teams", "team_code")
    sa.Enum(name="joinrequeststatus").drop(op.get_bind(), checkfirst=True)
