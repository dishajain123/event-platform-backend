"""
Referral profiles and reward issuance records.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class ReferralRewardStatus(StrEnum):
    TRACKED = "tracked"
    QUALIFIED = "qualified"
    ISSUED = "issued"
    FLAGGED = "flagged"


class ReferralRewardType(StrEnum):
    VOUCHER = "voucher"
    DISCOUNT = "discount"
    CASHBACK = "cashback"


class Referral(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "referrals"
    __table_args__ = (UniqueConstraint("event_id", "referral_code", name="uq_referral_code_event"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    referrer_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    referral_code: Mapped[str] = mapped_column(String(50), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    reward_value: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    total_rewards_issued: Mapped[int] = mapped_column(default=0)

    rewards: Mapped[list["ReferralReward"]] = relationship(back_populates="referral", cascade="all, delete-orphan")


class ReferralReward(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "referral_rewards"

    referral_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("referrals.id"), nullable=False)
    referred_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), default=None
    )
    device_fingerprint: Mapped[str | None] = mapped_column(String(255), default=None)
    ip_address: Mapped[str | None] = mapped_column(String(100), default=None)
    reward_type: Mapped[ReferralRewardType] = mapped_column(Enum(ReferralRewardType), default=ReferralRewardType.VOUCHER)
    reward_value: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    status: Mapped[ReferralRewardStatus] = mapped_column(
        Enum(ReferralRewardStatus), default=ReferralRewardStatus.TRACKED
    )
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(Text, default=None)
    reward_metadata: Mapped[dict | None] = mapped_column("metadata_json", JSON, default=None)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    referral: Mapped["Referral"] = relationship(back_populates="rewards")
