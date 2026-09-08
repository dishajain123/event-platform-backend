"""
Notification templates and delivered notifications.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, JSON, String, Text, UniqueConstraint
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


class DeviceTokenPlatform(StrEnum):
    ANDROID = "android"
    IOS = "ios"
    WEB = "web"
    OTHER = "other"


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
    __table_args__ = (
        Index("ix_notifications_event_created", "event_id", "created_at"),
        Index("ix_notifications_recipient_created", "recipient_user_id", "created_at"),
    )

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
    notification_type: Mapped[str] = mapped_column(String(80), default="operational", nullable=False)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), unique=True, default=None)
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    template: Mapped["NotificationTemplate | None"] = relationship(back_populates="notifications")


class DeviceToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_device_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_notification_device_token"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String(512), nullable=False)
    platform: Mapped[DeviceTokenPlatform] = mapped_column(
        Enum(DeviceTokenPlatform), default=DeviceTokenPlatform.OTHER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)


class NotificationPreference(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", name="uq_notification_preference_user"),)

    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    event_reminders: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    registration_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cancellation_refund_updates: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    event_changes: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operational_notifications: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    marketing_notifications: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
