"""
Teams, members, and invitations for team-based participation.

Team runs its own lightweight lifecycle (roster-building: draft →
inviting → submitted → approved/rejected), but the actual
participation record that Payments, Tickets, and Check-in key off is
a Registration (see registration_id below) — created once the team is
submitted, exactly like every other participation type. Team is not a
second, parallel source of truth for "is this team allowed to
participate"; Registration remains that single source of truth.
"""
import uuid
from datetime import date, datetime
from enum import StrEnum

from sqlalchemy import Date, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class TeamStatus(StrEnum):
    DRAFT = "draft"
    INVITING = "inviting"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Team(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "teams"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    captain_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TeamStatus] = mapped_column(Enum(TeamStatus), default=TeamStatus.DRAFT)
    captain_date_of_birth: Mapped[date | None] = mapped_column(Date(), default=None)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, default=None)

    # The Registration created on submit — this is what Payments/Tickets/
    # Check-in actually reference. Nullable only because a DRAFT/INVITING
    # team hasn't been submitted yet.
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), default=None
    )

    members: Mapped[list["TeamMember"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )
    invitations: Mapped[list["TeamInvitation"]] = relationship(
        back_populates="team", cascade="all, delete-orphan"
    )


class TeamMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "team_members"
    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_member_user"),)

    team_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("teams.id"), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date(), default=None)
    is_captain: Mapped[bool] = mapped_column(default=False)

    team: Mapped["Team"] = relationship(back_populates="members")


class TeamInvitation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "team_invitations"
    __table_args__ = (UniqueConstraint("team_id", "invitee_mobile", name="uq_team_invitation"),)

    team_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("teams.id"), nullable=False)
    invitee_mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    token: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    status: Mapped[InvitationStatus] = mapped_column(
        Enum(InvitationStatus), default=InvitationStatus.PENDING
    )
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    team: Mapped["Team"] = relationship(back_populates="invitations")