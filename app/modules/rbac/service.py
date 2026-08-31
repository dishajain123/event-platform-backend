"""
Business logic for role assignment: enforces that global roles are
never given an event_id, and scoped roles always require one — this
is what keeps the RoleAssignment table's data honest for the
permission engine in core/permissions.py to trust.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.rbac.exceptions import RoleNotFoundError, ScopeNotAllowedError, ScopeRequiredError
from app.modules.rbac.models import GLOBAL_ROLES, SCOPED_ROLES, AssignmentStatus, RoleAssignment, RoleName
from app.modules.rbac.repository import RoleAssignmentRepository, RoleRepository


class RBACService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.roles = RoleRepository(db)
        self.assignments = RoleAssignmentRepository(db)

    async def assign_role(
        self,
        *,
        target_user_id: uuid.UUID,
        role_name: RoleName,
        event_id: uuid.UUID | None,
        assigned_by: uuid.UUID,
    ) -> RoleAssignment:
        role = await self.roles.get_by_name(role_name)
        if role is None:
            raise RoleNotFoundError(f"Role '{role_name}' is not a recognized role.")

        if role_name in GLOBAL_ROLES and event_id is not None:
            raise ScopeNotAllowedError(f"'{role_name}' is a global role and cannot be scoped to an event.")
        if role_name in SCOPED_ROLES and event_id is None:
            raise ScopeRequiredError(f"'{role_name}' requires an event_id.")

        assignment = await self.assignments.create(
            user_id=target_user_id, role_id=role.id, event_id=event_id, assigned_by=assigned_by
        )
        await write_audit_log(
            self.db,
            entity_type="role_assignment",
            entity_id=assignment.id,
            action="assigned",
            actor_user_id=assigned_by,
            after_value={
                "user_id": str(target_user_id),
                "role": role_name.value,
                "event_id": str(event_id) if event_id else None,
            },
        )
        await self.db.commit()
        return assignment

    async def list_roles(self):
        return await self.roles.list_all()

    async def list_my_active_role_assignments(self, user_id: uuid.UUID) -> list[dict]:
        """
        Resolves the current user's own active RoleAssignments to their
        role NAME (joining against Role, so the caller doesn't have to
        separately fetch GET /roles and cross-reference role_id itself).
        This is what a client uses immediately after login to know what
        it's allowed to do — there was previously no way to answer
        "what roles do I hold" at all after authenticating.
        """
        assignments = await self.assignments.list_for_user(user_id)
        results = []
        for assignment in assignments:
            if assignment.status != AssignmentStatus.ACTIVE:
                continue
            role = await self.roles.get_by_id(assignment.role_id)
            if role is None:
                continue
            results.append(
                {
                    "role_name": role.name,
                    "event_id": assignment.event_id,
                    "status": assignment.status.value,
                }
            )
        return results