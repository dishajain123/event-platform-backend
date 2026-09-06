"""Persisted event feedback and its reusable category vocabulary."""
import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class FeedbackCategory(StrEnum):
    EVENT_EXPERIENCE = "event_experience"
    VENUE_FACILITIES = "venue_facilities"
    ORGANIZATION_MANAGEMENT = "organization_management"
    SCHEDULE_ACTIVITIES = "schedule_activities"
    FOOD_HOSPITALITY = "food_hospitality"
    TECHNICAL_EXPERIENCE = "technical_experience"
    OTHER = "other"

    @property
    def label(self) -> str:
        return {
            FeedbackCategory.EVENT_EXPERIENCE: "Event Experience",
            FeedbackCategory.VENUE_FACILITIES: "Venue & Facilities",
            FeedbackCategory.ORGANIZATION_MANAGEMENT: "Organization & Management",
            FeedbackCategory.SCHEDULE_ACTIVITIES: "Schedule & Activities",
            FeedbackCategory.FOOD_HOSPITALITY: "Food & Hospitality",
            FeedbackCategory.TECHNICAL_EXPERIENCE: "Technical Experience",
            FeedbackCategory.OTHER: "Other",
        }[self]


class EventFeedback(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_feedback"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "user_id",
            "category",
            name="uq_event_feedback_user_category",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    category: Mapped[FeedbackCategory] = mapped_column(String(64), nullable=False)
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, default=None)

    event = relationship("Event", foreign_keys=[event_id])
    user = relationship("User", foreign_keys=[user_id])
