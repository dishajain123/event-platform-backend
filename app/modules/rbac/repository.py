import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.rbac.models import AssignmentStatus, Role, RoleAssignment, RoleName


class RoleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_name(self, name: RoleName) -> Role | None:
        result = await self.db.execute(select(Role).where(Role.name == name))
        return result.scalar_one_or_none()

    async def get_by_id(self, role_id: uuid.UUID) -> Role | None:
        return await self.db.get(Role, role_id)

    async def list_all(self) -> list[Role]:
        result = await self.db.execute(select(Role))
        return list(result.scalars().all())


class RoleAssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        event_id: uuid.UUID | None,
        assigned_by: uuid.UUID | None,
    ) -> RoleAssignment:
        assignment = RoleAssignment(
            user_id=user_id, role_id=role_id, event_id=event_id, assigned_by=assigned_by
        )
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def get_by_id(self, assignment_id: uuid.UUID) -> RoleAssignment | None:
        return await self.db.get(RoleAssignment, assignment_id)

    async def list_for_user(self, user_id: uuid.UUID) -> list[RoleAssignment]:
        result = await self.db.execute(
            select(RoleAssignment).where(RoleAssignment.user_id == user_id)
        )
        return list(result.scalars().all())

    async def list_active_user_ids_for_event_and_roles(
        self, event_id: uuid.UUID, role_names: set[RoleName]
    ) -> dict[RoleName, list[uuid.UUID]]:
        """
        Finds every user with an ACTIVE, event-scoped RoleAssignment to
        any of role_names for this specific event — regardless of
        whether that assignment was created directly via the RBAC
        endpoint or bridged in from an accepted Staff invitation (see
        staff/service.py's accept_assignment). Used as the RBAC-native
        fallback source of reviewers/assignees for a given event, since
        not every scoped role holder necessarily has a StaffAssignment
        row (e.g. an Event Manager granted directly by Super Admin).
        """
        result = await self.db.execute(
            select(Role.name, RoleAssignment.user_id)
            .join(Role, RoleAssignment.role_id == Role.id)
            .where(
                RoleAssignment.event_id == event_id,
                RoleAssignment.status == AssignmentStatus.ACTIVE,
                Role.name.in_(role_names),
            )
        )
        by_role: dict[RoleName, list[uuid.UUID]] = {name: [] for name in role_names}
        for role_name, user_id in result.all():
            by_role[role_name].append(user_id)
        return by_role

    async def revoke(self, assignment: RoleAssignment) -> None:
        from datetime import datetime, timezone

        assignment.status = AssignmentStatus.REVOKED
        assignment.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()