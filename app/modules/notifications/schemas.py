"""Pydantic contracts for notifications."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.notifications.models import NotificationChannel, NotificationDeliveryStatus
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
    created_at: datetime
    updated_at: datetime
