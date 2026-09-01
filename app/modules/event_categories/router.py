import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.event_categories.schemas import (
    MainCategoryCreateIn,
    MainCategoryOut,
    MainCategoryUpdateIn,
    SubCategoryCreateIn,
    SubCategoryOut,
    SubCategoryUpdateIn,
)
from app.modules.event_categories.service import EventCategoryService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/event-categories", tags=["event-categories"])


def get_event_category_service(db: AsyncSession = Depends(get_db)) -> EventCategoryService:
    return EventCategoryService(db)


@router.get("/main", response_model=list[MainCategoryOut])
async def list_main_categories(
    _current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.list_main_categories()


@router.post(
    "/main",
    response_model=MainCategoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def create_main_category(
    payload: MainCategoryCreateIn,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.create_main_category(current_user.id, **payload.model_dump())


@router.patch(
    "/main/{main_category_id}",
    response_model=MainCategoryOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def update_main_category(
    main_category_id: uuid.UUID,
    payload: MainCategoryUpdateIn,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.update_main_category(main_category_id, current_user.id, **payload.model_dump(exclude_unset=True))


@router.delete(
    "/main/{main_category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def delete_main_category(
    main_category_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    await service.delete_main_category(main_category_id, current_user.id)


@router.get("/sub", response_model=list[SubCategoryOut])
async def list_sub_categories(
    main_category_id: uuid.UUID | None = None,
    _current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.list_sub_categories(main_category_id=main_category_id)


@router.post(
    "/sub",
    response_model=SubCategoryOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def create_sub_category(
    payload: SubCategoryCreateIn,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.create_sub_category(current_user.id, **payload.model_dump())


@router.patch(
    "/sub/{sub_category_id}",
    response_model=SubCategoryOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def update_sub_category(
    sub_category_id: uuid.UUID,
    payload: SubCategoryUpdateIn,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    return await service.update_sub_category(sub_category_id, current_user.id, **payload.model_dump(exclude_unset=True))


@router.delete(
    "/sub/{sub_category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def delete_sub_category(
    sub_category_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: EventCategoryService = Depends(get_event_category_service),
):
    await service.delete_sub_category(sub_category_id, current_user.id)
