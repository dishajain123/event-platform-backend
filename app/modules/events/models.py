"""
Event, Venue, Schedule, Sponsor — the event itself and its physical/
promotional details. Deliberately holds ZERO rules about who can
register or how; that's entirely config_engine's job. This module only
answers "what event is this, when, where, and what state is it in."
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class EventStatus(StrEnum):
    DRAFT = "draft"
    CONFIGURED = "configured"
    PUBLISHED = "published"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    LIVE = "live"
    COMPLETED = "completed"
    ARCHIVED = "archived"


# The valid state graph. Every transition not listed here is rejected —
# this is what "validated state transitions" means in practice: one
# source of truth the service layer checks against, not scattered
# if/else checks wherever an event's status happens to get touched.
ALLOWED_TRANSITIONS: dict[EventStatus, set[EventStatus]] = {
    EventStatus.DRAFT: {EventStatus.CONFIGURED},
    EventStatus.CONFIGURED: {EventStatus.DRAFT, EventStatus.PUBLISHED},
    EventStatus.PUBLISHED: {EventStatus.REGISTRATION_OPEN, EventStatus.ARCHIVED},
    EventStatus.REGISTRATION_OPEN: {EventStatus.REGISTRATION_CLOSED},
    EventStatus.REGISTRATION_CLOSED: {EventStatus.LIVE, EventStatus.REGISTRATION_OPEN},
    EventStatus.LIVE: {EventStatus.COMPLETED},
    EventStatus.COMPLETED: {EventStatus.ARCHIVED},
    EventStatus.ARCHIVED: set(),  # terminal state
}


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("organizations.id"), default=None
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.DRAFT)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )

    venues: Mapped[list["Venue"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    schedule_items: Mapped[list["ScheduleItem"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    sponsors: Mapped[list["Sponsor"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class Venue(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "venues"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), default=None)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)

    event: Mapped["Event"] = relationship(back_populates="venues")


class ScheduleItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "schedule_items"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    event: Mapped["Event"] = relationship(back_populates="schedule_items")


class Sponsor(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsors"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(100), default=None)
    logo_url: Mapped[str | None] = mapped_column(String(500), default=None)

    event: Mapped["Event"] = relationship(back_populates="sponsors")