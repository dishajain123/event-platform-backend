import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.event_categories.schemas import MainCategorySummary, SubCategorySummary
from app.modules.config_engine.schemas import EventConfigurationOut
from app.modules.identity.schemas import UserOut
from app.modules.events.models import EventStatus, ScheduleStatus, SponsorStatus


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


class EventDuplicateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    start_date: datetime
    end_date: datetime


class EventTemplateCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    source_event_id: uuid.UUID


class EventTemplateUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class EventTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    owner_user_id: uuid.UUID
    organization_id: uuid.UUID | None
    source_event_id: uuid.UUID | None
    name: str
    description: str | None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class EventTemplatePage(BaseModel):
    items: list[EventTemplateOut]
    total: int
    page: int
    page_size: int


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
    capacity: int | None = Field(default=None, ge=1)
    availability: list[dict] = Field(default_factory=list)
    is_shared: bool = False


class VenueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    address: str | None
    latitude: float | None
    longitude: float | None
    capacity: int | None
    availability: list[dict]
    is_shared: bool


class ScheduleItemIn(BaseModel):
    venue_id: uuid.UUID | None = None
    title: str
    start_time: datetime
    end_time: datetime | None = None
    resource_key: str | None = Field(default=None, max_length=120)
    expected_capacity: int | None = Field(default=None, ge=1)


class ScheduleItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID | None
    title: str
    start_time: datetime
    end_time: datetime | None
    resource_key: str | None
    expected_capacity: int | None
    status: ScheduleStatus


class ScheduleConflictOut(BaseModel):
    reason_code: str
    conflict_type: str
    message: str
    conflicting_event_id: uuid.UUID | None = None
    conflicting_event_name: str | None = None
    conflicting_schedule_id: uuid.UUID | None = None
    conflicting_venue_id: uuid.UUID | None = None
    existing_start_time: datetime | None = None
    existing_end_time: datetime | None = None
    requested_start_time: datetime
    requested_end_time: datetime


class ScheduleItemUpdateIn(BaseModel):
    venue_id: uuid.UUID | None = None
    title: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    resource_key: str | None = Field(default=None, max_length=120)
    expected_capacity: int | None = Field(default=None, ge=1)


class SponsorIn(BaseModel):
    name: str
    tier: str | None = None
    logo_url: str | None = None
    category: str | None = None
    description: str | None = None
    offer_details: str | None = None
    benefits: list[str] = Field(default_factory=list)
    website_url: str | None = None
    contact_email: str | None = None


class SponsorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    tier: str | None
    logo_url: str | None
    status: SponsorStatus
    category: str | None
    description: str | None
    offer_details: str | None
    benefits: list[str] | None
    website_url: str | None
    contact_email: str | None
    inquiry_id: uuid.UUID | None
