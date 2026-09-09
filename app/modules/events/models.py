"""
Event, Venue, Schedule, Sponsor — the event itself and its physical/
promotional details. Deliberately holds ZERO rules about who can
register or how; that's entirely config_engine's job. This module only
answers "what event is this, when, where, and what state is it in."
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType, SoftDeleteMixin


class EventStatus(StrEnum):
    DRAFT = "draft"
    CONFIGURED = "configured"
    PUBLISHED = "published"
    REGISTRATION_OPEN = "registration_open"
    REGISTRATION_CLOSED = "registration_closed"
    LIVE = "live"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class SponsorStatus(StrEnum):
    CONFIRMED = "confirmed"
    ACTIVE = "active"
    INACTIVE = "inactive"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ScheduleStatus(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


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


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "events"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("organizations.id"), default=None
    )
    organizer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    main_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("main_categories.id"), default=None, index=True
    )
    sub_category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("sub_categories.id"), default=None, index=True
    )
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[EventStatus] = mapped_column(Enum(EventStatus), default=EventStatus.DRAFT)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )

    main_category = relationship("MainCategory")
    sub_category = relationship("SubCategory", back_populates="events")
    organizer = relationship("User", foreign_keys=[organizer_user_id])
    configuration = relationship(
        "EventConfiguration", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )

    venues: Mapped[list["Venue"]] = relationship(back_populates="event", cascade="all, delete-orphan")
    schedule_items: Mapped[list["ScheduleItem"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    sponsors: Mapped[list["Sponsor"]] = relationship(back_populates="event", cascade="all, delete-orphan")


class EventTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Immutable-by-snapshot reusable event configuration owned by an organizer."""

    __tablename__ = "event_templates"
    __table_args__ = (Index("ix_event_templates_owner_archived", "owner_user_id", "is_archived", "created_at"),)

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("organizations.id"), default=None)
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("events.id"), default=None)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Venue(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "venues"
    __table_args__ = (Index("ix_venues_shared_id", "id", "is_shared"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), default=None)
    latitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)
    longitude: Mapped[float | None] = mapped_column(Numeric(9, 6), default=None)
    capacity: Mapped[int | None] = mapped_column(Integer, default=None)
    availability: Mapped[list] = mapped_column(JSON, default=list, nullable=False, server_default="[]")
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    event: Mapped["Event"] = relationship(back_populates="venues")


class ScheduleItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "schedule_items"
    __table_args__ = (
        Index("ix_schedule_items_venue_window", "venue_id", "start_time", "end_time", "status"),
        Index("ix_schedule_items_resource_window", "resource_key", "start_time", "end_time", "status"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    resource_key: Mapped[str | None] = mapped_column(String(120), default=None)
    expected_capacity: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[ScheduleStatus] = mapped_column(Enum(ScheduleStatus), default=ScheduleStatus.SCHEDULED, nullable=False)

    event: Mapped["Event"] = relationship(back_populates="schedule_items")


class Sponsor(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsors"
    __table_args__ = (UniqueConstraint("event_id", "inquiry_id", name="uq_sponsor_event_inquiry"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(100), default=None)
    logo_url: Mapped[str | None] = mapped_column(String(500), default=None)
    status: Mapped[SponsorStatus] = mapped_column(
        Enum(SponsorStatus), default=SponsorStatus.CONFIRMED, nullable=False
    )
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    offer_details: Mapped[str | None] = mapped_column(Text, default=None)
    benefits: Mapped[list | None] = mapped_column(JSON, default=list)
    website_url: Mapped[str | None] = mapped_column(String(500), default=None)
    contact_email: Mapped[str | None] = mapped_column(String(320), default=None)
    committed_value: Mapped[float | None] = mapped_column(Numeric(12, 2), default=None)
    paid_value: Mapped[float | None] = mapped_column(Numeric(12, 2), default=None)
    inquiry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("sponsorship_inquiries.id"), default=None, index=True
    )

    event: Mapped["Event"] = relationship(back_populates="sponsors")
