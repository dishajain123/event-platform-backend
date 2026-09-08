import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class SponsorshipInquiryStatus(StrEnum):
    NEW = "new"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    CLOSED = "closed"


ALLOWED_INQUIRY_TRANSITIONS: dict[SponsorshipInquiryStatus, set[SponsorshipInquiryStatus]] = {
    SponsorshipInquiryStatus.NEW: {
        SponsorshipInquiryStatus.REVIEWING,
        SponsorshipInquiryStatus.APPROVED,
        SponsorshipInquiryStatus.REJECTED,
        SponsorshipInquiryStatus.CLOSED,
    },
    SponsorshipInquiryStatus.REVIEWING: {
        SponsorshipInquiryStatus.APPROVED,
        SponsorshipInquiryStatus.REJECTED,
        SponsorshipInquiryStatus.CLOSED,
    },
    SponsorshipInquiryStatus.APPROVED: {
        SponsorshipInquiryStatus.CONFIRMED,
        SponsorshipInquiryStatus.REJECTED,
        SponsorshipInquiryStatus.CLOSED,
    },
    SponsorshipInquiryStatus.CONFIRMED: {SponsorshipInquiryStatus.CLOSED},
    SponsorshipInquiryStatus.REJECTED: {SponsorshipInquiryStatus.CLOSED},
    SponsorshipInquiryStatus.CLOSED: set(),
}


class SponsorshipCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsorship_categories"

    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(default=0, nullable=False)


class SponsorshipPackage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsorship_packages"

    category_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sponsorship_categories.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    benefits: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    minimum_offer: Mapped[float | None] = mapped_column(Numeric(12, 2), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    category: Mapped[SponsorshipCategory] = relationship()


class SponsorshipInquiry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsorship_inquiries"

    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_person: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    business_details: Mapped[str | None] = mapped_column(Text, default=None)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("sponsorship_categories.id"), default=None
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("sponsorship_packages.id"), default=None
    )
    offer_details: Mapped[str | None] = mapped_column(Text, default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[SponsorshipInquiryStatus] = mapped_column(
        Enum(SponsorshipInquiryStatus), default=SponsorshipInquiryStatus.NEW, nullable=False, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    events: Mapped[list["SponsorshipInquiryEvent"]] = relationship(
        back_populates="inquiry", cascade="all, delete-orphan"
    )


class SponsorshipInquiryEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsorship_inquiry_events"
    __table_args__ = (UniqueConstraint("inquiry_id", "event_id", name="uq_sponsorship_inquiry_event"), Index("ix_sponsorship_inquiry_events_event_inquiry", "event_id", "inquiry_id"))

    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sponsorship_inquiries.id"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)

    inquiry: Mapped[SponsorshipInquiry] = relationship(back_populates="events")


class SponsorshipDeliverableStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class SponsorshipDeliverable(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsorship_deliverables"
    __table_args__ = (
        Index("ix_sponsorship_deliverables_sponsor_status_due", "sponsor_id", "status", "due_date"),
        Index("ix_sponsorship_deliverables_event_status_due", "event_id", "status", "due_date"),
    )

    sponsor_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("sponsors.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    deliverable_type: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int | None] = mapped_column(Integer, default=None)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    status: Mapped[SponsorshipDeliverableStatus] = mapped_column(Enum(SponsorshipDeliverableStatus), default=SponsorshipDeliverableStatus.PENDING, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completion_notes: Mapped[str | None] = mapped_column(Text, default=None)
    evidence: Mapped[dict | None] = mapped_column(JSON, default=None)


class SponsorEngagementType(StrEnum):
    LEAD_CAPTURE = "lead_capture"
    BOOTH_VISIT = "booth_visit"
    SESSION_INTEREST = "session_interest"
    SPONSOR_INTERACTION = "sponsor_interaction"


class SponsorLeadStatus(StrEnum):
    CAPTURED = "captured"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    CONVERTED = "converted"
    DISMISSED = "dismissed"
    UNSUBSCRIBED = "unsubscribed"


class SponsorConsentStatus(StrEnum):
    NOT_GIVEN = "not_given"
    GIVEN = "given"
    WITHDRAWN = "withdrawn"


ALLOWED_LEAD_STATUS_TRANSITIONS: dict[SponsorLeadStatus, set[SponsorLeadStatus]] = {
    SponsorLeadStatus.CAPTURED: {
        SponsorLeadStatus.QUALIFIED,
        SponsorLeadStatus.DISMISSED,
        SponsorLeadStatus.UNSUBSCRIBED,
    },
    SponsorLeadStatus.QUALIFIED: {
        SponsorLeadStatus.CONTACTED,
        SponsorLeadStatus.DISMISSED,
        SponsorLeadStatus.UNSUBSCRIBED,
    },
    SponsorLeadStatus.CONTACTED: {
        SponsorLeadStatus.CONVERTED,
        SponsorLeadStatus.DISMISSED,
        SponsorLeadStatus.UNSUBSCRIBED,
    },
    SponsorLeadStatus.CONVERTED: {SponsorLeadStatus.UNSUBSCRIBED},
    SponsorLeadStatus.DISMISSED: set(),
    SponsorLeadStatus.UNSUBSCRIBED: set(),
}


class SponsorEngagement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sponsor_engagements"
    __table_args__ = (
        UniqueConstraint("sponsor_id", "event_id", "participant_id", "engagement_type", name="uq_sponsor_engagement_identity"),
        Index("ix_sponsor_engagements_event_sponsor_status", "event_id", "sponsor_id", "lead_status", "captured_at"),
        Index("ix_sponsor_engagements_event_participant", "event_id", "participant_id", "captured_at"),
        Index("ix_sponsor_engagements_sponsor_type", "sponsor_id", "engagement_type", "captured_at"),
    )

    sponsor_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("sponsors.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    participant_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    captured_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engagement_type: Mapped[SponsorEngagementType] = mapped_column(Enum(SponsorEngagementType), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, default=None)
    consent_status: Mapped[SponsorConsentStatus] = mapped_column(Enum(SponsorConsentStatus), nullable=False, default=SponsorConsentStatus.NOT_GIVEN)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    consent_source: Mapped[str | None] = mapped_column(String(80), default=None)
    lead_status: Mapped[SponsorLeadStatus] = mapped_column(Enum(SponsorLeadStatus), nullable=False, default=SponsorLeadStatus.CAPTURED)
