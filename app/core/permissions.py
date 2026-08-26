"""
The RBAC engine. Every module's router uses require_role() or
require_scoped_role() (from app/dependencies.py, which wraps the
functions here) to gate an endpoint — this file is the one place that
decides what "has permission" actually means.
"""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import GLOBAL_ROLES, SCOPED_ROLES, AssignmentStatus, Role, RoleAssignment, RoleName


async def get_active_assignments(db: AsyncSession, user_id: uuid.UUID) -> list[RoleAssignment]:
    result = await db.execute(
        select(RoleAssignment)
        .join(Role, RoleAssignment.role_id == Role.id)
        .where(
            RoleAssignment.user_id == user_id,
            RoleAssignment.status == AssignmentStatus.ACTIVE,
        )
    )
    return list(result.scalars().all())


async def user_has_global_role(
    db: AsyncSession, user_id: uuid.UUID, allowed_roles: set[RoleName]
) -> bool:
    """True if the user has an active, unscoped (event_id is null) assignment
    to any role in allowed_roles. Used for Super Admin / Operations Admin /
    Finance Admin-style endpoints."""
    assignments = await get_active_assignments(db, user_id)
    for assignment in assignments:
        role: Role = await db.get(Role, assignment.role_id)
        if role.name in allowed_roles and role.name in GLOBAL_ROLES and assignment.event_id is None:
            return True
    return False


async def user_has_scoped_role(
    db: AsyncSession,
    user_id: uuid.UUID,
    allowed_roles: set[RoleName],
    event_id: uuid.UUID,
    allow_global_roles: set[RoleName] | None = None,
) -> bool:
    """
    True if the user has an active assignment to any role in allowed_roles
    SPECIFICALLY for this event_id — e.g. an Event Manager assigned to
    event A is rejected when event B is requested.

    allow_global_roles lets certain platform-wide roles (typically Super
    Admin / Operations Admin) bypass the scope check entirely, since they
    are meant to reach every event.
    """
    assignments = await get_active_assignments(db, user_id)
    for assignment in assignments:
        role: Role = await db.get(Role, assignment.role_id)

        if allow_global_roles and role.name in allow_global_roles and assignment.event_id is None:
            return True

        if (
            role.name in allowed_roles
            and role.name in SCOPED_ROLES
            and assignment.event_id == event_id
        ):
            return True
    return False