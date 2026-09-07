import uuid
from enum import StrEnum
from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class NetworkingVisibility(StrEnum):
    VISIBLE = "visible"
    HIDDEN = "hidden"


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class ConnectionIntent(StrEnum):
    CONNECT = "connect"
    DISCUSS = "discuss"
    COLLABORATE = "collaborate"


class NetworkingReportStatus(StrEnum):
    OPEN = "open"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class EventNetworkingConfig(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_networking_configs"
    __table_args__ = (UniqueConstraint("event_id", name="uq_event_networking_config_event"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    matchmaking_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allowed_participant_types: Mapped[list | None] = mapped_column(JSON, default=None)


class NetworkingProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "networking_profiles"
    __table_args__ = (UniqueConstraint("event_id", "user_id", name="uq_networking_profile_event_user"), Index("ix_networking_profiles_event_visibility", "event_id", "visibility"))
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), default=None)
    organization: Mapped[str | None] = mapped_column(String(255), default=None)
    designation: Mapped[str | None] = mapped_column(String(255), default=None)
    interests: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    bio: Mapped[str | None] = mapped_column(Text, default=None)
    visibility: Mapped[NetworkingVisibility] = mapped_column(Enum(NetworkingVisibility), default=NetworkingVisibility.HIDDEN, nullable=False)
    share_contact: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class NetworkingDismissal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A participant's durable dismissal of another discoverable participant."""

    __tablename__ = "networking_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "requester_id", "participant_id",
            name="uq_networking_dismissal_event_requester_participant",
        ),
        Index("ix_networking_dismissals_event_requester", "event_id", "requester_id", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    requester_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class NetworkingConnection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "networking_connections"
    __table_args__ = (UniqueConstraint("event_id", "participant_low_id", "participant_high_id", name="uq_networking_connection_pair"), Index("ix_networking_connections_event_status", "event_id", "status", "created_at"))
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    participant_low_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    participant_high_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    intent: Mapped[ConnectionIntent] = mapped_column(Enum(ConnectionIntent), default=ConnectionIntent.CONNECT, nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(Enum(ConnectionStatus), default=ConnectionStatus.PENDING, nullable=False)
    responded_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)


class NetworkingReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "networking_reports"
    __table_args__ = (Index("ix_networking_reports_event_status_created", "event_id", "status", "created_at"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    reporter_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    reported_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[NetworkingReportStatus] = mapped_column(Enum(NetworkingReportStatus), default=NetworkingReportStatus.OPEN, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    resolution_notes: Mapped[str | None] = mapped_column(Text, default=None)
