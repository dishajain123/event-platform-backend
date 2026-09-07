import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.waitlists.models import WaitlistStatus
from app.modules.waitlists.schemas import WaitlistJoinIn, WaitlistOut
from app.modules.waitlists.service import WaitlistService

router = APIRouter(prefix="/waitlists", tags=["waitlists"])


def get_service(db: AsyncSession = Depends(get_db)) -> WaitlistService:
    return WaitlistService(db)


@router.post("", response_model=WaitlistOut, status_code=status.HTTP_201_CREATED)
async def join_waitlist(payload: WaitlistJoinIn, event_id: uuid.UUID = Query(...), current_user: User = Depends(get_current_user), service: WaitlistService = Depends(get_service)):
    return await service.join(current_user, event_id, payload.participation_type, payload.child_id, payload.team_id)


@router.get("/mine", response_model=Page[WaitlistOut])
async def list_my_waitlists(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User = Depends(get_current_user), service: WaitlistService = Depends(get_service)):
    items, total = await service.list_mine(current_user, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("", response_model=Page[WaitlistOut])
async def list_manageable_waitlists(event_id: uuid.UUID | None = None, waitlist_status: WaitlistStatus | None = Query(None, alias="status"), participation_type: str | None = Query(None, max_length=50), search: str | None = Query(None, max_length=100), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User = Depends(get_current_user), service: WaitlistService = Depends(get_service)):
    items, total = await service.page_manageable(current_user, event_id=event_id, status=waitlist_status, participation_type=participation_type, search=search, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.delete("/{entry_id}", response_model=WaitlistOut)
async def leave_waitlist(entry_id: uuid.UUID, current_user: User = Depends(get_current_user), service: WaitlistService = Depends(get_service)):
    return await service.leave(current_user, entry_id)


@router.post("/{entry_id}/retry", response_model=WaitlistOut)
async def retry_waitlist(entry_id: uuid.UUID, current_user: User = Depends(get_current_user), service: WaitlistService = Depends(get_service)):
    return await service.retry(current_user, entry_id)
