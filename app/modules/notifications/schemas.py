"""Pydantic contracts for notifications."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.notifications.models import (
    DeviceTokenPlatform,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from app.modules.registrations.models import RegistrationStatus


class NotificationTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID | None
    code: str
    channel: NotificationChannel
    subject: str | None
    body_template: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class NotificationSendTargetIn(BaseModel):
    event_id: uuid.UUID
    participation_types: list[str] = Field(default_factory=list)
    registration_statuses: list[RegistrationStatus] = Field(default_factory=list)
    recipient_user_ids: list[uuid.UUID] = Field(default_factory=list)


class NotificationSendIn(BaseModel):
    title: str
    body: str
    channels: list[NotificationChannel] = Field(default_factory=lambda: [NotificationChannel.PUSH])
    target: NotificationSendTargetIn
    notification_type: str = "operational"


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    recipient_user_id: uuid.UUID
    template_id: uuid.UUID | None
    channel: NotificationChannel
    title: str
    body: str
    target_metadata: dict | None
    delivery_status: NotificationDeliveryStatus
    provider_message_id: str | None
    sent_at: datetime | None
    read_at: datetime | None
    notification_type: str
    dedupe_key: str | None
    attempt_count: int
    last_error: str | None
    delivered_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeviceTokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    platform: DeviceTokenPlatform = DeviceTokenPlatform.OTHER


class DeviceTokenOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform: DeviceTokenPlatform
    is_active: bool
    last_seen_at: datetime
    failure_count: int


class NotificationPreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_reminders: bool
    registration_updates: bool
    cancellation_refund_updates: bool
    event_changes: bool
    operational_notifications: bool
    marketing_notifications: bool


class NotificationPreferenceIn(BaseModel):
    event_reminders: bool | None = None
    registration_updates: bool | None = None
    cancellation_refund_updates: bool | None = None
    event_changes: bool | None = None
    operational_notifications: bool | None = None
    marketing_notifications: bool | None = None
