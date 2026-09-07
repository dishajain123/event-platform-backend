"""phase 15 competition containers, fixtures, results, and standings source data"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "o0d1e2f3a4b5"
down_revision: Union[str, None] = "n9c0d1e2f3a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for value in ("GROUP", "KNOCKOUT", "QUARTER_FINAL", "SEMI_FINAL", "FINAL"):
        op.execute(f"ALTER TYPE stagetype ADD VALUE IF NOT EXISTS '{value}'")

    op.alter_column("competition_stages", "metadata_json", new_column_name="stage_metadata")
    op.add_column("competition_stages", sa.Column("competition_id", sa.Uuid(), nullable=True))
    stage_status = postgresql.ENUM("DRAFT", "OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="stagestatus", create_type=False)
    stage_status.create(op.get_bind(), checkfirst=True)
    op.add_column("competition_stages", sa.Column("status", stage_status, nullable=True))
    op.add_column("competition_stages", sa.Column("advancement_rules", sa.JSON(), nullable=True))
    op.execute("UPDATE competition_stages SET status = 'DRAFT' WHERE status IS NULL")
    op.alter_column("competition_stages", "status", nullable=False)
    op.add_column("entries", sa.Column("competition_id", sa.Uuid(), nullable=True))
    op.drop_constraint("uq_entry_registration", "entries", type_="unique")
    op.create_unique_constraint("uq_entry_competition_registration", "entries", ["competition_id", "registration_id"])

    competition_status = postgresql.ENUM("DRAFT", "OPEN", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="competitionstatus", create_type=False)
    competition_status.create(op.get_bind(), checkfirst=True)
    match_status = postgresql.ENUM("SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED", name="matchstatus", create_type=False)
    match_status.create(op.get_bind(), checkfirst=True)
    result_status = postgresql.ENUM("PENDING", "WIN", "DRAW", "FORFEIT", name="matchresultstatus", create_type=False)
    result_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "competitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("competition_type", sa.String(80), nullable=False),
        sa.Column("participation_mode", sa.String(20), nullable=False),
        sa.Column("max_participants", sa.Integer(), nullable=True),
        sa.Column("registration_deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", competition_status, nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_competitions_event_status_created", "competitions", ["event_id", "status", "created_at"])
    op.create_foreign_key("fk_competition_stages_competition", "competition_stages", "competitions", ["competition_id"], ["id"])
    op.create_foreign_key("fk_entries_competition", "entries", "competitions", ["competition_id"], ["id"])

    op.create_table(
        "competition_matches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("competition_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("stage_id", sa.Uuid(), nullable=False),
        sa.Column("round_number", sa.Integer(), nullable=False),
        sa.Column("match_number", sa.Integer(), nullable=False),
        sa.Column("entry_a_id", sa.Uuid(), nullable=True),
        sa.Column("entry_b_id", sa.Uuid(), nullable=True),
        sa.Column("winner_entry_id", sa.Uuid(), nullable=True),
        sa.Column("venue_id", sa.Uuid(), nullable=True),
        sa.Column("schedule_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scheduled_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", match_status, nullable=False),
        sa.Column("result_status", result_status, nullable=False),
        sa.Column("score_a", sa.Integer(), nullable=True),
        sa.Column("score_b", sa.Integer(), nullable=True),
        sa.Column("result_notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=True),
        sa.Column("result_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["competition_id"], ["competitions.id"]),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]),
        sa.ForeignKeyConstraint(["stage_id"], ["competition_stages.id"]),
        sa.ForeignKeyConstraint(["entry_a_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["entry_b_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["winner_entry_id"], ["entries.id"]),
        sa.ForeignKeyConstraint(["venue_id"], ["venues.id"]),
        sa.ForeignKeyConstraint(["schedule_id"], ["schedule_items.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("competition_id", "stage_id", "round_number", "match_number", name="uq_competition_match_slot"),
    )
    op.create_index("ix_competition_matches_event_status_start", "competition_matches", ["event_id", "status", "scheduled_start"])


def downgrade() -> None:
    op.drop_index("ix_competition_matches_event_status_start", table_name="competition_matches")
    op.drop_table("competition_matches")
    op.drop_index("ix_competitions_event_status_created", table_name="competitions")
    op.drop_table("competitions")
    op.drop_constraint("fk_entries_competition", "entries", type_="foreignkey")
    op.drop_constraint("uq_entry_competition_registration", "entries", type_="unique")
    op.create_unique_constraint("uq_entry_registration", "entries", ["registration_id"])
    op.drop_column("entries", "competition_id")
    op.drop_constraint("fk_competition_stages_competition", "competition_stages", type_="foreignkey")
    op.drop_column("competition_stages", "advancement_rules")
    op.drop_column("competition_stages", "status")
    op.drop_column("competition_stages", "competition_id")
    op.alter_column("competition_stages", "stage_metadata", new_column_name="metadata_json")
