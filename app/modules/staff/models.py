"""
Staff assignments and assignment history for event operations.

role_name (RoleName enum) is what actually drives permissions — it's
the field that gets bridged into a real RoleAssignment when an
invitation is accepted (see service.py). role_label stays as an
optional, organization-chosen DISPLAY string (e.g. "Marshal", "Gate
Lead") shown in the Console/app UI — exactly the "what you call a role
on screen is a display concern, not the enum" principle from the
platform's account model. The two are deliberately separate: role_name
must be one of the four scoped roles for permissions to make sense;
role_label can be anything an Operations Admin or Event Manager wants
to type.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType
from app.modules.rbac.models import RoleName


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

    # The permission-bearing field — must be one of the four SCOPED_ROLES.
    # Nullable at the DB level only to keep the migration backward-safe for
    # any pre-existing rows; the service layer requires it on every new
    # assignment created from this point forward.
    role_name: Mapped[RoleName | None] = mapped_column(Enum(RoleName), default=None)

    # Display-only label, independent of role_name. Not used for any
    # permission decision anywhere in the codebase.
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

    # The RoleAssignment created in the RBAC system when this invitation is
    # accepted. This is THE bridge between "staff onboarding" and "actual
    # permissions" — without it, accepting an invitation grants nothing.
    linked_role_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("role_assignments.id"), default=None
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