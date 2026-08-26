import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.registrations.models import (
    ACTIVE_REGISTRATION_STATUSES,
    Registration,
    RegistrationParticipant,
    RegistrationStatus,
)


class RegistrationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Registration:
        registration = Registration(**kwargs)
        self.db.add(registration)
        await self.db.flush()
        return registration

    async def get_by_id(self, registration_id: uuid.UUID) -> Registration | None:
        return await self.db.get(Registration, registration_id)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Registration]:
        result = await self.db.execute(select(Registration).where(Registration.user_id == user_id))
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Registration]:
        result = await self.db.execute(
            select(Registration).where(Registration.event_id == event_id)
        )
        return list(result.scalars().all())

    async def count_active_for_event(self, event_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Registration)
            .where(
                Registration.event_id == event_id,
                Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)),
            )
        )
        return int(result.scalar_one())

    async def find_duplicate(
        self,
        *,
        event_id: uuid.UUID,
        user_id: uuid.UUID,
        child_id: uuid.UUID | None,
        participation_type: str,
    ) -> Registration | None:
        result = await self.db.execute(
            select(Registration).where(
                Registration.event_id == event_id,
                Registration.user_id == user_id,
                Registration.child_id == child_id,
                Registration.participation_type == participation_type,
                Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)),
            )
        )
        return result.scalar_one_or_none()

    async def add_participant(self, **kwargs) -> RegistrationParticipant:
        participant = RegistrationParticipant(**kwargs)
        self.db.add(participant)
        await self.db.flush()
        return participant
