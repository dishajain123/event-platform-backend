"""Participant feedback and event-scoped operational feedback views."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.database import get_db
from app.dependencies import get_current_user
from app.exceptions import PermissionDeniedError
from app.modules.feedback.models import FeedbackCategory
from app.modules.feedback.schemas import (
    FeedbackCategoryOut,
    FeedbackCreateIn,
    FeedbackOut,
    FeedbackSummaryOut,
    FeedbackUpdateIn,
)
from app.modules.feedback.service import FeedbackService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/feedback", tags=["feedback"])
GLOBAL_FEEDBACK_ROLES = {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
SCOPED_FEEDBACK_ROLES = {RoleName.EVENT_MANAGER}


def get_feedback_service(db: AsyncSession = Depends(get_db)) -> FeedbackService:
    return FeedbackService(db)


def _to_out(feedback) -> FeedbackOut:
    category = feedback.category if isinstance(feedback.category, FeedbackCategory) else FeedbackCategory(feedback.category)
    return FeedbackOut(
        id=feedback.id,
        event_id=feedback.event_id,
        event_name=feedback.event.name if feedback.event else None,
        user_id=feedback.user_id,
        user_name=feedback.user.name if feedback.user else None,
        category=category,
        category_label=category.label,
        rating=feedback.rating,
        comment=feedback.comment,
        created_at=feedback.created_at,
        updated_at=feedback.updated_at,
    )


async def _scope_for_actor(
    current_user: User,
    db: AsyncSession,
    event_id: uuid.UUID | None,
) -> tuple[set[uuid.UUID] | None, uuid.UUID | None]:
    if await user_has_global_role(db, current_user.id, GLOBAL_FEEDBACK_ROLES):
        return None, event_id
    if event_id is None or not await user_has_scoped_role(
        db, current_user.id, SCOPED_FEEDBACK_ROLES, event_id
    ):
        event_ids = await user_scoped_event_ids(db, current_user.id, SCOPED_FEEDBACK_ROLES)
        if event_id is not None and event_id not in event_ids:
            raise PermissionDeniedError("You don't have permission to view feedback for this event.")
        if not event_ids:
            raise PermissionDeniedError("You don't have permission to view event feedback.")
        return event_ids, None
    return None, event_id


@router.get("/categories", response_model=list[FeedbackCategoryOut])
async def list_feedback_categories():
    return FeedbackService.categories()


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackCreateIn,
    current_user: User = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    return _to_out(await service.submit(current_user, payload.event_id, payload.category, payload.rating, payload.comment))


@router.get("/mine", response_model=list[FeedbackOut])
async def list_my_feedback(
    event_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    return [_to_out(row) for row in await service.list_mine(current_user, event_id)]


@router.get("/summary", response_model=FeedbackSummaryOut)
async def feedback_summary(
    event_id: uuid.UUID | None = None,
    category: FeedbackCategory | None = None,
    rating: int | None = Query(default=None, ge=1, le=5),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FeedbackService = Depends(get_feedback_service),
):
    event_ids, requested_event_id = await _scope_for_actor(current_user, db, event_id)
    return await service.summary_scoped(
        event_ids=event_ids,
        event_id=requested_event_id,
        category=category,
        rating=rating,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("", response_model=list[FeedbackOut])
async def list_feedback(
    event_id: uuid.UUID | None = None,
    category: FeedbackCategory | None = None,
    rating: int | None = Query(default=None, ge=1, le=5),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FeedbackService = Depends(get_feedback_service),
):
    event_ids, requested_event_id = await _scope_for_actor(current_user, db, event_id)
    rows = await service.list_scoped(
        event_ids=event_ids,
        event_id=requested_event_id,
        category=category,
        rating=rating,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return [_to_out(row) for row in rows]


@router.get("/{feedback_id}", response_model=FeedbackOut)
async def get_feedback(
    feedback_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    service: FeedbackService = Depends(get_feedback_service),
):
    feedback = await service.feedback.get_by_id(feedback_id)
    if feedback is None:
        from app.modules.feedback.exceptions import FeedbackNotFoundError
        raise FeedbackNotFoundError("Feedback not found.")
    can_view_event = await user_has_global_role(db, current_user.id, GLOBAL_FEEDBACK_ROLES) or await user_has_scoped_role(
        db, current_user.id, SCOPED_FEEDBACK_ROLES, feedback.event_id, allow_global_roles=GLOBAL_FEEDBACK_ROLES
    )
    return _to_out(await service.get_for_actor(feedback_id, current_user, can_view_event))


@router.put("/{feedback_id}", response_model=FeedbackOut)
async def update_feedback(
    feedback_id: uuid.UUID,
    payload: FeedbackUpdateIn,
    current_user: User = Depends(get_current_user),
    service: FeedbackService = Depends(get_feedback_service),
):
    return _to_out(
        await service.update_mine(feedback_id, current_user, payload.category, payload.rating, payload.comment)
    )
