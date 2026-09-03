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

    async def list_for_requester(self, requester_user_id: uuid.UUID) -> list[AssistanceRequest]:
        """
        BUG FIX: found while building the mobile app's assistance-request
        status screen — list_for_event is Event-Manager-only
        (_can_review_event), so a participant who actually SUBMITTED a
        fee-waiver request had no way whatsoever to check its status
        afterward. Same class of gap as the team/staff-assignment
        visibility issues found in earlier phases.
        """
        result = await self.db.execute(
            select(AssistanceRequest).where(AssistanceRequest.requester_user_id == requester_user_id)
        )
        return list(result.scalars().all())