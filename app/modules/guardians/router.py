"""Guardian endpoints."""
from fastapi import APIRouter, Depends, status

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.guardians.schemas import ChildProfileIn, ChildProfileOut
from app.modules.guardians.service import GuardianService
from app.modules.identity.models import User

router = APIRouter(prefix="/guardians", tags=["guardians"])


def get_guardian_service(db=Depends(get_db)) -> GuardianService:
    return GuardianService(db)


@router.post("/children", response_model=ChildProfileOut, status_code=status.HTTP_201_CREATED)
async def create_child_profile(
    payload: ChildProfileIn,
    current_user: User = Depends(get_current_user),
    service: GuardianService = Depends(get_guardian_service),
):
    return await service.create_child(
        current_user.id, payload.full_name, payload.date_of_birth, payload.relationship_label
    )


@router.get("/children", response_model=list[ChildProfileOut])
async def list_children(
    current_user: User = Depends(get_current_user),
    service: GuardianService = Depends(get_guardian_service),
):
    return await service.list_children(current_user.id)
