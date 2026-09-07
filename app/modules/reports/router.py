"""
Reporting endpoints for both consoles.

/reports/operations and /reports/financial are platform-wide, so they
use require_role (global roles only, correctly — no event_id in
either path). /reports/events/{event_id} is scoped and correctly has
event_id in its path, so require_scoped_role is used safely here
(unlike the five routes fixed elsewhere in this audit).
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role, require_scoped_role
from app.core.permissions import user_has_global_role, user_scoped_event_ids
from app.exceptions import PermissionDeniedError
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.reports.schemas import (
    EventFinancialReportOut,
    EventOperationsReportOut,
    EventSummaryReportOut,
    PlatformFinancialReportOut,
    PlatformOperationsReportOut,
    OperationsCommandCenterOut,
    AttendanceParticipantPageOut,
    AttendanceHistoryPageOut,
    EventAttendanceReportOut,
)
from app.modules.reports.service import ReportService
from app.modules.reports.analytics_service import AnalyticsService
from app.modules.reports.schemas import EventAnalyticsComparisonOut, EventAnalyticsOut, EventAnalyticsTimeSeriesOut
from app.modules.events.schemas import EventOperationsOverviewOut

router = APIRouter(prefix="/reports", tags=["reports"])


def get_report_service(db: AsyncSession = Depends(get_db)) -> ReportService:
    return ReportService(db)


def get_analytics_service(db: AsyncSession = Depends(get_db)) -> AnalyticsService:
    return AnalyticsService(db)


async def _require_analytics_access(event_id: uuid.UUID, current_user: User, db: AsyncSession) -> bool:
    allowed = await user_has_global_role(db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN, RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR}) or await user_has_scoped_role(db, current_user.id, {RoleName.EVENT_MANAGER}, event_id, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})
    if not allowed:
        raise PermissionDeniedError("You don't have permission to view analytics for this event.")
    return await user_has_global_role(db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR})


@router.get("/analytics/events/{event_id}", response_model=EventAnalyticsOut)
async def get_event_analytics(event_id: uuid.UUID, start: datetime | None = None, end: datetime | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: AnalyticsService = Depends(get_analytics_service)):
    include_financial = await _require_analytics_access(event_id, current_user, db)
    return await service.overview(event_id, start=start, end=end, include_financial=include_financial)


@router.get("/analytics/events/{event_id}/timeseries", response_model=EventAnalyticsTimeSeriesOut)
async def get_event_analytics_timeseries(event_id: uuid.UUID, start: datetime | None = None, end: datetime | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: AnalyticsService = Depends(get_analytics_service)):
    await _require_analytics_access(event_id, current_user, db)
    return await service.timeseries(event_id, start=start, end=end)


@router.get("/analytics/events/{event_id}/comparison", response_model=EventAnalyticsComparisonOut)
async def get_event_analytics_comparison(event_id: uuid.UUID, start: datetime | None = None, end: datetime | None = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: AnalyticsService = Depends(get_analytics_service)):
    include_financial = await _require_analytics_access(event_id, current_user, db)
    return await service.comparison(event_id, start=start, end=end, include_financial=include_financial)


@router.get(
    "/operations/command-center",
    response_model=OperationsCommandCenterOut,
)
async def get_operations_command_center(
    event_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ReportService = Depends(get_report_service),
):
    """Read-only operational snapshot scoped to the caller's events."""
    is_global = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    event_ids = None if is_global else await user_scoped_event_ids(
        db, current_user.id, {RoleName.EVENT_MANAGER}
    )
    if not is_global and not event_ids:
        raise PermissionDeniedError("You don't have permission to view operations.")
    return await service.get_command_center(
        event_ids=event_ids, event_id=event_id, search=search,
        page=page, page_size=page_size,
    )


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


async def _require_attendance_access(event_id: uuid.UUID, current_user: User, db: AsyncSession) -> None:
    allowed = await user_has_global_role(db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}) or await user_has_scoped_role(
        db, current_user.id, {RoleName.EVENT_MANAGER}, event_id,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not allowed:
        raise PermissionDeniedError("You don't have permission to view attendance for this event.")


@router.get("/events/{event_id}/attendance", response_model=EventAttendanceReportOut)
async def get_event_attendance_report(
    event_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ReportService = Depends(get_report_service),
):
    await _require_attendance_access(event_id, current_user, db)
    return await service.get_event_attendance_report(event_id)


@router.get("/events/{event_id}/attendance/participants", response_model=AttendanceParticipantPageOut)
async def get_event_attendance_participants(
    event_id: uuid.UUID,
    search: str | None = Query(None, max_length=100),
    attendance: str | None = Query(None, pattern="^(attended|no_show)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: ReportService = Depends(get_report_service),
):
    await _require_attendance_access(event_id, current_user, db)
    return await service.page_event_attendance_participants(event_id, page=page, page_size=page_size, search=search, attendance=attendance)


@router.get("/attendance/mine", response_model=AttendanceHistoryPageOut)
async def get_my_attendance_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: ReportService = Depends(get_report_service),
):
    """User-scoped attendance history; never accepts another user's ID."""
    return await service.page_my_attendance_history(current_user.id, page=page, page_size=page_size)
