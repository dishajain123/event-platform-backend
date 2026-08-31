"""
Registration endpoints. Mobile users create and list their own
registrations; Console roles can list and decide over scoped events.

Note on approve/reject: these do NOT use the require_scoped_role
router dependency, because that dependency reads event_id from the
URL PATH — and these routes are keyed by registration_id, not
event_id (the event isn't known until the registration is loaded from
the database). Authorization is instead enforced inside
RegistrationService.decide_registration() -> can_manage_registration(),
which loads the registration first and then checks the caller's scope
against its actual event_id. Applying require_scoped_role here would
look correct but silently reject every caller, since request.path_params
would never contain "event_id" on this route.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PermissionDeniedError
from app.core.permissions import user_has_global_role
from app.core.permissions import user_has_scoped_role
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.registrations.schemas import (
    RegistrationCreateIn,
    RegistrationDecisionIn,
    RegistrationOut,
)
from app.modules.registrations.service import RegistrationService

router = APIRouter(prefix="/registrations", tags=["registrations"])


def get_registration_service(db: AsyncSession = Depends(get_db)) -> RegistrationService:
    return RegistrationService(db)


@router.post("", response_model=RegistrationOut, status_code=status.HTTP_201_CREATED)
async def create_registration(
    payload: RegistrationCreateIn,
    event_id: str = Query(..., description="Event to register for"),
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.create_registration(
        event_id=uuid.UUID(event_id),
        actor=current_user,
        participation_type=payload.participation_type,
        date_of_birth=payload.date_of_birth,
        child_id=payload.child_id,
        team_id=payload.team_id,
        documents_provided=payload.documents_provided,
        answers=payload.answers,
        participants=[p.model_dump() for p in payload.participants],
        team_member_count=payload.team_member_count,
    )


@router.get("/mine", response_model=list[RegistrationOut])
async def list_my_registrations(
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.list_registrations_for_actor(current_user)


@router.get("", response_model=list[RegistrationOut])
async def list_registrations(
    event_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: RegistrationService = Depends(get_registration_service),
):
    is_global_console = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    if is_global_console:
        if event_id:
            return await service.list_registrations_for_event(event_id)
        return await service.list_all_registrations()
    if event_id is None:
        return await service.list_registrations_for_actor(current_user)
    is_event_manager = await user_has_scoped_role(
        db,
        current_user.id,
        {RoleName.EVENT_MANAGER},
        event_id,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not is_event_manager:
        raise PermissionDeniedError("You don't have permission to view registrations for this event.")
    return await service.list_registrations_for_event(event_id)


@router.get("/{registration_id}", response_model=RegistrationOut)
async def get_registration(
    registration_id: str,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.get_registration_visible_to_actor(current_user, uuid.UUID(registration_id))


@router.post("/{registration_id}/approve", response_model=RegistrationOut)
async def approve_registration(
    registration_id: str,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    """
    Called by: console (Operations Admin / scoped Event Manager), or a
    scoped Event Manager's mobile Staff Mode. Authorization is enforced
    inside the service — see the module docstring above for why this
    can't be a router-level require_scoped_role dependency.
    """
    return await service.decide_registration(uuid.UUID(registration_id), current_user, True)


@router.post("/{registration_id}/reject", response_model=RegistrationOut)
async def reject_registration(
    registration_id: str,
    payload: RegistrationDecisionIn,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    """Called by: console / scoped mobile Staff Mode. See approve_registration docstring."""
    return await service.decide_registration(
        uuid.UUID(registration_id), current_user, False, payload.reason
    )
