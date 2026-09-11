"""Primary manager changes participate in the caller's transaction."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role
from app.exceptions import PermissionDeniedError, ValidationError
from app.modules.events.models import Event
from app.modules.identity.models import User
from app.modules.rbac.models import AssignmentStatus, Role, RoleAssignment, RoleName


async def assign_event_manager(db, event_id, user_id, actor_id):
    if not await user_has_global_role(db, actor_id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
        raise PermissionDeniedError("Only Operations or Super Admin can change the event manager.")
    # Serialize assignments to the same event so two admins cannot create two primaries.
    event = (await db.execute(select(Event).where(Event.id == event_id,
        Event.deleted_at.is_(None)).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if event is None:
        raise ValidationError("Event not found.")
    user = (await db.execute(select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True))).scalar_one_or_none()
    if user is None or not user.is_active or not user.is_event_manager:
        raise ValidationError("Select an existing active Event Manager account from Admin Accounts.")
    role = (await db.execute(select(Role).where(Role.name == RoleName.EVENT_MANAGER))).scalar_one()
    assignments = (await db.execute(select(RoleAssignment).where(
        RoleAssignment.event_id == event_id, RoleAssignment.role_id == role.id,
        RoleAssignment.status == AssignmentStatus.ACTIVE))).scalars().all()
    selected = None
    for assignment in assignments:
        if assignment.user_id == user_id and selected is None:
            selected = assignment
        else:
            assignment.status = AssignmentStatus.REVOKED
            assignment.revoked_at = datetime.now(timezone.utc)
    previous = event.organizer_user_id
    event.organizer_user_id = user_id
    if selected is None:
        selected = RoleAssignment(user_id=user_id, role_id=role.id, event_id=event_id,
            assigned_by=actor_id, status=AssignmentStatus.ACTIVE)
        db.add(selected)
    await db.flush()
    await write_audit_log(db, entity_type="event", entity_id=event_id,
        action="manager_assigned", actor_user_id=actor_id,
        before_value={"organizer_user_id": str(previous) if previous else None},
        after_value={"organizer_user_id": str(user_id)})
    return selected
