import uuid
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.pagination import Page
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.database import get_db
from app.dependencies import get_current_user
from app.exceptions import PermissionDeniedError
from app.modules.identity.models import User
from app.modules.networking.models import ConnectionStatus, NetworkingProfile, NetworkingReport, NetworkingReportStatus
from app.modules.networking.schemas import ActivityOut, ConnectionActionIn, ConnectionCreateIn, ConnectionOut, NetworkingConfigIn, NetworkingConfigOut, NetworkingMetricsOut, ParticipantOut, ProfileIn, ProfileOut, ReportActionIn, ReportIn, ReportOut
from app.modules.networking.service import NetworkingService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/networking", tags=["networking"])
GLOBAL = {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
MANAGERS = {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR}

def svc(db: AsyncSession = Depends(get_db)): return NetworkingService(db)
async def manager(db, user, event_id): return await user_has_global_role(db, user.id, GLOBAL) or await user_has_scoped_role(db, user.id, MANAGERS, event_id, allow_global_roles=GLOBAL)
async def require_manager(db, user, event_id):
    if not await manager(db, user, event_id): raise PermissionDeniedError("You don't have permission for this event.")

@router.get("/events/{event_id}/config", response_model=NetworkingConfigOut | None)
async def get_config(event_id: uuid.UUID, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)):
    await service.event(event_id); return await service.config(event_id)

@router.put("/events/{event_id}/config", response_model=NetworkingConfigOut)
async def set_config(event_id: uuid.UUID, payload: NetworkingConfigIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: NetworkingService = Depends(svc)):
    await require_manager(db, user, event_id); await service.event(event_id); config = await service.config(event_id)
    if config is None:
        from app.modules.networking.models import EventNetworkingConfig
        config = EventNetworkingConfig(event_id=event_id); db.add(config)
    for key, value in payload.model_dump().items(): setattr(config, key, value)
    await db.commit(); await db.refresh(config); return config

@router.get("/events/{event_id}/profile", response_model=ProfileOut)
async def my_profile(event_id: uuid.UUID, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.profile(event_id, user.id)

@router.put("/events/{event_id}/profile", response_model=ProfileOut)
async def update_profile(event_id: uuid.UUID, payload: ProfileIn, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.save_profile(event_id, user, payload.model_dump())

@router.get("/events/{event_id}/participants", response_model=Page[ParticipantOut])
async def participants(event_id: uuid.UUID, search: str | None = Query(None, max_length=100), organization: str | None = Query(None, max_length=255), designation: str | None = Query(None, max_length=255), interest: str | None = Query(None, max_length=100), skill: str | None = Query(None, max_length=100), recommended: bool = False, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.discover(event_id, user.id, page=page, page_size=page_size, search=search, organization=organization, designation=designation, interest=interest, skill=skill, recommended=recommended)

@router.get("/events/{event_id}/participants/{profile_id}", response_model=ProfileOut)
async def participant(event_id: uuid.UUID, profile_id: uuid.UUID, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.public_profile(event_id, profile_id, user.id)

@router.post("/events/{event_id}/participants/{participant_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_participant(event_id: uuid.UUID, participant_id: uuid.UUID, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)):
    await service.dismiss(event_id, user.id, participant_id)

@router.get("/events/{event_id}/activities", response_model=Page[ActivityOut])
async def activities(event_id: uuid.UUID, search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)):
    return await service.activities(event_id, user.id, page=page, page_size=page_size, search=search)

@router.post("/events/{event_id}/connections", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
async def send_connection(event_id: uuid.UUID, payload: ConnectionCreateIn, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.send_request(event_id, user, payload.participant_id, payload.intent)

@router.get("/events/{event_id}/connections", response_model=Page[ConnectionOut])
async def connections(event_id: uuid.UUID, status_filter: ConnectionStatus | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), service: NetworkingService = Depends(svc), db: AsyncSession = Depends(get_db)):
    if not await manager(db, user, event_id): await service.ensure_eligible(event_id, user.id)
    from app.modules.networking.models import NetworkingConnection
    where = [NetworkingConnection.event_id == event_id]
    if not await manager(db, user, event_id): where.append(or_(NetworkingConnection.participant_low_id == user.id, NetworkingConnection.participant_high_id == user.id))
    if status_filter: where.append(NetworkingConnection.status == status_filter)
    if search:
        matching = select(NetworkingProfile.user_id).where(NetworkingProfile.event_id == event_id, or_(NetworkingProfile.display_name.ilike(f"%{search}%"), NetworkingProfile.organization.ilike(f"%{search}%"))).scalar_subquery()
        where.append(or_(NetworkingConnection.participant_low_id.in_(matching), NetworkingConnection.participant_high_id.in_(matching)))
    total = await db.scalar(select(func.count(NetworkingConnection.id)).where(*where)) or 0
    rows = list((await db.scalars(select(NetworkingConnection).where(*where).order_by(NetworkingConnection.created_at.desc(), NetworkingConnection.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
    return Page(items=rows, total=total, page=page, page_size=page_size)

@router.post("/connections/{connection_id}/status", response_model=ConnectionOut)
async def connection_status(connection_id: uuid.UUID, payload: ConnectionActionIn, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.transition(connection_id, user, payload.status)

@router.post("/events/{event_id}/participants/{participant_id}/block", response_model=ConnectionOut)
async def block_participant(event_id: uuid.UUID, participant_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: NetworkingService = Depends(svc)):
    await require_manager(db, user, event_id)
    return await service.block_participant(event_id, user, participant_id)

@router.post("/events/{event_id}/participants/{participant_id}/unblock", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_participant(event_id: uuid.UUID, participant_id: uuid.UUID, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)):
    await service.unblock_participant(event_id, user, participant_id)

@router.post("/events/{event_id}/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def report(event_id: uuid.UUID, payload: ReportIn, user: User = Depends(get_current_user), service: NetworkingService = Depends(svc)): return await service.report(event_id, user, payload.reported_user_id, payload.reason)

@router.get("/events/{event_id}/reports", response_model=Page[ReportOut])
async def reports(event_id: uuid.UUID, status_filter: NetworkingReportStatus | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: NetworkingService = Depends(svc)):
    await require_manager(db, user, event_id); return await service.reports(event_id, page, page_size, status_filter)

@router.post("/reports/{report_id}/status", response_model=ReportOut)
async def report_status(report_id: uuid.UUID, payload: ReportActionIn, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: NetworkingService = Depends(svc)):
    report = await db.get(NetworkingReport, report_id)
    if report is None:
        from app.exceptions import NotFoundError
        raise NotFoundError("Report not found.")
    await require_manager(db, user, report.event_id); return await service.report_action(report_id, user, payload.status, payload.resolution_notes)

@router.get("/events/{event_id}/metrics", response_model=NetworkingMetricsOut)
async def metrics(event_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db), service: NetworkingService = Depends(svc)):
    await require_manager(db, user, event_id); return await service.metrics(event_id)
