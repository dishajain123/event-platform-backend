"""Pydantic contracts for referrals and rewards."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.referrals.models import ReferralRewardStatus, ReferralRewardType


class ReferralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    referrer_user_id: uuid.UUID
    referral_code: str
    is_active: bool
    reward_value: Decimal
    total_rewards_issued: int
    created_at: datetime
    updated_at: datetime


class ReferralRewardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    referral_id: uuid.UUID
    referred_user_id: uuid.UUID
    registration_id: uuid.UUID | None
    device_fingerprint: str | None
    ip_address: str | None
    reward_type: ReferralRewardType
    reward_value: Decimal
    status: ReferralRewardStatus
    is_flagged: bool
    flag_reason: str | None
    reward_metadata: dict | None
    qualified_at: datetime | None
    issued_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ReferralMineOut(BaseModel):
    profile: ReferralOut
    rewards: list[ReferralRewardOut]


class ReferralTrackIn(BaseModel):
    event_id: uuid.UUID
    referral_code: str
    registration_id: uuid.UUID | None = None
    device_fingerprint: str | None = None
    ip_address: str | None = None


class ReferralRewardCandidateOut(BaseModel):
    reward: ReferralRewardOut
