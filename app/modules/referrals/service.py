"""Referral profile management, tracking, and reward issuance."""
import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.payments.models import PaymentStatus
from app.modules.payments.repository import PaymentRepository
from app.modules.referrals.exceptions import (
    InvalidReferralStateError,
    ReferralConflictError,
    ReferralNotFoundError,
    ReferralRewardNotFoundError,
)
from app.modules.referrals.models import Referral, ReferralReward, ReferralRewardStatus, ReferralRewardType
from app.modules.referrals.repository import ReferralRepository, ReferralRewardRepository
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository

# Used only if an event's configuration genuinely has no "referral" key
# at all yet — NOT a business default, just a safe fallback so a referral
# profile can still be created (with a zero reward) rather than crashing,
# until an Operations Admin/Event Manager configures the real value.
_UNCONFIGURED_REWARD_VALUE = Decimal("0")


class ReferralService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventRepository(db)
        self.referrals = ReferralRepository(db)
        self.rewards = ReferralRewardRepository(db)
        self.registrations = RegistrationRepository(db)
        self.payments = PaymentRepository(db)
        self.config = ConfigEngineService(db)

    def _generate_referral_code(self, event_id: uuid.UUID, user_id: uuid.UUID) -> str:
        raw = f"{event_id.hex}:{user_id.hex}".encode()
        digest = hashlib.sha256(raw).hexdigest()[:10].upper()
        return f"REF-{digest}"

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def _get_configured_reward_value(self, event_id: uuid.UUID) -> Decimal:
        """
        Reads the referral reward amount from this event's own
        configuration (EventConfiguration.rules["referral"]["reward_value"])
        instead of a fixed platform-wide number — this is what lets two
        different events on the same platform offer two different
        referral rewards, set by whoever configures each event.
        """
        configuration = await self.config.get_configuration(event_id)
        if configuration is None:
            return _UNCONFIGURED_REWARD_VALUE
        referral_rules = (configuration.rules or {}).get("referral") or {}
        raw_value = referral_rules.get("reward_value")
        if raw_value is None:
            return _UNCONFIGURED_REWARD_VALUE
        return Decimal(str(raw_value))

    async def get_or_create_profile(self, event_id: uuid.UUID, actor: User) -> Referral:
        await self._get_event_or_raise(event_id)
        referral = await self.referrals.get_by_referrer(event_id, actor.id)
        if referral is not None:
            return referral
        reward_value = await self._get_configured_reward_value(event_id)
        referral = await self.referrals.create(
            event_id=event_id,
            referrer_user_id=actor.id,
            referral_code=self._generate_referral_code(event_id, actor.id),
            reward_value=reward_value,
        )
        await write_audit_log(
            self.db,
            entity_type="referral",
            entity_id=referral.id,
            action="created",
            actor_user_id=actor.id,
            after_value={"referral_code": referral.referral_code, "reward_value": str(reward_value)},
        )
        await self.db.commit()
        await self.db.refresh(referral)
        return referral

    async def get_mine(self, event_id: uuid.UUID, actor: User) -> tuple[Referral, list[ReferralReward]]:
        profile = await self.get_or_create_profile(event_id, actor)
        rewards = await self.rewards.list_for_referrer(actor.id)
        return profile, rewards

    def _flag_reason(self, device_fingerprint: str | None, ip_address: str | None, self_referral: bool) -> str | None:
        reasons: list[str] = []
        if self_referral:
            reasons.append("referred user matched referrer account")
        if device_fingerprint:
            reasons.append(f"device={device_fingerprint}")
        if ip_address:
            reasons.append(f"ip={ip_address}")
        return "; ".join(reasons) if reasons else None

    async def track_referral(
        self,
        *,
        event_id: uuid.UUID,
        actor: User,
        referral_code: str,
        registration_id: uuid.UUID | None,
        device_fingerprint: str | None,
        ip_address: str | None,
    ) -> ReferralReward:
        await self._get_event_or_raise(event_id)
        referral = await self.referrals.get_by_code(event_id, referral_code)
        if referral is None:
            raise ReferralNotFoundError("Referral code not found.")
        is_self_referral = referral.referrer_user_id == actor.id
        flag_reason = self._flag_reason(device_fingerprint, ip_address, is_self_referral)

        reward = await self.rewards.create(
            referral_id=referral.id,
            referred_user_id=actor.id,
            registration_id=registration_id,
            device_fingerprint=device_fingerprint,
            ip_address=ip_address,
            reward_type=ReferralRewardType.VOUCHER,
            reward_value=referral.reward_value,
            status=ReferralRewardStatus.TRACKED,
            is_flagged=flag_reason is not None,
            flag_reason=flag_reason,
            reward_metadata={"tracked_from": referral.referral_code},
        )
        await write_audit_log(
            self.db,
            entity_type="referral_reward",
            entity_id=reward.id,
            action="tracked",
            actor_user_id=actor.id,
            after_value={"referral_code": referral.referral_code, "is_flagged": reward.is_flagged},
        )
        await self.db.commit()
        await self.db.refresh(reward)
        return reward

    async def evaluate_referral_qualification(self, registration_id: uuid.UUID) -> ReferralReward | None:
        registration = await self.registrations.get_by_id(registration_id)
        if registration is None:
            raise InvalidReferralStateError("Registration not found.")
        payment = await self.payments.get_by_registration_id(registration_id)
        if payment is None or payment.status != PaymentStatus.VERIFIED:
            return None
        if registration.status not in {RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}:
            return None

        reward = await self.rewards.get_by_registration_id(registration_id)
        if reward is None:
            raise ReferralRewardNotFoundError("Referral reward not found.")
        if reward.status == ReferralRewardStatus.ISSUED:
            return reward

        referral = await self.referrals.get_by_id(reward.referral_id)
        if referral is None:
            raise ReferralNotFoundError("Referral not found.")

        reward.status = ReferralRewardStatus.ISSUED
        reward.qualified_at = datetime.now(timezone.utc)
        reward.issued_at = datetime.now(timezone.utc)
        reward.reward_metadata = {
            **(reward.reward_metadata or {}),
            "payment_id": str(payment.id),
            "registration_status": registration.status.value,
        }
        referral.total_rewards_issued += 1
        await write_audit_log(
            self.db,
            entity_type="referral_reward",
            entity_id=reward.id,
            action="issued",
            actor_user_id=None,
            after_value={"registration_id": str(registration_id)},
        )
        await self.db.commit()
        await self.db.refresh(reward)
        return reward

    async def list_flagged(self) -> list[ReferralReward]:
        return await self.rewards.list_flagged()