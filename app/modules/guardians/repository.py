import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.guardians.models import ChildProfile, GuardianChildRelationship


class GuardianRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_child(self, **kwargs) -> ChildProfile:
        child = ChildProfile(**kwargs)
        self.db.add(child)
        await self.db.flush()
        return child

    async def add_relationship(self, **kwargs) -> GuardianChildRelationship:
        relationship = GuardianChildRelationship(**kwargs)
        self.db.add(relationship)
        await self.db.flush()
        return relationship

    async def list_children_for_guardian(self, guardian_user_id: uuid.UUID) -> list[ChildProfile]:
        result = await self.db.execute(
            select(ChildProfile)
            .join(GuardianChildRelationship, GuardianChildRelationship.child_id == ChildProfile.id)
            .where(GuardianChildRelationship.guardian_user_id == guardian_user_id)
        )
        return list(result.scalars().all())

    async def get_relationship(
        self, guardian_user_id: uuid.UUID, child_id: uuid.UUID
    ) -> GuardianChildRelationship | None:
        result = await self.db.execute(
            select(GuardianChildRelationship).where(
                GuardianChildRelationship.guardian_user_id == guardian_user_id,
                GuardianChildRelationship.child_id == child_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_child(self, child_id: uuid.UUID) -> ChildProfile | None:
        return await self.db.get(ChildProfile, child_id)
