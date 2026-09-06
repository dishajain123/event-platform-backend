import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationType


class VolunteerRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields):
        item = VolunteerApplication(**fields)
        self.db.add(item)
        await self.db.flush()
        return item

    async def get(self, application_id: uuid.UUID):
        return await self.db.get(VolunteerApplication, application_id)

    async def get_for_user_event(self, user_id: uuid.UUID, event_id: uuid.UUID, application_type: VolunteerApplicationType):
        result = await self.db.execute(select(VolunteerApplication).where(
            VolunteerApplication.user_id == user_id,
            VolunteerApplication.event_id == event_id,
            VolunteerApplication.application_type == application_type,
        ))
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID):
        result = await self.db.execute(select(VolunteerApplication).where(
            VolunteerApplication.user_id == user_id
        ).order_by(VolunteerApplication.created_at.desc()))
        return list(result.scalars().all())

    async def list_for_events(self, event_ids: set[uuid.UUID] | None, status=None, search=None, application_type=None):
        if event_ids is not None and not event_ids:
            return []
        stmt = select(VolunteerApplication)
        if event_ids is not None:
            stmt = stmt.where(VolunteerApplication.event_id.in_(event_ids))
        if status is not None:
            stmt = stmt.where(VolunteerApplication.status == status)
        if application_type is not None:
            stmt = stmt.where(VolunteerApplication.application_type == application_type)
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.where(
                VolunteerApplication.full_name.ilike(term)
                | VolunteerApplication.phone.ilike(term)
                | VolunteerApplication.email.ilike(term)
                | VolunteerApplication.skills_experience.ilike(term)
            )
        result = await self.db.execute(stmt.order_by(VolunteerApplication.created_at.desc()))
        return list(result.scalars().all())
