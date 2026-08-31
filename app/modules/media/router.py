"""Media upload and public event media endpoints."""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, get_current_user_optional, require_role, require_scoped_role
from app.modules.identity.models import User
from app.modules.media.schemas import MediaOut, MediaPublishIn, MediaUploadIn
from app.modules.media.service import MediaService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/events/{event_id}/media", tags=["media"])
media_router = APIRouter(tags=["media"])


def get_media_service(db: AsyncSession = Depends(get_db)) -> MediaService:
    return MediaService(db)


@router.get("", response_model=list[MediaOut])
async def list_event_media(
    event_id: str,
    current_user: User | None = Depends(get_current_user_optional),
    service: MediaService = Depends(get_media_service),
):
    """
    Called by: both — public/mobile app (no auth, published only) and
    console (authenticated staff managing this event's media see
    drafts too). See MediaService.list_event_media for why this can't
    just be "authenticated = sees everything."
    """
    return await service.list_event_media(uuid.UUID(event_id), current_user)


@router.post(
    "",
    response_model=MediaOut,
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
async def upload_media(
    event_id: str,
    payload: MediaUploadIn,
    current_user: User = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
):
    return await service.upload_media(uuid.UUID(event_id), current_user, payload)


@media_router.post(
    "/media/{media_id}/publish",
    response_model=MediaOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def publish_media(
    media_id: str,
    payload: MediaPublishIn,
    current_user: User = Depends(get_current_user),
    service: MediaService = Depends(get_media_service),
):
    return await service.publish_media(uuid.UUID(media_id), current_user, is_published=payload.is_published)