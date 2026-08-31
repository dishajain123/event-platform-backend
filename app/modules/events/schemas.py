import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.events.models import EventStatus


class EventCreateIn(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    start_date: datetime
    end_date: datetime
    organization_id: uuid.UUID | None = None


class EventUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    name: str
    description: str | None
    category: str | None
    start_date: datetime
    end_date: datetime
    status: EventStatus


class EventStatusChangeIn(BaseModel):
    new_status: EventStatus


class VenueIn(BaseModel):
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class VenueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None


class ScheduleItemIn(BaseModel):
    venue_id: uuid.UUID | None = None
    title: str
    start_time: datetime
    end_time: datetime | None = None


class ScheduleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID | None
    title: str
    start_time: datetime
    end_time: datetime | None


class SponsorIn(BaseModel):
    name: str
    tier: str | None = None
    logo_url: str | None = None


class SponsorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    tier: str | None
    logo_url: str | None
