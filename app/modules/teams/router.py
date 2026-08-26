"""
Team endpoints for mobile captains and console reviewers.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, require_role, require_scoped_role
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.teams.schemas import (
    TeamCreateIn,
    TeamInvitationIn,
    TeamInvitationOut,
    TeamInvitationResponseIn,
    TeamOut,
)
from app.modules.teams.service import TeamService

router = APIRouter(prefix="/teams", tags=["teams"])


def get_team_service(db: AsyncSession = Depends(get_db)) -> TeamService:
    return TeamService(db)


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
async def create_team(
    payload: TeamCreateIn,
    event_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    return await service.create_team(
        uuid.UUID(event_id), current_user, payload.name, payload.captain_date_of_birth
    )


@router.post(
    "/{team_id}/invitations",
    response_model=TeamInvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    team_id: str,
    payload: TeamInvitationIn,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    return await service.invite_member(uuid.UUID(team_id), current_user, payload.invitee_mobile)


@router.post("/{team_id}/invitations/{invite_id}/respond", response_model=TeamInvitationOut)
async def respond_to_invitation(
    team_id: str,
    invite_id: str,
    payload: TeamInvitationResponseIn,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    return await service.respond_to_invitation(
        uuid.UUID(team_id), uuid.UUID(invite_id), current_user, payload.accept
    )


@router.post("/{team_id}/submit", response_model=TeamOut)
async def submit_team(
    team_id: str,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    return await service.submit_team(uuid.UUID(team_id), current_user)


@router.get("", response_model=list[TeamOut])
async def list_teams(
    event_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: TeamService = Depends(get_team_service),
):
    if event_id is None:
        return []
    return await service.list_teams(uuid.UUID(event_id))


@router.post(
    "/{team_id}/approve",
    response_model=TeamOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def approve_team(
    team_id: str,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    return await service.approve_team(uuid.UUID(team_id), current_user)
