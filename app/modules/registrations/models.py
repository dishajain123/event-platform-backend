"""
Registration lifecycle and participant details.

This module intentionally stays generic: the same data model handles
individual, viewer, and guardian-led registrations, while still leaving
room for future team-linked or funnel-linked workflows.
"""
import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class RegistrationStatus(StrEnum):
    STARTED = "started"
    SUBMITTED = "submitted"
    PENDING_VERIFICATION = "pending_verification"
    PENDING_PAYMENT = "pending_payment"
    APPROVED = "approved"
    CONFIRMED = "confirmed"
    CHECKED_IN = "checked_in"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


ACTIVE_REGISTRATION_STATUSES = {
    RegistrationStatus.STARTED,
    RegistrationStatus.SUBMITTED,
    RegistrationStatus.PENDING_VERIFICATION,
    RegistrationStatus.PENDING_PAYMENT,
    RegistrationStatus.APPROVED,
    RegistrationStatus.CONFIRMED,
    RegistrationStatus.CHECKED_IN,
    RegistrationStatus.COMPLETED,
}

TERMINAL_REGISTRATION_STATUSES = {
    RegistrationStatus.REJECTED,
    RegistrationStatus.CANCELLED,
}


class Registration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "registrations"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "user_id",
            "child_id",
            "participation_type",
            name="uq_registration_identity",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    child_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("child_profiles.id"), default=None
    )
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("teams.id"), default=None)
    participation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus), default=RegistrationStatus.STARTED, nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    participants: Mapped[list["RegistrationParticipant"]] = relationship(
        back_populates="registration", cascade="all, delete-orphan"
    )


class RegistrationParticipant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "registration_participants"

    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date(), default=None)
    is_captain: Mapped[bool] = mapped_column(default=False)

    registration: Mapped["Registration"] = relationship(back_populates="participants")
