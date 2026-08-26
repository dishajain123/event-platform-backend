"""Data access for assistance requests."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assistance.models import AssistanceRequest


class AssistanceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> AssistanceRequest:
        request = AssistanceRequest(**kwargs)
        self.db.add(request)
        await self.db.flush()
        return request

    async def get_by_id(self, request_id: uuid.UUID) -> AssistanceRequest | None:
        return await self.db.get(AssistanceRequest, request_id)

    async def list_for_event(self, event_id: uuid.UUID) -> list[AssistanceRequest]:
        result = await self.db.execute(
            select(AssistanceRequest).where(AssistanceRequest.event_id == event_id)
        )
        return list(result.scalars().all())

    async def get_by_registration_id(self, registration_id: uuid.UUID) -> AssistanceRequest | None:
        result = await self.db.execute(
            select(AssistanceRequest).where(AssistanceRequest.registration_id == registration_id)
        )
        return result.scalar_one_or_none()
