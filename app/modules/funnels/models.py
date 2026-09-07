"""
Generic multi-stage funnel / competition engine.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class StageType(StrEnum):
    JURY_REVIEW = "jury_review"
    PUBLIC_VOTE = "public_vote"
    TOP_N_CUTOFF = "top_n_cutoff"
    MANUAL_REVIEW = "manual_review"
    GROUP = "group"
    KNOCKOUT = "knockout"
    QUARTER_FINAL = "quarter_final"
    SEMI_FINAL = "semi_final"
    FINAL = "final"


class CompetitionStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class StageStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MatchStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class MatchResultStatus(StrEnum):
    PENDING = "pending"
    WIN = "win"
    DRAW = "draw"
    FORFEIT = "forfeit"


class EntryStatus(StrEnum):
    ACTIVE = "active"
    ADVANCED = "advanced"
    ELIMINATED = "eliminated"
    COMPLETED = "completed"


class Competition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competitions"
    __table_args__ = (Index("ix_competitions_event_status_created", "event_id", "status", "created_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    competition_type: Mapped[str] = mapped_column(String(80), nullable=False)
    participation_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    max_participants: Mapped[int | None] = mapped_column(Integer, default=None)
    registration_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[CompetitionStatus] = mapped_column(Enum(CompetitionStatus), default=CompetitionStatus.DRAFT, nullable=False)


class CompetitionMatch(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competition_matches"
    __table_args__ = (
        UniqueConstraint("competition_id", "stage_id", "round_number", "match_number", name="uq_competition_match_slot"),
        Index("ix_competition_matches_event_status_start", "event_id", "status", "scheduled_start"),
    )

    competition_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("competitions.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("competition_stages.id"), nullable=False)
    round_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    match_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    entry_a_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("entries.id"), default=None)
    entry_b_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("entries.id"), default=None)
    winner_entry_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("entries.id"), default=None)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("schedule_items.id"), default=None)
    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[MatchStatus] = mapped_column(Enum(MatchStatus), default=MatchStatus.SCHEDULED, nullable=False)
    result_status: Mapped[MatchResultStatus] = mapped_column(Enum(MatchResultStatus), default=MatchResultStatus.PENDING, nullable=False)
    score_a: Mapped[int | None] = mapped_column(Integer, default=None)
    score_b: Mapped[int | None] = mapped_column(Integer, default=None)
    result_notes: Mapped[str | None] = mapped_column(Text, default=None)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    result_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class CompetitionStage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competition_stages"
    __table_args__ = (UniqueConstraint("event_id", "order_index", name="uq_stage_order"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    competition_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("competitions.id"), default=None, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage_type: Mapped[StageType] = mapped_column(Enum(StageType), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int | None] = mapped_column(Integer, default=None)
    stage_metadata: Mapped[dict | None] = mapped_column(JSON, default=None)
    status: Mapped[StageStatus] = mapped_column(Enum(StageStatus), default=StageStatus.DRAFT, nullable=False)
    advancement_rules: Mapped[dict | None] = mapped_column(JSON, default=None)

    entries: Mapped[list["Entry"]] = relationship(back_populates="stage")


class Entry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("competition_id", "registration_id", name="uq_entry_competition_registration"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    competition_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("competitions.id"), default=None, index=True)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    current_stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("competition_stages.id"), default=None
    )
    status: Mapped[EntryStatus] = mapped_column(Enum(EntryStatus), default=EntryStatus.ACTIVE)
    score: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    vote_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    stage: Mapped["CompetitionStage"] = relationship(back_populates="entries")
    decisions: Mapped[list["StageDecision"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan"
    )


class StageDecision(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "stage_decisions"

    entry_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("entries.id"), nullable=False)
    stage_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("competition_stages.id"), nullable=False
    )
    decided_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(50), nullable=False)
    score: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    entry: Mapped["Entry"] = relationship(back_populates="decisions")
