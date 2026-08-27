"""
Audit log read endpoints — Console only. Gated to the roles that
genuinely need accountability visibility: Super Admin and Operations
Admin for operational actions, Finance Admin/Auditor for financial
ones. Nobody else (including scoped Event Managers) can see the audit
trail — it's platform-level oversight, not an event-management tool.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role
from app.modules.audit_log.schemas import AuditLogOut, AuditLogPageOut
from app.modules.audit_log.service import AuditLogService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/audit-log", tags=["audit_log"])

_can_view_audit_log = require_role(
    RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN, RoleName.FINANCE_ADMIN, RoleName.FINANCE_AUDITOR
)


def get_audit_log_service(db: AsyncSession = Depends(get_db)) -> AuditLogService:
    return AuditLogService(db)


@router.get("", response_model=AuditLogPageOut, dependencies=[Depends(_can_view_audit_log)])
async def query_audit_log(
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_user_id: str | None = None,
    action: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: AuditLogService = Depends(get_audit_log_service),
):
    """Called by: console (Super Admin, Operations Admin, Finance Admin, Finance Auditor)."""
    return await service.query(
        entity_type=entity_type,
        entity_id=uuid.UUID(entity_id) if entity_id else None,
        actor_user_id=uuid.UUID(actor_user_id) if actor_user_id else None,
        action=action,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/entity/{entity_type}/{entity_id}",
    response_model=list[AuditLogOut],
    dependencies=[Depends(_can_view_audit_log)],
)
async def get_entity_history(
    entity_type: str,
    entity_id: str,
    service: AuditLogService = Depends(get_audit_log_service),
):
    """
    Called by: console. Full chronological history for one specific
    record — e.g. every change ever made to one Registration or one
    Event, in order.
    """
    return await service.get_history_for_entity(entity_type, uuid.UUID(entity_id))