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

    async def revoke(self, assignment: RoleAssignment) -> None:
        from datetime import datetime, timezone

        assignment.status = AssignmentStatus.REVOKED
        assignment.revoked_at = datetime.now(timezone.utc)
        await self.db.flush()