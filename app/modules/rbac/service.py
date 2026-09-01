"""
Business logic for role assignment: enforces that global roles are
never given an event_id, and scoped roles always require one — this
is what keeps the RoleAssignment table's data honest for the
permission engine in core/permissions.py to trust.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.exceptions import PermissionDeniedError
from app.core.permissions import get_active_assignments
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

        actor_roles = await self.get_active_role_names_for_user(assigned_by)
        allowed_roles: set[RoleName] = set()
        if RoleName.SUPER_ADMIN in actor_roles:
            allowed_roles.update(
                {
                    RoleName.OPERATIONS_ADMIN,
                    RoleName.FINANCE_ADMIN,
                    RoleName.FINANCE_OPERATOR,
                    RoleName.FINANCE_AUDITOR,
                    RoleName.EVENT_MANAGER,
                }
            )
        if RoleName.OPERATIONS_ADMIN in actor_roles:
            allowed_roles.add(RoleName.EVENT_MANAGER)
        if RoleName.FINANCE_ADMIN in actor_roles:
            allowed_roles.update({RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR})

        if role_name not in allowed_roles:
            raise PermissionDeniedError("You don't have permission to assign this role.")

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

    async def get_active_role_names_for_user(self, user_id: uuid.UUID) -> set[RoleName]:
        active_assignments = await get_active_assignments(self.db, user_id)
        role_names: set[RoleName] = set()
        for assignment in active_assignments:
            role = await self.roles.get_by_id(assignment.role_id)
            if role is not None:
                role_names.add(role.name)
        return role_names

    async def list_assignable_roles_for_user(self, user_id: uuid.UUID) -> list:
        role_names = await self.get_active_role_names_for_user(user_id)
        allowed: set[RoleName] = set()

        if RoleName.SUPER_ADMIN in role_names:
            allowed.update(
                {
                    RoleName.OPERATIONS_ADMIN,
                    RoleName.FINANCE_ADMIN,
                    RoleName.FINANCE_OPERATOR,
                    RoleName.FINANCE_AUDITOR,
                    RoleName.EVENT_MANAGER,
                }
            )
        if RoleName.OPERATIONS_ADMIN in role_names:
            allowed.add(RoleName.EVENT_MANAGER)
        if RoleName.FINANCE_ADMIN in role_names:
            allowed.update({RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR})

        roles = await self.roles.list_all()
        return [role for role in roles if role.name in allowed]

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
