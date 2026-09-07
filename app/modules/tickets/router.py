"""
Ticket endpoints and check-in dashboard endpoints.

Note on /check-in: does NOT use the require_scoped_role router
dependency — the route only has ticket_id in its path, and the
ticket's event_id isn't known until the ticket is loaded from the
database. Authorization is enforced inside TicketService.check_in()
via can_access_ticket(), which already checks the caller's scope
correctly (ticket owner, OR any Staff Mode role scoped to that
ticket's event, OR global console admin).
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.tickets.models import CheckInSource
from app.modules.tickets.schemas import CheckInIn, CheckInOut, OfflineCheckInBatchIn, ResolveTicketIn, TicketOut
from app.modules.tickets.service import TicketService
from app.core.pagination import Page

router = APIRouter(prefix="/tickets", tags=["tickets"])
checkins_router = APIRouter(tags=["tickets"])


def get_ticket_service(db: AsyncSession = Depends(get_db)) -> TicketService:
    return TicketService(db)


@router.get("/mine", response_model=list[TicketOut])
async def list_my_tickets(
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    return await service.list_my_tickets(current_user)


@router.post("/resolve", response_model=TicketOut)
async def resolve_ticket_by_scan(
    payload: ResolveTicketIn,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    """
    Called by: mobile Staff Mode's barcode scanner, immediately after every
    scan — resolves a scanned barcode payload into the real ticket (and its
    UUID `id`) that POST /{ticket_id}/check-in requires. Declared before
    GET /{ticket_id} below so the literal "/resolve" path is never
    swallowed by the parameterized route.
    """
    ticket = await service.resolve_by_scan_payload(payload.scan_payload, payload.barcode_signature)
    if not await service.can_check_in_ticket(ticket, current_user):
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You don't have permission to check in this ticket.")
    return ticket


@router.get("/by-code/{ticket_code}", response_model=TicketOut)
async def resolve_ticket_by_code(
    ticket_code: str,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    """
    Called by: mobile Staff Mode's manual-entry fallback, for a
    damaged/unreadable barcode. Declared before
    GET /{ticket_id} so "/by-code/..." is never swallowed by the
    parameterized route.
    """
    ticket = await service.resolve_by_ticket_code(ticket_code, current_user)
    if not await service.can_check_in_ticket(ticket, current_user):
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You don't have permission to check in this ticket.")
    return ticket


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(
    ticket_id: str,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    ticket = await service.get_ticket_or_raise(uuid.UUID(ticket_id))
    if not await service.can_access_ticket(ticket, current_user):
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You don't have permission to view this ticket.")
    return ticket


@router.post(
    "/{ticket_id}/check-in",
    response_model=CheckInOut,
    status_code=status.HTTP_201_CREATED,
)
async def check_in_ticket(
    ticket_id: str,
    payload: CheckInIn,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    """
    Called by: mobile Staff Mode (Volunteer/Staff Member/Staff Lead/Event
    Coordinator/Event Manager scanning a barcode ticket at the gate). See the
    module docstring above for why this isn't a require_scoped_role dependency.
    """
    return await service.check_in(
        uuid.UUID(ticket_id),
        current_user,
        venue_id=payload.venue_id,
        offline_batch_id=payload.offline_batch_id,
        scan_payload=payload.scan_payload,
        source=CheckInSource.ONLINE,
    )


@checkins_router.get("/check-ins", response_model=list[CheckInOut] | Page[CheckInOut])
async def list_checkins(
    event_id: str = Query(...),
    venue_id: str | None = None,
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: TicketService = Depends(get_ticket_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    event_uuid = uuid.UUID(event_id)
    is_allowed = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    ) or await user_has_scoped_role(
        db,
        current_user.id,
        {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER},
        event_uuid,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not is_allowed:
        from app.exceptions import PermissionDeniedError

        raise PermissionDeniedError("You don't have permission to view check-ins for this event.")
    if page is None:
        return await service.list_checkins(event_uuid, uuid.UUID(venue_id) if venue_id else None)
    items, total = await service.page_checkins(event_uuid, uuid.UUID(venue_id) if venue_id else None, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@checkins_router.post("/check-ins/sync", response_model=list[CheckInOut])
async def sync_offline_checkins(
    payload: OfflineCheckInBatchIn,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    return await service.sync_offline_checkins(current_user, payload.scans)
