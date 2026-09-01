"""
Role, Permission, RolePermission, and RoleAssignment.

RoleAssignment is the key design piece: a role can be GLOBAL (event_id
is null — Super Admin, Operations Admin, Finance Admin, Finance
Operator, Finance Auditor) or EVENT-SCOPED (event_id is set — Event
Manager, Event Coordinator, Staff Lead, Staff Member). The same table
and the same permission-checking code handles both, so scoped roles
aren't a special case bolted on afterward.

Note: event_id is a plain UUID column, not yet a ForeignKey — the
`events` table doesn't exist until Phase 2. Phase 2's migration adds
the FK constraint once app/modules/events/models.py exists.
"""
import uuid
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class RoleName(StrEnum):
    """
    The platform's built-in role names.

    The console now treats Operations Admin, Finance Admin, Finance
    Operator, Finance Auditor, and Event Manager as the supported
    account-management roles. The older event_coordinator/staff_lead/
    staff_member names remain only for backward compatibility with
    existing data and legacy mobile flows.
    """

    SUPER_ADMIN = "super_admin"
    OPERATIONS_ADMIN = "operations_admin"
    FINANCE_ADMIN = "finance_admin"
    FINANCE_OPERATOR = "finance_operator"
    FINANCE_AUDITOR = "finance_auditor"
    EVENT_MANAGER = "event_manager"          # scoped — console + mobile Staff Mode
    EVENT_COORDINATOR = "event_coordinator"  # legacy scoped — mobile Staff Mode only
    STAFF_LEAD = "staff_lead"                # legacy scoped — mobile Staff Mode only
    STAFF_MEMBER = "staff_member"            # legacy scoped — mobile Staff Mode only


# Roles that apply platform-wide and are never tied to one event.
GLOBAL_ROLES = {
    RoleName.SUPER_ADMIN,
    RoleName.OPERATIONS_ADMIN,
    RoleName.FINANCE_ADMIN,
    RoleName.FINANCE_OPERATOR,
    RoleName.FINANCE_AUDITOR,
}

# Roles that must always be assigned with a specific event_id.
SCOPED_ROLES = {
    RoleName.EVENT_MANAGER,
    RoleName.EVENT_COORDINATOR,
    RoleName.STAFF_LEAD,
    RoleName.STAFF_MEMBER,
}


class AssignmentStatus(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"


class Role(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "roles"

    name: Mapped[RoleName] = mapped_column(Enum(RoleName), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), default=None)
    is_scoped: Mapped[bool] = mapped_column(Boolean, nullable=False)


class Permission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Granular permission codes (e.g. "event.publish", "registration.approve").
    Not fully populated/enforced until later phases start using
    require_permission() alongside require_role() — the table exists from
    Phase 1 so later phases are additive, not a schema change.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), default=None)


class RolePermission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),)

    role_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("roles.id"), nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("permissions.id"), nullable=False
    )


class RoleAssignment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Links a User to a Role, optionally scoped to one event_id.
    This is what a Console or mobile Staff Mode login is checked against.
    """

    __tablename__ = "role_assignments"

    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("roles.id"), nullable=False)
    event_id: Mapped[uuid.UUID | None] = mapped_column(
    UUIDType, ForeignKey("events.id"), default=None
)
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), default=AssignmentStatus.ACTIVE
    )
    revoked_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped["User"] = relationship(  # noqa: F821 — User lives in modules.identity, resolved via registry
        back_populates="role_assignments", foreign_keys=[user_id]
    )
    role: Mapped["Role"] = relationship()
