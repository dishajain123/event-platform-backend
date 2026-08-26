"""
Teams, members, and invitations for team-based participation.
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
