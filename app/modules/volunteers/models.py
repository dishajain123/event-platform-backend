import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class VolunteerApplicationStatus(StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    CONTACTED = "contacted"
    APPROVED = "approved"
    REJECTED = "rejected"


class VolunteerApplicationType(StrEnum):
    VOLUNTEER = "volunteer"
    EVENT_MANAGER = "event_manager"


ALLOWED_VOLUNTEER_TRANSITIONS = {
    VolunteerApplicationStatus.SUBMITTED: {
        VolunteerApplicationStatus.UNDER_REVIEW,
        VolunteerApplicationStatus.CONTACTED,
        VolunteerApplicationStatus.APPROVED,
        VolunteerApplicationStatus.REJECTED,
    },
    VolunteerApplicationStatus.UNDER_REVIEW: {
        VolunteerApplicationStatus.CONTACTED,
        VolunteerApplicationStatus.APPROVED,
        VolunteerApplicationStatus.REJECTED,
    },
    VolunteerApplicationStatus.CONTACTED: {
        VolunteerApplicationStatus.APPROVED,
        VolunteerApplicationStatus.REJECTED,
    },
    VolunteerApplicationStatus.APPROVED: set(),
    VolunteerApplicationStatus.REJECTED: set(),
}


class VolunteerApplication(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "volunteer_applications"
    __table_args__ = (UniqueConstraint("event_id", "user_id", "application_type", name="uq_volunteer_application_event_user_type"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    application_type: Mapped[VolunteerApplicationType] = mapped_column(
        Enum(VolunteerApplicationType), default=VolunteerApplicationType.VOLUNTEER, nullable=False, index=True
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), default=None)
    skills_experience: Mapped[str | None] = mapped_column(Text, default=None)
    availability: Mapped[str | None] = mapped_column(Text, default=None)
    preferred_responsibility: Mapped[str | None] = mapped_column(String(255), default=None)
    message: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[VolunteerApplicationStatus] = mapped_column(
        Enum(VolunteerApplicationStatus), default=VolunteerApplicationStatus.SUBMITTED, nullable=False, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    activated_staff_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("staff_assignments.id"), default=None
    )
