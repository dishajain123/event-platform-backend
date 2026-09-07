"""
Team endpoints for mobile captains and console reviewers.

Note on /approve: does NOT use the require_scoped_role router
dependency (event_id isn't in this route's path — only team_id is,
and the team's event_id isn't known until it's loaded from the
database). Authorization is enforced inside TeamService.approve_team(),
which already checks the caller's scope correctly against the team's
actual event_id.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PermissionDeniedError
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.teams.schemas import (
    TeamCreateIn,
    TeamInvitationIn,
    TeamInvitationOut,
    TeamManagerIn,
    TeamInvitationResponseIn,
    TeamMemberOut,
    TeamMemberRoleIn,
    TeamJoinRequestOut,
    TeamOut,
)
from app.modules.teams.service import TeamService
from app.core.pagination import Page

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


@router.get("", response_model=list[TeamOut] | Page[TeamOut])
async def list_teams(
    event_id: uuid.UUID | None = None,
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: TeamService = Depends(get_team_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    if event_id is None:
        if await user_has_global_role(db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            if page is None:
                return await service.list_teams_for_events(None)
            items, total = await service.page_teams_for_events(None, page=page, page_size=page_size)
            return Page(items=items, total=total, page=page, page_size=page_size)
        assigned_ids = await user_scoped_event_ids(db, current_user.id, {RoleName.EVENT_MANAGER})
        if page is None:
            return await service.list_teams_for_events(assigned_ids)
        items, total = await service.page_teams_for_events(assigned_ids, page=page, page_size=page_size)
        return Page(items=items, total=total, page=page, page_size=page_size)
    is_global_console = await user_has_global_role(
        db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
    )
    is_event_manager = await user_has_scoped_role(
        db,
        current_user.id,
        {RoleName.EVENT_MANAGER},
        event_id,
        allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
    )
    if not is_global_console and not is_event_manager:
        raise PermissionDeniedError("You don't have permission to view teams for this event.")
    if page is None:
        return await service.list_teams(event_id)
    items, total = await service.page_teams(event_id, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/mine", response_model=list[TeamOut])
async def list_my_teams(current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.list_my_teams(current_user)


@router.get("/invitations/mine", response_model=list[TeamInvitationOut])
async def list_my_invitations(current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.list_my_invitations(current_user)


@router.get("/{team_id}", response_model=TeamOut)
async def get_team(
    team_id: str,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    """
    Called by: mobile (a team's captain or an accepted/invited member
    checking on their own team — see get_team_visible_to_actor for why
    this endpoint exists at all), and console/Event Manager. Closes a
    real gap: previously the only way to see team state was the
    create/submit response at that one moment — a captain reopening the
    app had no way to check on their team at all.
    """
    return await service.get_team_visible_to_actor(uuid.UUID(team_id), current_user)


@router.get("/{team_id}/members", response_model=list[TeamMemberOut])
async def list_team_members(
    team_id: str,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    """Called by: mobile (Team Roster screen) and console/Event Manager."""
    return await service.list_members_visible_to_actor(uuid.UUID(team_id), current_user)


@router.post("/{team_id}/approve", response_model=TeamOut)
async def approve_team(
    team_id: str,
    current_user: User = Depends(get_current_user),
    service: TeamService = Depends(get_team_service),
):
    """Called by: console / scoped mobile Staff Mode (Event Manager). See
    module docstring above for why this isn't a require_scoped_role dependency."""
    return await service.approve_team(uuid.UUID(team_id), current_user)


@router.post("/{team_id}/join-requests", response_model=TeamJoinRequestOut, status_code=status.HTTP_201_CREATED)
async def request_to_join_team(team_id: str, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.request_to_join(uuid.UUID(team_id), current_user)


@router.get("/{team_id}/join-requests", response_model=list[TeamJoinRequestOut])
async def list_join_requests(team_id: str, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.list_join_requests_visible_to_actor(uuid.UUID(team_id), current_user)


@router.post("/{team_id}/join-requests/{request_id}/respond", response_model=TeamJoinRequestOut)
async def respond_to_join_request(team_id: str, request_id: str, payload: TeamInvitationResponseIn, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.respond_to_join_request(uuid.UUID(team_id), uuid.UUID(request_id), current_user, payload.accept)


@router.post("/{team_id}/members/{member_id}/remove", response_model=TeamMemberOut)
async def remove_team_member(team_id: str, member_id: str, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.remove_member(uuid.UUID(team_id), uuid.UUID(member_id), current_user)


@router.post("/{team_id}/members/{member_id}/role", response_model=TeamMemberOut)
async def set_team_member_role(team_id: str, member_id: str, payload: TeamMemberRoleIn, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.set_member_role(uuid.UUID(team_id), uuid.UUID(member_id), payload.role, current_user)


@router.post("/{team_id}/leave")
async def leave_team(team_id: str, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.leave_team(uuid.UUID(team_id), current_user)


@router.post("/{team_id}/manager", response_model=TeamOut)
async def assign_team_manager(team_id: str, payload: TeamManagerIn, current_user: User = Depends(get_current_user), service: TeamService = Depends(get_team_service)):
    return await service.assign_manager(uuid.UUID(team_id), payload.user_id, current_user)
