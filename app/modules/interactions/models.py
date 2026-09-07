import uuid
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class PollStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    LIVE = "live"
    CLOSED = "closed"
    ARCHIVED = "archived"


class PollChoiceMode(StrEnum):
    SINGLE = "single"
    MULTIPLE = "multiple"


class PollResultVisibility(StrEnum):
    HIDDEN = "hidden"
    AFTER_VOTING = "after_voting"
    ALWAYS = "always"
    AFTER_CLOSE = "after_close"


class QuestionStatus(StrEnum):
    SUBMITTED = "submitted"
    PENDING = "pending"
    APPROVED = "approved"
    ANSWERED = "answered"
    REJECTED = "rejected"
    HIDDEN = "hidden"
    ARCHIVED = "archived"


class EventPoll(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_polls"
    __table_args__ = (Index("ix_event_polls_event_status_start", "event_id", "status", "starts_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    starts_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    choice_mode: Mapped[PollChoiceMode] = mapped_column(Enum(PollChoiceMode), nullable=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_selections: Mapped[int | None] = mapped_column(Integer, default=None)
    allow_vote_change: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    result_visibility: Mapped[PollResultVisibility] = mapped_column(Enum(PollResultVisibility), nullable=False)
    status: Mapped[PollStatus] = mapped_column(Enum(PollStatus), default=PollStatus.DRAFT, nullable=False)
    options: Mapped[list["PollOption"]] = relationship("PollOption", cascade="all, delete-orphan", order_by="PollOption.sort_order")


class PollOption(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "poll_options"
    __table_args__ = (UniqueConstraint("poll_id", "sort_order", name="uq_poll_option_order"), Index("ix_poll_options_poll", "poll_id"))

    poll_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("event_polls.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)


class PollResponse(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "poll_responses"
    __table_args__ = (UniqueConstraint("poll_id", "user_id", name="uq_poll_response_user"),)

    poll_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("event_polls.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)


class PollVote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "poll_votes"
    __table_args__ = (UniqueConstraint("response_id", "option_id", name="uq_poll_vote_option"),)

    response_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("poll_responses.id", ondelete="CASCADE"), nullable=False)
    option_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("poll_options.id", ondelete="CASCADE"), nullable=False)


class EventQuestion(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_questions"
    __table_args__ = (Index("ix_event_questions_event_status_created", "event_id", "status", "created_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    anonymous: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    status: Mapped[QuestionStatus] = mapped_column(Enum(QuestionStatus), default=QuestionStatus.PENDING, nullable=False)
    answer_text: Mapped[str | None] = mapped_column(Text, default=None)
    answered_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    answered_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)


class QuestionUpvote(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "question_upvotes"
    __table_args__ = (UniqueConstraint("question_id", "user_id", name="uq_question_upvote_user"), Index("ix_question_upvotes_question", "question_id"))

    question_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("event_questions.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
