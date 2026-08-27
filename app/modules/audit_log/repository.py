"""
Read-only query access to the audit log. Writes happen exclusively
through core/audit.py's write_audit_log(), called from every other
module — this repository is only ever used from this module's own
service.py to power the Console's audit trail viewer.
"""
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.models import AuditLog


class AuditLogRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

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
    ) -> tuple[list[AuditLog], int]:
        conditions = []
        if entity_type is not None:
            conditions.append(AuditLog.entity_type == entity_type)
        if entity_id is not None:
            conditions.append(AuditLog.entity_id == entity_id)
        if actor_user_id is not None:
            conditions.append(AuditLog.actor_user_id == actor_user_id)
        if action is not None:
            conditions.append(AuditLog.action == action)
        if date_from is not None:
            conditions.append(AuditLog.created_at >= date_from)
        if date_to is not None:
            conditions.append(AuditLog.created_at <= date_to)

        count_query = select(func.count()).select_from(AuditLog)
        items_query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)
        for condition in conditions:
            count_query = count_query.where(condition)
            items_query = items_query.where(condition)

        total = (await self.db.execute(count_query)).scalar_one()
        items = (await self.db.execute(items_query)).scalars().all()
        return list(items), int(total)

    async def get_for_entity(self, entity_type: str, entity_id: uuid.UUID) -> list[AuditLog]:
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.entity_type == entity_type, AuditLog.entity_id == entity_id)
            .order_by(AuditLog.created_at.asc())
        )
        return list(result.scalars().all())