"""
Staff assignments and assignment history for event operations.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class StaffAssignmentStatus(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    REVOKED = "revoked"


class StaffAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_assignments"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    invitee_mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    role_label: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[StaffAssignmentStatus] = mapped_column(
        Enum(StaffAssignmentStatus), default=StaffAssignmentStatus.INVITED
    )
    invited_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    superseded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("staff_assignments.id"), default=None
    )

    history: Mapped[list["StaffAssignmentHistory"]] = relationship(
        back_populates="assignment", cascade="all, delete-orphan"
    )


class StaffAssignmentHistory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "staff_assignment_history"

    assignment_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("staff_assignments.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    before_value: Mapped[dict | None] = mapped_column(JSON, default=None)
    after_value: Mapped[dict | None] = mapped_column(JSON, default=None)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    assignment: Mapped["StaffAssignment"] = relationship(back_populates="history")
