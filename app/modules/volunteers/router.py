import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.volunteers.models import VolunteerApplicationStatus, VolunteerApplicationType
from app.modules.volunteers.schemas import VolunteerApplicationCreateIn, VolunteerApplicationOut, VolunteerApplicationStatusIn
from app.modules.volunteers.service import VolunteerService

router = APIRouter(prefix="/volunteers", tags=["volunteers"])


def get_service(db: AsyncSession = Depends(get_db)) -> VolunteerService:
    return VolunteerService(db)


@router.post("/applications", response_model=VolunteerApplicationOut, status_code=status.HTTP_201_CREATED)
async def create_application(payload: VolunteerApplicationCreateIn, current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service)):
    return await service.create_application(current_user, payload.model_dump())


@router.get("/applications/mine", response_model=list[VolunteerApplicationOut])
async def list_mine(current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service)):
    return await service.list_mine(current_user)


@router.get("/applications", response_model=list[VolunteerApplicationOut])
async def list_manageable(
    event_id: uuid.UUID | None = None,
    application_status: VolunteerApplicationStatus | None = Query(None, alias="status"),
    application_type: VolunteerApplicationType | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service),
):
    return await service.list_manageable(current_user, event_id, application_status, search, application_type)


@router.get("/applications/{application_id}", response_model=VolunteerApplicationOut)
async def get_application(application_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service)):
    return await service.get_visible(current_user, application_id)


@router.patch("/applications/{application_id}/status", response_model=VolunteerApplicationOut)
async def update_status(application_id: uuid.UUID, payload: VolunteerApplicationStatusIn, current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service)):
    return await service.update_status(current_user, application_id, payload.status)


@router.post("/applications/{application_id}/activate", response_model=VolunteerApplicationOut)
async def activate(application_id: uuid.UUID, current_user: User = Depends(get_current_user), service: VolunteerService = Depends(get_service)):
    return await service.activate(current_user, application_id)
