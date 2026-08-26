"""
Notification templates and delivered notifications.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class NotificationChannel(StrEnum):
    SMS = "sms"
    EMAIL = "email"
    PUSH = "push"


class NotificationDeliveryStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class NotificationTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_templates"

    event_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("events.id"), default=None)
    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(255), default=None)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    notifications: Mapped[list["Notification"]] = relationship(back_populates="template")


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("notification_templates.id"), default=None)
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_metadata: Mapped[dict | None] = mapped_column(JSON, default=None)
    delivery_status: Mapped[NotificationDeliveryStatus] = mapped_column(
        Enum(NotificationDeliveryStatus), default=NotificationDeliveryStatus.QUEUED
    )
    provider_message_id: Mapped[str | None] = mapped_column(String(255), default=None)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    template: Mapped["NotificationTemplate | None"] = relationship(back_populates="notifications")
