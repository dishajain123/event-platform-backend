"""Funnel endpoints for event stage configuration and entry control."""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PermissionDeniedError
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.database import get_db
from app.dependencies import get_current_user, require_scoped_role
from app.modules.funnels.schemas import CompetitionStageIn, CompetitionStageOut, EntryOut, StageDecisionIn
from app.modules.funnels.service import FunnelService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName

router = APIRouter(tags=["funnels"])


def get_funnel_service(db: AsyncSession = Depends(get_db)) -> FunnelService:
    return FunnelService(db)


@router.get("/events/{event_id}/stages", response_model=list[CompetitionStageOut])
async def list_stages(
    event_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FunnelService = Depends(get_funnel_service),
):
    return await service.list_stages(uuid.UUID(event_id))


@router.post(
    "/events/{event_id}/stages",
    response_model=CompetitionStageOut,
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
async def create_stage(
    event_id: str,
    payload: CompetitionStageIn,
    service: FunnelService = Depends(get_funnel_service),
):
    return await service.create_stage(uuid.UUID(event_id), **payload.model_dump())


@router.get("/entries", response_model=list[EntryOut])
async def list_entries(
    stage_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FunnelService = Depends(get_funnel_service),
):
    stage = await service._get_stage_or_raise(uuid.UUID(stage_id))
    is_allowed = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    ) or await user_has_scoped_role(
        db,
        current_user.id,
        {RoleName.EVENT_MANAGER},
        stage.event_id,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not is_allowed:
        raise PermissionDeniedError("You don't have permission to view entries for this stage.")
    return await service.list_entries(stage.id)


@router.post("/entries/{entry_id}/advance", response_model=EntryOut)
async def advance_entry(
    entry_id: str,
    payload: StageDecisionIn,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FunnelService = Depends(get_funnel_service),
):
    entry = await service._get_entry_or_raise(uuid.UUID(entry_id))
    is_allowed = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    ) or await user_has_scoped_role(
        db,
        current_user.id,
        {RoleName.EVENT_MANAGER},
        entry.event_id,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not is_allowed:
        raise PermissionDeniedError("You don't have permission to advance this entry.")
    return await service.advance_entry(
        uuid.UUID(entry_id), current_user, payload.decision, payload.score, payload.notes
    )


@router.post("/entries/{entry_id}/vote", response_model=EntryOut)
async def vote_entry(
    entry_id: str,
    current_user: User = Depends(get_current_user),
    service: FunnelService = Depends(get_funnel_service),
):
    return await service.vote_entry(uuid.UUID(entry_id), current_user)
