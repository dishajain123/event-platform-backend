import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
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
    __table_args__ = (UniqueConstraint("inquiry_id", "event_id", name="uq_sponsorship_inquiry_event"),)

    inquiry_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("sponsorship_inquiries.id"), nullable=False, index=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)

    inquiry: Mapped[SponsorshipInquiry] = relationship(back_populates="events")
