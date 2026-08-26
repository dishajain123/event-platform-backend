"""Data access for referrals and referral rewards."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.referrals.models import Referral, ReferralReward, ReferralRewardStatus


class ReferralRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Referral:
        referral = Referral(**kwargs)
        self.db.add(referral)
        await self.db.flush()
        return referral

    async def get_by_id(self, referral_id: uuid.UUID) -> Referral | None:
        return await self.db.get(Referral, referral_id)

    async def get_by_code(self, event_id: uuid.UUID, referral_code: str) -> Referral | None:
        result = await self.db.execute(
            select(Referral).where(Referral.event_id == event_id, Referral.referral_code == referral_code)
        )
        return result.scalar_one_or_none()

    async def get_by_referrer(self, event_id: uuid.UUID, referrer_user_id: uuid.UUID) -> Referral | None:
        result = await self.db.execute(
            select(Referral).where(
                Referral.event_id == event_id,
                Referral.referrer_user_id == referrer_user_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_referrer(self, referrer_user_id: uuid.UUID) -> list[Referral]:
        result = await self.db.execute(
            select(Referral).where(Referral.referrer_user_id == referrer_user_id)
        )
        return list(result.scalars().all())


class ReferralRewardRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> ReferralReward:
        reward = ReferralReward(**kwargs)
        self.db.add(reward)
        await self.db.flush()
        return reward

    async def get_by_id(self, reward_id: uuid.UUID) -> ReferralReward | None:
        return await self.db.get(ReferralReward, reward_id)

    async def get_by_registration_id(self, registration_id: uuid.UUID) -> ReferralReward | None:
        result = await self.db.execute(
            select(ReferralReward).where(ReferralReward.registration_id == registration_id)
        )
        return result.scalar_one_or_none()

    async def list_for_referrer(self, referrer_user_id: uuid.UUID) -> list[ReferralReward]:
        result = await self.db.execute(
            select(ReferralReward)
            .join(Referral, ReferralReward.referral_id == Referral.id)
            .where(Referral.referrer_user_id == referrer_user_id)
        )
        return list(result.scalars().all())

    async def list_flagged(self) -> list[ReferralReward]:
        result = await self.db.execute(
            select(ReferralReward).where(ReferralReward.is_flagged.is_(True))
        )
        return list(result.scalars().all())

    async def list_pending_or_tracked(self) -> list[ReferralReward]:
        result = await self.db.execute(
            select(ReferralReward).where(
                ReferralReward.status.in_(
                    (ReferralRewardStatus.TRACKED, ReferralRewardStatus.QUALIFIED)
                )
            )
        )
        return list(result.scalars().all())
