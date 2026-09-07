import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.incidents.models import IncidentSeverity, IncidentStatus
from app.modules.incidents.schemas import IncidentCreateIn, IncidentOut, IncidentUpdateIn
from app.modules.incidents.service import IncidentService

router = APIRouter(prefix="/incidents", tags=["incidents"])


def get_service(db: AsyncSession = Depends(get_db)) -> IncidentService:
    return IncidentService(db)


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
async def create_incident(payload: IncidentCreateIn, current_user: User = Depends(get_current_user), service: IncidentService = Depends(get_service)):
    return await service.create(current_user, payload)


@router.get("", response_model=Page[IncidentOut])
async def list_incidents(
    event_id: uuid.UUID | None = None,
    incident_status: IncidentStatus | None = Query(None, alias="status"),
    severity: IncidentSeverity | None = None,
    category: str | None = Query(None, max_length=80),
    assigned_user_id: uuid.UUID | None = None,
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user), service: IncidentService = Depends(get_service),
):
    items, total = await service.page(current_user, event_id=event_id, status=incident_status, severity=severity, category=category, assigned_user_id=assigned_user_id, search=search, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: uuid.UUID, current_user: User = Depends(get_current_user), service: IncidentService = Depends(get_service)):
    return await service.get(current_user, incident_id)


@router.patch("/{incident_id}", response_model=IncidentOut)
async def update_incident(incident_id: uuid.UUID, payload: IncidentUpdateIn, current_user: User = Depends(get_current_user), service: IncidentService = Depends(get_service)):
    return await service.update(current_user, incident_id, payload)
