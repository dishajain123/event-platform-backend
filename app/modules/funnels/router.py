"""Funnel endpoints for event stage configuration and entry control."""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PermissionDeniedError
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.database import get_db
from app.dependencies import get_current_user, get_current_user_optional, require_scoped_role
from app.modules.funnels.models import CompetitionStatus, MatchResultStatus, MatchStatus
from app.modules.funnels.schemas import CompetitionIn, CompetitionOut, CompetitionStageIn, CompetitionStageOut, CompetitionStatusIn, CompetitionUpdateIn, EntryOut, MatchIn, MatchOut, MatchResultIn, StageDecisionIn, StandingsOut
from app.modules.funnels.service import FunnelService
from app.modules.identity.models import User
from app.modules.registrations.models import Registration
from app.modules.rbac.models import RoleName
from app.core.pagination import Page

router = APIRouter(tags=["funnels"])


def get_funnel_service(db: AsyncSession = Depends(get_db)) -> FunnelService:
    return FunnelService(db)


async def _can_manage_competition(db: AsyncSession, user: User, event_id: uuid.UUID) -> bool:
    return await user_has_global_role(db, user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}) or await user_has_scoped_role(db, user.id, {RoleName.EVENT_MANAGER}, event_id, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})


@router.get("/competitions", response_model=Page[CompetitionOut])
async def list_competitions(event_id: uuid.UUID | None = None, search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    if event_id is None and (current_user is None or not await user_has_global_role(db, current_user.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})):
        raise PermissionDeniedError("event_id is required for public competition listing.")
    public = False
    if event_id is not None and (current_user is None or not await _can_manage_competition(db, current_user, event_id)):
        # Public users may browse only the event's published competition data.
        event = await service._get_event_or_raise(event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
        public = True
    items, total = await service.funnels.list_competitions(event_id, page=page, page_size=page_size, search=search, public=public)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/events/{event_id}/competitions", response_model=CompetitionOut, status_code=status.HTTP_201_CREATED)
async def create_competition(event_id: uuid.UUID, payload: CompetitionIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    if not await _can_manage_competition(db, current_user, event_id):
        raise PermissionDeniedError("You don't have permission to manage competitions for this event.")
    return await service.create_competition(event_id, current_user, **payload.model_dump())


@router.get("/competitions/{competition_id}", response_model=CompetitionOut)
async def get_competition(competition_id: uuid.UUID, current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if current_user is None or not await _can_manage_competition(db, current_user, competition.event_id):
        event = await service._get_event_or_raise(competition.event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
    return competition


@router.patch("/competitions/{competition_id}", response_model=CompetitionOut)
async def update_competition(competition_id: uuid.UUID, payload: CompetitionUpdateIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if not await _can_manage_competition(db, current_user, competition.event_id):
        raise PermissionDeniedError("You don't have permission to manage this competition.")
    return await service.update_competition(competition_id, current_user, **payload.model_dump(exclude_unset=True))


@router.post("/competitions/{competition_id}/status", response_model=CompetitionOut)
async def change_competition_status(competition_id: uuid.UUID, payload: CompetitionStatusIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if not await _can_manage_competition(db, current_user, competition.event_id):
        raise PermissionDeniedError("You don't have permission to manage this competition.")
    return await service.change_competition_status(competition_id, current_user, payload.status)


@router.get("/events/{event_id}/stages", response_model=list[CompetitionStageOut])
async def list_stages(
    event_id: str,
    current_user: User | None = Depends(get_current_user_optional),
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


@router.get("/competitions/{competition_id}/stages", response_model=list[CompetitionStageOut])
async def list_competition_stages(competition_id: uuid.UUID, current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if current_user is None or not await _can_manage_competition(db, current_user, competition.event_id):
        event = await service._get_event_or_raise(competition.event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
    return await service.list_competition_stages(competition_id)


@router.post("/competitions/{competition_id}/entries", response_model=EntryOut, status_code=status.HTTP_201_CREATED)
async def add_competition_entry(competition_id: uuid.UUID, registration_id: uuid.UUID = Query(...), current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    registration = await db.get(Registration, registration_id)
    if registration is None or registration.event_id != competition.event_id:
        raise PermissionDeniedError("Registration does not belong to this competition event.")
    allowed = registration.user_id == current_user.id or await _can_manage_competition(db, current_user, competition.event_id)
    if not allowed:
        raise PermissionDeniedError("You cannot add this registration to the competition.")
    return await service.create_entry(competition.event_id, registration_id, competition_id)


@router.get("/competitions/{competition_id}/entries", response_model=Page[EntryOut])
async def list_competition_entries(competition_id: uuid.UUID, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if current_user is None or not await _can_manage_competition(db, current_user, competition.event_id):
        event = await service._get_event_or_raise(competition.event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
    items, total = await service.funnels.page_entries_for_competition(competition_id, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/competitions/{competition_id}/matches", response_model=MatchOut, status_code=status.HTTP_201_CREATED)
async def create_match(competition_id: uuid.UUID, payload: MatchIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if not await _can_manage_competition(db, current_user, competition.event_id):
        raise PermissionDeniedError("You don't have permission to manage competition fixtures.")
    return await service.create_match(competition_id, current_user, **payload.model_dump())


@router.get("/competitions/{competition_id}/matches", response_model=Page[MatchOut])
async def list_matches(competition_id: uuid.UUID, stage_id: uuid.UUID | None = None, match_status: MatchStatus | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if current_user is None or not await _can_manage_competition(db, current_user, competition.event_id):
        event = await service._get_event_or_raise(competition.event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
    items, total = await service.page_matches(competition_id, page=page, page_size=page_size, stage_id=stage_id, status=match_status)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/matches/{match_id}/result", response_model=MatchOut)
async def record_match_result(match_id: uuid.UUID, payload: MatchResultIn, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    match = await service.funnels.get_match(match_id)
    if match is None or not await _can_manage_competition(db, current_user, match.event_id):
        raise PermissionDeniedError("You don't have permission to record this result.")
    return await service.record_result(match_id, current_user, **payload.model_dump())


@router.get("/competitions/{competition_id}/standings", response_model=list[StandingsOut])
async def get_standings(competition_id: uuid.UUID, current_user: User | None = Depends(get_current_user_optional), db: AsyncSession = Depends(get_db), service: FunnelService = Depends(get_funnel_service)):
    competition = await service.get_competition_or_raise(competition_id)
    if current_user is None or not await _can_manage_competition(db, current_user, competition.event_id):
        event = await service._get_event_or_raise(competition.event_id)
        if event.status.value not in {"published", "registration_open", "registration_closed", "live", "completed"}:
            raise PermissionDeniedError("Competition is not public.")
    return await service.standings(competition_id)


@router.get("/entries/public", response_model=list[EntryOut] | Page[EntryOut])
async def list_public_vote_entries(
    stage_id: str = Query(...),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User | None = Depends(get_current_user_optional),
    service: FunnelService = Depends(get_funnel_service),
):
    """
    Called by: mobile's public voting screen (Section 8, Phase 6). Closes
    a real gap — GET /entries is Event-Manager-only, so a participant had
    no way whatsoever to discover which entries exist to vote for. Only
    ever returns entries for a stage whose stage_type is PUBLIC_VOTE.
    """
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    if page is None:
        return await service.list_public_vote_entries(uuid.UUID(stage_id))
    stage = await service._get_stage_or_raise(uuid.UUID(stage_id))
    if stage.stage_type != "public_vote":
        return await service.list_public_vote_entries(uuid.UUID(stage_id))
    items, total = await service.page_entries(stage.id, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/entries", response_model=list[EntryOut] | Page[EntryOut])
async def list_entries(
    stage_id: str = Query(...),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
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
    if not isinstance(page, int):
        page = None
    if page is None:
        return await service.list_entries(stage.id)
    items, total = await service.page_entries(stage.id, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


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
