import uuid
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.volunteer_shifts.models import (
    ASSIGNABLE_STATUSES,
    VolunteerAttendance,
    VolunteerShift,
    VolunteerShiftAssignment,
)
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationStatus, VolunteerApplicationType


class VolunteerShiftRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_shift(self, shift_id: uuid.UUID, *, lock: bool = False):
        stmt = select(VolunteerShift).where(VolunteerShift.id == shift_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def count_assigned(self, shift_id: uuid.UUID) -> int:
        return int(await self.db.scalar(select(func.count(VolunteerShiftAssignment.id)).where(
            VolunteerShiftAssignment.shift_id == shift_id,
            VolunteerShiftAssignment.status.in_(ASSIGNABLE_STATUSES),
        )) or 0)

    async def list_shifts(self, event_ids: set[uuid.UUID] | None, *, page: int, page_size: int, search: str | None = None, status=None):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(VolunteerShift.event_id.in_(event_ids))
        if status is not None:
            filters.append(VolunteerShift.status == status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(VolunteerShift.title.ilike(term), VolunteerShift.location.ilike(term)))
        total = int(await self.db.scalar(select(func.count(VolunteerShift.id)).where(*filters)) or 0)
        rows = (await self.db.execute(select(VolunteerShift).where(*filters).order_by(
            VolunteerShift.starts_at.asc(), VolunteerShift.id.asc()
        ).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def assignment(self, assignment_id: uuid.UUID, *, lock: bool = False):
        stmt = select(VolunteerShiftAssignment).where(VolunteerShiftAssignment.id == assignment_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def assignment_for_user(self, shift_id: uuid.UUID, user_id: uuid.UUID, *, lock: bool = False):
        stmt = select(VolunteerShiftAssignment).where(
            VolunteerShiftAssignment.shift_id == shift_id, VolunteerShiftAssignment.user_id == user_id
        )
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def overlap(self, user_id: uuid.UUID, starts_at, ends_at, *, exclude_shift_id=None) -> bool:
        stmt = select(VolunteerShiftAssignment.id).join(
            VolunteerShift, VolunteerShift.id == VolunteerShiftAssignment.shift_id
        ).where(
            VolunteerShiftAssignment.user_id == user_id,
            VolunteerShiftAssignment.status.in_(ASSIGNABLE_STATUSES),
            VolunteerShift.starts_at < ends_at,
            VolunteerShift.ends_at > starts_at,
        )
        if exclude_shift_id:
            stmt = stmt.where(VolunteerShift.id != exclude_shift_id)
        return (await self.db.scalar(stmt.limit(1))) is not None

    async def list_assignments(self, *, event_ids: set[uuid.UUID] | None, user_id=None, shift_id=None, page=1, page_size=25, status=None, search=None):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(VolunteerShiftAssignment.event_id.in_(event_ids))
        if user_id:
            filters.append(VolunteerShiftAssignment.user_id == user_id)
        if shift_id:
            filters.append(VolunteerShiftAssignment.shift_id == shift_id)
        if status:
            filters.append(VolunteerShiftAssignment.status == status)
        if search:
            filters.append(VolunteerShift.title.ilike(f"%{search.strip()}%"))
        stmt = select(VolunteerShiftAssignment).join(VolunteerShift, VolunteerShift.id == VolunteerShiftAssignment.shift_id).where(*filters)
        total = int(await self.db.scalar(select(func.count(VolunteerShiftAssignment.id)).join(VolunteerShift, VolunteerShift.id == VolunteerShiftAssignment.shift_id).where(*filters)) or 0)
        rows = (await self.db.execute(stmt.order_by(VolunteerShiftAssignment.created_at.desc(), VolunteerShiftAssignment.id.desc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total

    async def attendance(self, assignment_id: uuid.UUID, *, lock=False):
        stmt = select(VolunteerAttendance).where(VolunteerAttendance.assignment_id == assignment_id)
        if lock:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def user_ids_for_shift(self, shift_id: uuid.UUID) -> list[uuid.UUID]:
        rows = await self.db.scalars(select(VolunteerShiftAssignment.user_id).where(
            VolunteerShiftAssignment.shift_id == shift_id,
            VolunteerShiftAssignment.status.in_({
                # Requests and approved assignments both need change notices;
                # cancelled/rejected history does not.
                "requested", "approved", "active",
            }),
        ))
        return list(dict.fromkeys(rows.all()))

    async def eligible_volunteers(self, event_id: uuid.UUID, *, shift_id: uuid.UUID, starts_at, ends_at, required_role=None, page=1, page_size=25, search=None):
        filters = [VolunteerApplication.event_id == event_id, VolunteerApplication.application_type == VolunteerApplicationType.VOLUNTEER, VolunteerApplication.status == VolunteerApplicationStatus.APPROVED]
        filters.append(~exists(select(1).select_from(VolunteerShiftAssignment).where(
            VolunteerShiftAssignment.shift_id == shift_id,
            VolunteerShiftAssignment.user_id == VolunteerApplication.user_id,
        )))
        filters.append(~exists(select(1).select_from(VolunteerShiftAssignment).join(VolunteerShift, VolunteerShift.id == VolunteerShiftAssignment.shift_id).where(
            VolunteerShiftAssignment.user_id == VolunteerApplication.user_id,
            VolunteerShiftAssignment.status.in_(ASSIGNABLE_STATUSES),
            VolunteerShift.id != shift_id,
            VolunteerShift.starts_at < ends_at,
            VolunteerShift.ends_at > starts_at,
        )))
        if required_role:
            role_term = f"%{required_role.strip()}%"
            filters.append(or_(VolunteerApplication.preferred_responsibility.ilike(role_term), VolunteerApplication.skills_experience.ilike(role_term)))
        if search:
            filters.append(VolunteerApplication.full_name.ilike(f"%{search.strip()}%"))
        total = int(await self.db.scalar(select(func.count(VolunteerApplication.id)).where(*filters)) or 0)
        rows = (await self.db.execute(select(VolunteerApplication).where(*filters).order_by(VolunteerApplication.full_name.asc(), VolunteerApplication.id.asc()).offset((page - 1) * page_size).limit(page_size))).scalars().all()
        return list(rows), total
