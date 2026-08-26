"""Data access for staff assignments and assignment history."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.staff.models import StaffAssignment, StaffAssignmentHistory, StaffAssignmentStatus


class StaffAssignmentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> StaffAssignment:
        assignment = StaffAssignment(**kwargs)
        self.db.add(assignment)
        await self.db.flush()
        return assignment

    async def get_by_id(self, assignment_id: uuid.UUID) -> StaffAssignment | None:
        return await self.db.get(StaffAssignment, assignment_id)

    async def list_for_event(self, event_id: uuid.UUID) -> list[StaffAssignment]:
        result = await self.db.execute(
            select(StaffAssignment).where(StaffAssignment.event_id == event_id)
        )
        return list(result.scalars().all())

    async def find_active_conflict(
        self, *, event_id: uuid.UUID, invitee_mobile: str, role_label: str, venue_id: uuid.UUID | None
    ) -> StaffAssignment | None:
        query = select(StaffAssignment).where(
            StaffAssignment.event_id == event_id,
            StaffAssignment.invitee_mobile == invitee_mobile,
            StaffAssignment.role_label == role_label,
            StaffAssignment.status != StaffAssignmentStatus.REVOKED,
        )
        if venue_id is None:
            query = query.where(StaffAssignment.venue_id.is_(None))
        else:
            query = query.where(StaffAssignment.venue_id == venue_id)
        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class StaffAssignmentHistoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> StaffAssignmentHistory:
        entry = StaffAssignmentHistory(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def list_for_assignment(self, assignment_id: uuid.UUID) -> list[StaffAssignmentHistory]:
        result = await self.db.execute(
            select(StaffAssignmentHistory).where(StaffAssignmentHistory.assignment_id == assignment_id)
        )
        return list(result.scalars().all())
