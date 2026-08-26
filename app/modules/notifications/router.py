"""Notification inbox and send endpoints."""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, require_role, require_scoped_role
from app.modules.identity.models import User
from app.modules.notifications.models import NotificationChannel
from app.modules.notifications.schemas import NotificationOut, NotificationSendIn, NotificationTemplateOut
from app.modules.notifications.service import NotificationService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/notifications", tags=["notifications"])
templates_router = APIRouter(tags=["notifications"])


def get_notification_service(db: AsyncSession = Depends(get_db)) -> NotificationService:
    return NotificationService(db)


@router.get("/mine", response_model=list[NotificationOut])
async def list_my_notifications(
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.list_my_notifications(current_user)


@router.post(
    "/send",
    response_model=list[NotificationOut],
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_COORDINATOR,
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def send_notification(
    payload: NotificationSendIn,
    current_user: User = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
):
    return await service.send_notifications(
        actor=current_user,
        title=payload.title,
        body=payload.body,
        channels=payload.channels,
        event_id=payload.target.event_id,
        participation_types=payload.target.participation_types,
        registration_statuses=payload.target.registration_statuses,
        recipient_user_ids=payload.target.recipient_user_ids,
    )


@templates_router.get(
    "/notification-templates",
    response_model=list[NotificationTemplateOut],
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def list_notification_templates(
    service: NotificationService = Depends(get_notification_service),
):
    return await service.list_templates()
