"""Thin service wrapping AuditLogRepository for the Console's audit trail viewer."""
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.exceptions import InvalidAuditLogFilterError
from app.modules.audit_log.repository import AuditLogRepository
from app.modules.audit_log.schemas import AuditLogPageOut, AuditLogOut

MAX_PAGE_SIZE = 200


class AuditLogService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = AuditLogRepository(db)

    async def query(
        self,
        *,
        entity_type: str | None = None,
        entity_id: uuid.UUID | None = None,
        actor_user_id: uuid.UUID | None = None,
        action: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AuditLogPageOut:
        if limit < 1 or limit > MAX_PAGE_SIZE:
            raise InvalidAuditLogFilterError(f"limit must be between 1 and {MAX_PAGE_SIZE}.")
        if offset < 0:
            raise InvalidAuditLogFilterError("offset cannot be negative.")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise InvalidAuditLogFilterError("date_from cannot be after date_to.")

        items, total = await self.repo.query(
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            action=action,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            offset=offset,
        )
        return AuditLogPageOut(
            items=[AuditLogOut.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get_history_for_entity(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLogOut]:
        items = await self.repo.get_for_entity(entity_type, entity_id)
        return [AuditLogOut.model_validate(item) for item in items]