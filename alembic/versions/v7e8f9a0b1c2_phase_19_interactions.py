"""phase 19 generic polls and event questions"""
from alembic import op
import sqlalchemy as sa

revision = "v7e8f9a0b1c2"
down_revision = "u6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "event_polls",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("created_by", sa.UUID(), nullable=False), sa.Column("title", sa.String(255), nullable=False), sa.Column("description", sa.Text()), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("choice_mode", sa.Enum("SINGLE", "MULTIPLE", name="pollchoicemode"), nullable=False), sa.Column("anonymous", sa.Boolean(), nullable=False), sa.Column("max_selections", sa.Integer()), sa.Column("allow_vote_change", sa.Boolean(), nullable=False), sa.Column("result_visibility", sa.Enum("HIDDEN", "AFTER_VOTING", "ALWAYS", "AFTER_CLOSE", name="pollresultvisibility"), nullable=False), sa.Column("status", sa.Enum("DRAFT", "SCHEDULED", "LIVE", "CLOSED", "ARCHIVED", name="pollstatus"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["created_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_polls_event_status_start", "event_polls", ["event_id", "status", "starts_at"])
    op.create_table(
        "poll_options",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("poll_id", sa.UUID(), nullable=False), sa.Column("label", sa.String(255), nullable=False), sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["event_polls.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("poll_id", "sort_order", name="uq_poll_option_order"),
    )
    op.create_index("ix_poll_options_poll", "poll_options", ["poll_id"])
    op.create_table(
        "poll_responses",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("poll_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["event_polls.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("poll_id", "user_id", name="uq_poll_response_user"),
    )
    op.create_table(
        "poll_votes",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("response_id", sa.UUID(), nullable=False), sa.Column("option_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["response_id"], ["poll_responses.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["option_id"], ["poll_options.id"], ondelete="CASCADE"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("response_id", "option_id", name="uq_poll_vote_option"),
    )
    op.create_table(
        "event_questions",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=False), sa.Column("question", sa.Text(), nullable=False), sa.Column("anonymous", sa.Boolean(), nullable=False), sa.Column("display_name", sa.String(255)), sa.Column("status", sa.Enum("SUBMITTED", "PENDING", "APPROVED", "ANSWERED", "REJECTED", "HIDDEN", "ARCHIVED", name="questionstatus"), nullable=False), sa.Column("answer_text", sa.Text()), sa.Column("answered_by", sa.UUID()), sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"]), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.ForeignKeyConstraint(["answered_by"], ["users.id"]), sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_questions_event_status_created", "event_questions", ["event_id", "status", "created_at"])
    op.create_table(
        "question_upvotes",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("question_id", sa.UUID(), nullable=False), sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["event_questions.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["user_id"], ["users.id"]), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("question_id", "user_id", name="uq_question_upvote_user"),
    )
    op.create_index("ix_question_upvotes_question", "question_upvotes", ["question_id"])


def downgrade():
    op.drop_index("ix_question_upvotes_question", table_name="question_upvotes"); op.drop_table("question_upvotes")
    op.drop_index("ix_event_questions_event_status_created", table_name="event_questions"); op.drop_table("event_questions")
    op.drop_table("poll_votes"); op.drop_table("poll_responses")
    op.drop_index("ix_poll_options_poll", table_name="poll_options"); op.drop_table("poll_options")
    op.drop_index("ix_event_polls_event_status_start", table_name="event_polls"); op.drop_table("event_polls")
    op.execute("DROP TYPE IF EXISTS questionstatus")
    op.execute("DROP TYPE IF EXISTS pollstatus")
    op.execute("DROP TYPE IF EXISTS pollresultvisibility")
    op.execute("DROP TYPE IF EXISTS pollchoicemode")
