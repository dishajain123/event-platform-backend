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
from app.modules.tickets.schemas import CheckInIn, CheckInOut, OfflineCheckInBatchIn, TicketOut
from app.modules.tickets.service import TicketService

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
    Coordinator/Event Manager scanning a QR ticket at the gate). See the
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


@checkins_router.get("/check-ins", response_model=list[CheckInOut])
async def list_checkins(
    event_id: str = Query(...),
    venue_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: TicketService = Depends(get_ticket_service),
):
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
    return await service.list_checkins(event_uuid, uuid.UUID(venue_id) if venue_id else None)


@checkins_router.post("/check-ins/sync", response_model=list[CheckInOut])
async def sync_offline_checkins(
    payload: OfflineCheckInBatchIn,
    current_user: User = Depends(get_current_user),
    service: TicketService = Depends(get_ticket_service),
):
    return await service.sync_offline_checkins(current_user, payload.scans)