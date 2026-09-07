import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class VolunteerShiftStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    FULL = "full"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class VolunteerAssignmentStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    ACTIVE = "active"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class VolunteerAttendanceStatus(StrEnum):
    NOT_CHECKED_IN = "not_checked_in"
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    NO_SHOW = "no_show"
    CANCELLED = "cancelled"


ASSIGNABLE_STATUSES = {
    VolunteerAssignmentStatus.APPROVED,
    VolunteerAssignmentStatus.ACTIVE,
}
ACTIVE_SHIFT_STATUSES = {
    VolunteerShiftStatus.OPEN,
    VolunteerShiftStatus.FULL,
    VolunteerShiftStatus.IN_PROGRESS,
}
ALLOWED_SHIFT_TRANSITIONS = {
    VolunteerShiftStatus.DRAFT: {VolunteerShiftStatus.OPEN, VolunteerShiftStatus.CANCELLED},
    VolunteerShiftStatus.OPEN: {VolunteerShiftStatus.CANCELLED},
    VolunteerShiftStatus.FULL: {VolunteerShiftStatus.OPEN, VolunteerShiftStatus.CANCELLED},
    VolunteerShiftStatus.IN_PROGRESS: {VolunteerShiftStatus.COMPLETED, VolunteerShiftStatus.CANCELLED},
    VolunteerShiftStatus.COMPLETED: set(),
    VolunteerShiftStatus.CANCELLED: set(),
}
ALLOWED_ASSIGNMENT_TRANSITIONS = {
    VolunteerAssignmentStatus.REQUESTED: {
        VolunteerAssignmentStatus.APPROVED,
        VolunteerAssignmentStatus.REJECTED,
        VolunteerAssignmentStatus.CANCELLED,
    },
    VolunteerAssignmentStatus.APPROVED: {
        VolunteerAssignmentStatus.ACTIVE,
        VolunteerAssignmentStatus.CANCELLED,
    },
    VolunteerAssignmentStatus.ACTIVE: {
        VolunteerAssignmentStatus.COMPLETED,
        VolunteerAssignmentStatus.CANCELLED,
    },
    VolunteerAssignmentStatus.COMPLETED: set(),
    VolunteerAssignmentStatus.REJECTED: set(),
    VolunteerAssignmentStatus.CANCELLED: set(),
}


class VolunteerShift(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "volunteer_shifts"
    __table_args__ = (
        Index("ix_volunteer_shifts_event_status_start", "event_id", "status", "starts_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    location: Mapped[str | None] = mapped_column(String(255), default=None)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    required_count: Mapped[int] = mapped_column(Integer, nullable=False)
    required_role: Mapped[str | None] = mapped_column(String(120), default=None)
    status: Mapped[VolunteerShiftStatus] = mapped_column(
        Enum(VolunteerShiftStatus), default=VolunteerShiftStatus.DRAFT, nullable=False, index=True
    )


class VolunteerShiftAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "volunteer_shift_assignments"
    __table_args__ = (
        UniqueConstraint("shift_id", "user_id", name="uq_volunteer_shift_assignment_user"),
        Index("ix_volunteer_shift_assignments_event_status", "event_id", "status", "created_at"),
        Index("ix_volunteer_shift_assignments_user_status", "user_id", "status"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    shift_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("volunteer_shifts.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    volunteer_application_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("volunteer_applications.id"), default=None
    )
    status: Mapped[VolunteerAssignmentStatus] = mapped_column(
        Enum(VolunteerAssignmentStatus), default=VolunteerAssignmentStatus.REQUESTED, nullable=False, index=True
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class VolunteerAttendance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "volunteer_attendance"
    __table_args__ = (
        UniqueConstraint("assignment_id", name="uq_volunteer_attendance_assignment"),
        Index("ix_volunteer_attendance_event_status", "event_id", "status", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    shift_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("volunteer_shifts.id"), nullable=False)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("volunteer_shift_assignments.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    status: Mapped[VolunteerAttendanceStatus] = mapped_column(
        Enum(VolunteerAttendanceStatus), default=VolunteerAttendanceStatus.NOT_CHECKED_IN, nullable=False, index=True
    )
    first_check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    final_check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    worked_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
