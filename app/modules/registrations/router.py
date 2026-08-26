"""
Registration endpoints. Mobile users create and list their own
registrations; Console roles can list and decide over scoped events.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, require_role, require_scoped_role
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
    event_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: RegistrationService = Depends(get_registration_service),
):
    is_global_console = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    if is_global_console:
        if event_id:
            return await service.list_registrations_for_event(uuid.UUID(event_id))
        return await service.list_all_registrations()
    if event_id is None:
        return await service.list_registrations_for_actor(current_user)
    return await service.list_registrations_for_event(uuid.UUID(event_id))


@router.get("/{registration_id}", response_model=RegistrationOut)
async def get_registration(
    registration_id: str,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.get_registration_visible_to_actor(current_user, uuid.UUID(registration_id))


@router.post(
    "/{registration_id}/approve",
    response_model=RegistrationOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def approve_registration(
    registration_id: str,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.decide_registration(uuid.UUID(registration_id), current_user, True)


@router.post(
    "/{registration_id}/reject",
    response_model=RegistrationOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def reject_registration(
    registration_id: str,
    payload: RegistrationDecisionIn,
    current_user: User = Depends(get_current_user),
    service: RegistrationService = Depends(get_registration_service),
):
    return await service.decide_registration(
        uuid.UUID(registration_id), current_user, False, payload.reason
    )
