import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.event_categories.schemas import MainCategorySummary, SubCategorySummary
from app.modules.config_engine.schemas import EventConfigurationOut
from app.modules.identity.schemas import UserOut
from app.modules.events.models import EventStatus


class EventCreateIn(BaseModel):
    name: str
    description: str | None = None
    category: str | None = None
    main_category_id: uuid.UUID | None = None
    sub_category_id: uuid.UUID | None = None
    start_date: datetime
    end_date: datetime
    organizer_user_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None


class EventUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    main_category_id: uuid.UUID | None = None
    sub_category_id: uuid.UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    organizer_user_id: uuid.UUID | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID | None
    organizer_user_id: uuid.UUID | None
    name: str
    description: str | None
    category: str | None
    main_category_id: uuid.UUID | None
    sub_category_id: uuid.UUID | None
    organizer_user_id: uuid.UUID | None
    main_category: MainCategorySummary | None = None
    sub_category: SubCategorySummary | None = None
    organizer: UserOut | None = None
    configuration: EventConfigurationOut | None = None
    start_date: datetime
    end_date: datetime
    status: EventStatus


class EventManagerOverviewOut(BaseModel):
    user_id: uuid.UUID | None
    name: str | None
    mobile_number: str | None
    total_events: int
    upcoming_events: int
    active_events: int
    completed_events: int


class EventDashboardItemOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    organizer_user_id: uuid.UUID | None
    organizer_name: str | None
    organizer_mobile_number: str | None
    main_category: str | None
    sub_category: str | None
    status: EventStatus
    start_date: datetime
    end_date: datetime
    total_registrations: int
    active_registrations: int
    capacity: int | None
    registration_status: str
    is_full: bool


class EventOperationsOverviewOut(BaseModel):
    total_events: int
    upcoming_events: int
    active_events: int
    completed_events: int
    draft_events: int
    unpublished_events: int
    registration_open_events: int
    registration_closed_events: int
    events_at_full_capacity: int
    total_registrations: int
    active_registrations: int
    event_manager_overview: list[EventManagerOverviewOut]
    events: list[EventDashboardItemOut]


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
