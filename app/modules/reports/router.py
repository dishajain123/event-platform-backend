"""
Reporting endpoints for both consoles.

/reports/operations and /reports/financial are platform-wide, so they
use require_role (global roles only, correctly — no event_id in
either path). /reports/events/{event_id} is scoped and correctly has
event_id in its path, so require_scoped_role is used safely here
(unlike the five routes fixed elsewhere in this audit).
"""
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_role, require_scoped_role
from app.modules.rbac.models import RoleName
from app.modules.reports.schemas import (
    EventFinancialReportOut,
    EventOperationsReportOut,
    EventSummaryReportOut,
    PlatformFinancialReportOut,
    PlatformOperationsReportOut,
)
from app.modules.reports.service import ReportService
from app.modules.events.schemas import EventOperationsOverviewOut

router = APIRouter(prefix="/reports", tags=["reports"])


def get_report_service(db: AsyncSession = Depends(get_db)) -> ReportService:
    return ReportService(db)


@router.get(
    "/operations",
    response_model=PlatformOperationsReportOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def get_platform_operations_report(service: ReportService = Depends(get_report_service)):
    """Called by: console (Operations Admin / Super Admin) — platform-wide dashboard."""
    return await service.get_platform_operations_report()


@router.get(
    "/overview",
    response_model=EventOperationsOverviewOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def get_platform_operations_overview(service: ReportService = Depends(get_report_service)):
    """Called by: console (Operations Admin / Super Admin) — the main operations dashboard."""
    return await service.get_platform_operations_overview()


@router.get(
    "/operations/{event_id}",
    response_model=EventOperationsReportOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def get_event_operations_report(
    event_id: str, service: ReportService = Depends(get_report_service)
):
    """Called by: console (Operations Admin / Super Admin) — single-event drill-down."""
    return await service.get_event_operations_report(uuid.UUID(event_id))


@router.get(
    "/financial",
    response_model=PlatformFinancialReportOut,
    dependencies=[
        Depends(
            require_role(
                RoleName.FINANCE_ADMIN,
                RoleName.FINANCE_OPERATOR,
                RoleName.FINANCE_AUDITOR,
                RoleName.SUPER_ADMIN,
            )
        )
    ],
)
async def get_platform_financial_report(service: ReportService = Depends(get_report_service)):
    """Called by: console (Finance roles) — platform-wide revenue dashboard."""
    return await service.get_platform_financial_report()


@router.get(
    "/financial/{event_id}",
    response_model=EventFinancialReportOut,
    dependencies=[
        Depends(
            require_role(
                RoleName.FINANCE_ADMIN,
                RoleName.FINANCE_OPERATOR,
                RoleName.FINANCE_AUDITOR,
                RoleName.SUPER_ADMIN,
            )
        )
    ],
)
async def get_event_financial_report(
    event_id: str, service: ReportService = Depends(get_report_service)
):
    """Called by: console (Finance roles) — single-event revenue drill-down."""
    return await service.get_event_financial_report(uuid.UUID(event_id))


@router.get(
    "/events/{event_id}",
    response_model=EventSummaryReportOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def get_event_summary_for_manager(
    event_id: str, service: ReportService = Depends(get_report_service)
):
    """
    Called by: console (scoped Event Manager login, config+reports only —
    see the platform's account model) or mobile Staff Mode "My Event
    Reports" screen. Returns operational numbers plus revenue collected,
    but not the full financial breakdown Finance roles see.
    """
    return await service.get_event_summary_for_manager(uuid.UUID(event_id))
