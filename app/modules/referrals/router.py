"""Referral tracking and review endpoints."""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.referrals.schemas import ReferralMineOut, ReferralRewardOut, ReferralTrackIn, ReferralOut
from app.modules.referrals.service import ReferralService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/referrals", tags=["referrals"])


def get_referral_service(db: AsyncSession = Depends(get_db)) -> ReferralService:
    return ReferralService(db)


@router.get("/mine", response_model=ReferralMineOut)
async def get_my_referrals(
    event_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    service: ReferralService = Depends(get_referral_service),
):
    profile, rewards = await service.get_mine(uuid.UUID(event_id), current_user)
    return ReferralMineOut(
        profile=ReferralOut.model_validate(profile),
        rewards=[ReferralRewardOut.model_validate(reward) for reward in rewards],
    )


@router.post("/track", response_model=ReferralRewardOut, status_code=status.HTTP_201_CREATED)
async def track_referral(
    payload: ReferralTrackIn,
    current_user: User = Depends(get_current_user),
    service: ReferralService = Depends(get_referral_service),
):
    reward = await service.track_referral(
        event_id=payload.event_id,
        actor=current_user,
        referral_code=payload.referral_code,
        registration_id=payload.registration_id,
        device_fingerprint=payload.device_fingerprint,
        ip_address=payload.ip_address,
    )
    return ReferralRewardOut.model_validate(reward)


@router.get(
    "/flagged",
    response_model=list[ReferralRewardOut],
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def list_flagged_referrals(
    service: ReferralService = Depends(get_referral_service),
):
    return [ReferralRewardOut.model_validate(reward) for reward in await service.list_flagged()]
