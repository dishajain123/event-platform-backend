"""
Generic multi-stage funnel / competition engine.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class StageType(StrEnum):
    JURY_REVIEW = "jury_review"
    PUBLIC_VOTE = "public_vote"
    TOP_N_CUTOFF = "top_n_cutoff"
    MANUAL_REVIEW = "manual_review"


class EntryStatus(StrEnum):
    ACTIVE = "active"
    ADVANCED = "advanced"
    ELIMINATED = "eliminated"
    COMPLETED = "completed"


class CompetitionStage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "competition_stages"
    __table_args__ = (UniqueConstraint("event_id", "order_index", name="uq_stage_order"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    stage_type: Mapped[StageType] = mapped_column(Enum(StageType), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    threshold: Mapped[int | None] = mapped_column(Integer, default=None)
    stage_metadata: Mapped[dict | None] = mapped_column(JSON, default=None)

    entries: Mapped[list["Entry"]] = relationship(back_populates="stage")


class Entry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "entries"
    __table_args__ = (UniqueConstraint("registration_id", name="uq_entry_registration"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
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
