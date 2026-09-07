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
from app.dependencies import get_current_user, get_current_user_optional, require_role, require_scoped_role
from app.modules.events.schemas import (
    EventCreateIn,
    EventOut,
    EventStatusChangeIn,
    EventUpdateIn,
    EventDuplicateIn,
    EventTemplateCreateIn,
    EventTemplateUpdateIn,
    EventTemplateOut,
    EventTemplatePage,
    ScheduleItemIn,
    ScheduleItemUpdateIn,
    ScheduleItemOut,
    SponsorIn,
    SponsorOut,
    VenueIn,
    VenueOut,
)
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.core.pagination import Page

router = APIRouter(prefix="/events", tags=["events"])


def get_event_service(db: AsyncSession = Depends(get_db)) -> EventService:
    return EventService(db)


@router.get("", response_model=list[EventOut] | Page[EventOut])
async def list_events(
    main_category_id: uuid.UUID | None = None,
    sub_category_id: uuid.UUID | None = None,
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    event_status: EventStatus | None = Query(None, alias="status"),
    current_user: User | None = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
    service: EventService = Depends(get_event_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    """
    Called by: both. Mobile users see only PUBLISHED-or-later events;
    console users with Operations Admin/Super Admin see every status.
    """
    is_console_admin = current_user is not None and await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    if page is None:
        events = await service.list_events(
        include_all_statuses=is_console_admin,
        main_category_id=main_category_id,
        sub_category_id=sub_category_id,
        )
        return [await service.to_response(event) for event in events]
    events, total = await service.page_events(include_all_statuses=is_console_admin, main_category_id=main_category_id, sub_category_id=sub_category_id, search=search, status=event_status, page=page, page_size=page_size)
    return Page(items=[await service.to_response(event) for event in events], total=total, page=page, page_size=page_size)


@router.get("/templates", response_model=EventTemplatePage)
async def list_event_templates(
    search: str | None = Query(None, max_length=100),
    include_archived: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: EventService = Depends(get_event_service),
):
    items, total = await service.list_templates(current_user, search=search, include_archived=include_archived, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/templates", response_model=EventTemplateOut, status_code=status.HTTP_201_CREATED)
async def create_event_template(payload: EventTemplateCreateIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service.create_template(current_user, **payload.model_dump())


@router.get("/templates/{template_id}", response_model=EventTemplateOut)
async def get_event_template(template_id: uuid.UUID, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service._get_visible_template(current_user, template_id)


@router.patch("/templates/{template_id}", response_model=EventTemplateOut)
async def update_event_template(template_id: uuid.UUID, payload: EventTemplateUpdateIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service.update_template(current_user, template_id, **payload.model_dump(exclude_unset=True))


@router.post("/templates/{template_id}/archive", response_model=EventTemplateOut)
async def archive_event_template(template_id: uuid.UUID, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service.archive_template(current_user, template_id)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_template(template_id: uuid.UUID, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    await service.delete_template(current_user, template_id)


@router.post("/templates/{template_id}/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_event_from_template(template_id: uuid.UUID, payload: EventDuplicateIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    event = await service.create_event_from_template(current_user, template_id, **payload.model_dump())
    return await service.to_response(event)


@router.post("/{event_id}/duplicate", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def duplicate_event(event_id: uuid.UUID, payload: EventDuplicateIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    event = await service.duplicate_event(current_user, event_id, **payload.model_dump())
    return await service.to_response(event)


@router.get("/{event_id}", response_model=EventOut)
async def get_event(
    event_id: uuid.UUID,
    current_user: User | None = Depends(get_current_user_optional),
    service: EventService = Depends(get_event_service),
):
    """Called by: console event detail pages."""
    event = await service.get_event_visible_to_actor(event_id, current_user)
    return await service.to_response(event)


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
    event = await service.create_event(created_by=current_user.id, **payload.model_dump())
    return await service.to_response(event)


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
    event = await service.update_event(
        uuid.UUID(event_id), current_user.id, **payload.model_dump(exclude_unset=True)
    )
    return await service.to_response(event)


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
    event = await service.publish(uuid.UUID(event_id), current_user.id)
    return await service.to_response(event)


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
    event = await service.transition_status(uuid.UUID(event_id), payload.new_status, current_user.id)
    return await service.to_response(event)


@router.post(
    "/{event_id}/venues",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def add_venue(
    event_id: uuid.UUID, payload: VenueIn, service: EventService = Depends(get_event_service)
):
    """Called by: console."""
    return await service.add_venue(event_id, **payload.model_dump())


@router.put(
    "/{event_id}/venues/{venue_id}", response_model=VenueOut,
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def update_venue(event_id: uuid.UUID, venue_id: uuid.UUID, payload: VenueIn, service: EventService = Depends(get_event_service)):
    return await service.update_venue(event_id, venue_id, **payload.model_dump())


@router.get("/{event_id}/venues", response_model=list[VenueOut])
async def list_venues(
    event_id: uuid.UUID,
    current_user: User | None = Depends(get_current_user_optional),
    service: EventService = Depends(get_event_service),
):
    """Called by: both."""
    await service.get_event_visible_to_actor(event_id, current_user)
    return await service.list_venues(event_id)


@router.get(
    "/{event_id}/venues/assignable", response_model=list[VenueOut],
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def list_assignable_venues(event_id: uuid.UUID, service: EventService = Depends(get_event_service)):
    return await service.list_assignable_venues(event_id)


@router.post(
    "/{event_id}/schedule",
    response_model=ScheduleItemOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def add_schedule_item(
    event_id: uuid.UUID, payload: ScheduleItemIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)
):
    """Called by: console."""
    return await service.add_schedule_item(event_id, actor_user_id=current_user.id, **payload.model_dump())


@router.get(
    "/{event_id}/schedule/manage", response_model=Page[ScheduleItemOut],
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def manage_schedule(
    event_id: uuid.UUID, status_filter: str | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), service: EventService = Depends(get_event_service)
):
    items, total = await service.schedule.page_for_event(event_id, page=page, page_size=page_size, status=status_filter, search=search)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.put(
    "/{event_id}/schedule/{schedule_id}", response_model=ScheduleItemOut,
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def update_schedule_item(event_id: uuid.UUID, schedule_id: uuid.UUID, payload: ScheduleItemUpdateIn, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service.update_schedule_item(event_id, schedule_id, actor_user_id=current_user.id, **payload.model_dump(exclude_unset=True))


@router.post(
    "/{event_id}/schedule/{schedule_id}/cancel", response_model=ScheduleItemOut,
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def cancel_schedule_item(event_id: uuid.UUID, schedule_id: uuid.UUID, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    return await service.cancel_schedule_item(event_id, schedule_id, actor_user_id=current_user.id)


@router.delete(
    "/{event_id}/schedule/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scoped_role(RoleName.EVENT_MANAGER, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}))],
)
async def delete_schedule_item(event_id: uuid.UUID, schedule_id: uuid.UUID, current_user: User = Depends(get_current_user), service: EventService = Depends(get_event_service)):
    await service.delete_schedule_item(event_id, schedule_id, actor_user_id=current_user.id)


@router.get("/{event_id}/schedule", response_model=list[ScheduleItemOut])
async def get_schedule(
    event_id: uuid.UUID,
    current_user: User | None = Depends(get_current_user_optional),
    service: EventService = Depends(get_event_service),
):
    """Called by: both."""
    await service.get_event_visible_to_actor(event_id, current_user)
    return await service.list_schedule(event_id)


@router.get("/{event_id}/sponsors", response_model=list[SponsorOut])
async def list_sponsors(
    event_id: uuid.UUID,
    current_user: User | None = Depends(get_current_user_optional),
    service: EventService = Depends(get_event_service),
):
    """Called by: console sponsor management screens."""
    await service.get_event_visible_to_actor(event_id, current_user)
    return await service.list_sponsors(event_id)


@router.post(
    "/{event_id}/sponsors",
    response_model=SponsorOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_scoped_role(
        RoleName.EVENT_MANAGER,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    ))],
)
async def add_sponsor(
    event_id: uuid.UUID,
    payload: SponsorIn,
    service: EventService = Depends(get_event_service),
):
    """Called by: console."""
    return await service.add_sponsor(event_id, **payload.model_dump())


@router.delete(
    "/{event_id}/sponsors/{sponsor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_scoped_role(
        RoleName.EVENT_MANAGER,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    ))],
)
async def delete_sponsor(
    event_id: uuid.UUID,
    sponsor_id: uuid.UUID,
    service: EventService = Depends(get_event_service),
):
    """Called by: console."""
    await service.delete_sponsor(event_id, sponsor_id)
