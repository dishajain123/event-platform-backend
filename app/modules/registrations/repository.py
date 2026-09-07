import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.registrations.models import (
    ACTIVE_REGISTRATION_STATUSES,
    Registration,
    RegistrationParticipant,
)
from app.modules.payments.models import Payment


class RegistrationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Registration:
        registration = Registration(**kwargs)
        self.db.add(registration)
        await self.db.flush()
        return registration

    async def get_by_id(self, registration_id: uuid.UUID) -> Registration | None:
        # BUG FIX: was `self.db.get(Registration, registration_id)`, which
        # does not eager-load relationships. RegistrationOut serializes
        # `participants`, and accessing a lazy-loaded relationship outside
        # an active async context (e.g. during FastAPI's post-request
        # response serialization) raises MissingGreenlet — this surfaced
        # in practice the moment a registration with participants was
        # successfully created and returned, rather than being masked by
        # an earlier validation error.
        result = await self.db.execute(
            select(Registration)
            .options(
                selectinload(Registration.participants),
                selectinload(Registration.payment).selectinload(Payment.refunds),
            )
            .where(Registration.id == registration_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Registration]:
        result = await self.db.execute(
            select(Registration)
            .options(
                selectinload(Registration.participants),
                selectinload(Registration.payment).selectinload(Payment.refunds),
            )
            .where(Registration.user_id == user_id)
        )
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Registration]:
        return await self.list_for_events({event_id})

    async def list_for_events(self, event_ids: set[uuid.UUID]) -> list[Registration]:
        if not event_ids:
            return []
        result = await self.db.execute(
            select(Registration)
            .options(
                selectinload(Registration.participants),
                selectinload(Registration.payment).selectinload(Payment.refunds),
            )
            .where(Registration.event_id.in_(event_ids))
            .order_by(Registration.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[Registration]:
        result = await self.db.execute(
            select(Registration)
            .options(
                selectinload(Registration.participants),
                selectinload(Registration.payment).selectinload(Payment.refunds),
            )
            .order_by(Registration.created_at.desc())
        )
        return list(result.scalars().all())

    async def page_for_events(
        self,
        event_ids: set[uuid.UUID] | None,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        status=None,
        participation_type: str | None = None,
    ) -> tuple[list[Registration], int]:
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(Registration.event_id.in_(event_ids))
        if search:
            filters.append(
                Registration.id.in_(
                    select(RegistrationParticipant.registration_id).where(
                        RegistrationParticipant.full_name.ilike(f"%{search}%")
                    )
                )
            )
        if status is not None:
            filters.append(Registration.status == status)
        if participation_type:
            filters.append(Registration.participation_type == participation_type)
        total = int((await self.db.execute(select(func.count()).select_from(Registration).where(*filters))).scalar_one())
        result = await self.db.execute(
            select(Registration)
            .options(
                selectinload(Registration.participants),
                selectinload(Registration.payment).selectinload(Payment.refunds),
            )
            .where(*filters)
            .order_by(Registration.created_at.desc(), Registration.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

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
