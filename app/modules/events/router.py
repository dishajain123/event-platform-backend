"""
Event endpoints. GET /events is shared by both clients with different
result scoping (public/published-only for mobile, everything for
console) — see the include_all_statuses query param, gated by role.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, require_role, require_scoped_role
from app.modules.events.schemas import (
    EventCreateIn,
    EventOut,
    EventStatusChangeIn,
    EventUpdateIn,
    ScheduleItemIn,
    ScheduleItemOut,
    VenueIn,
    VenueOut,
)
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/events", tags=["events"])


def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    return EventService(db)


@router.get("", response_model=list[EventOut])
async def list_events(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: EventService = Depends(get_event_service),
):
    """
    Called by: both. Mobile users see only PUBLISHED-or-later events;
    console users with Operations Admin/Super Admin see every status.
    """
    is_console_admin = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    return await service.list_events(include_all_statuses=is_console_admin)


@router.post(
    "",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def create_event(
    payload: EventCreateIn,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    """Called by: console (Operations Admin)."""
    return await service.create_event(created_by=current_user.id, **payload.model_dump())


@router.patch("/{event_id}", response_model=EventOut)
async def update_event(
    event_id: str,
    payload: EventUpdateIn,
    current_user: User = Depends(
        require_scoped_role(
            RoleName.EVENT_MANAGER,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )
    ),
    service: EventService = Depends(get_event_service),
):
    """Called by: console — Operations Admin (any event) or a scoped Event
    Manager (their own event only, enforced by require_scoped_role)."""
    return await service.update_event(
        uuid.UUID(event_id), current_user.id, **payload.model_dump(exclude_unset=True)
    )


@router.post(
    "/{event_id}/publish",
    response_model=EventOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def publish_event(
    event_id: str,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    """Called by: console (Operations Admin only) — deliberately not delegated
    to Event Manager, publishing is a platform-level decision."""
    return await service.publish(uuid.UUID(event_id), current_user.id)


@router.post(
    "/{event_id}/status",
    response_model=EventOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def change_event_status(
    event_id: str,
    payload: EventStatusChangeIn,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    """Called by: console (Operations Admin). Any transition not allowed by
    ALLOWED_TRANSITIONS is rejected with a 422, not silently applied."""
    return await service.transition_status(uuid.UUID(event_id), payload.new_status, current_user.id)


@router.post(
    "/{event_id}/venues",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def add_venue(
    event_id: str, payload: VenueIn, service: EventService = Depends(get_event_service)
):
    """Called by: console."""
    return await service.add_venue(uuid.UUID(event_id), **payload.model_dump())


@router.get("/{event_id}/venues", response_model=list[VenueOut])
async def list_venues(
    event_id: str,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    """Called by: both."""
    return await service.list_venues(uuid.UUID(event_id))


@router.post(
    "/{event_id}/schedule",
    response_model=ScheduleItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def add_schedule_item(
    event_id: str, payload: ScheduleItemIn, service: EventService = Depends(get_event_service)
):
    """Called by: console."""
    return await service.add_schedule_item(uuid.UUID(event_id), **payload.model_dump())


@router.get("/{event_id}/schedule", response_model=list[ScheduleItemOut])
async def get_schedule(
    event_id: str,
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    """Called by: both."""
    return await service.list_schedule(uuid.UUID(event_id))