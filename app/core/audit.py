"""
The single audit-log writer every module calls. Deliberately a plain
function rather than a service class — logging an action should never
require more ceremony than one line, or people stop doing it.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit_log.models import AuditLog


async def write_audit_log(
    db: AsyncSession,
    *,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_user_id: uuid.UUID | None,
    before_value: dict | None = None,
    after_value: dict | None = None,
) -> None:
    """
    Adds an audit entry to the current session WITHOUT committing —
    callers include this in the same transaction as the action itself,
    so the audit entry and the change it describes always succeed or
    fail together.
    """
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        before_value=before_value,
        after_value=after_value,
    )
    db.add(entry)