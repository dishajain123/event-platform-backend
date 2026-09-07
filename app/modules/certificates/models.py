import uuid
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class CertificateType(StrEnum):
    PARTICIPATION = "participation"
    COMPLETION = "completion"
    WINNER = "winner"
    RUNNER_UP = "runner_up"
    ATTENDANCE = "attendance"
    ACHIEVEMENT = "achievement"
    CUSTOM = "custom"


class CertificateStatus(StrEnum):
    ISSUED = "issued"
    REVOKED = "revoked"


class CertificateTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "certificate_templates"
    __table_args__ = (Index("ix_certificate_templates_event_active", "event_id", "is_active", "created_at"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    certificate_type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    issuer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    mutually_exclusive: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Certificate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("certificate_number", name="uq_certificate_number"),
        UniqueConstraint("verification_token", name="uq_certificate_verification_token"),
        Index("ix_certificates_event_participant", "event_id", "user_id", "status", "created_at"),
        Index("ix_certificates_active_recipient", "event_id", "template_id", "registration_id", "participant_id", unique=True, postgresql_where=text("status = 'issued'")),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    template_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("certificate_templates.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("registrations.id"), nullable=False)
    participant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("registration_participants.id"), default=None)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    certificate_number: Mapped[str] = mapped_column(String(80), nullable=False)
    verification_token: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CertificateStatus.ISSUED.value, nullable=False)
    artifact_url: Mapped[str | None] = mapped_column(String(500), default=None)
    issued_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)
    revocation_reason: Mapped[str | None] = mapped_column(Text, default=None)


class BadgeDefinition(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "badge_definitions"
    __table_args__ = (UniqueConstraint("event_id", "name", name="uq_badge_event_name"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    icon_reference: Mapped[str | None] = mapped_column(String(500), default=None)
    criteria: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BadgeAward(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "badge_awards"
    __table_args__ = (
        UniqueConstraint("event_id", "badge_id", "user_id", "participant_id", name="uq_badge_award_recipient"),
        Index("ix_badge_awards_user_event", "user_id", "event_id", "created_at"),
        Index("ix_badge_awards_active_recipient", "event_id", "badge_id", "registration_id", "participant_id", unique=True, postgresql_where=text("status = 'awarded'")),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    badge_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("badge_definitions.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("registrations.id"), nullable=False)
    participant_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("registration_participants.id"), default=None)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="awarded", nullable=False)
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)
    revocation_reason: Mapped[str | None] = mapped_column(Text, default=None)
