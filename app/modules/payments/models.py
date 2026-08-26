"""
Payments, refunds, and discount codes.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class PaymentStatus(StrEnum):
    INITIATED = "initiated"
    VERIFIED = "verified"
    FAILED = "failed"
    REFUNDED = "refunded"


class RefundStatus(StrEnum):
    DRAFT = "draft"
    PENDING_ADMIN_APPROVAL = "pending_admin_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"


class DiscountType(StrEnum):
    PERCENTAGE = "percentage"
    FIXED = "fixed"


class DiscountCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "discount_codes"
    __table_args__ = (UniqueConstraint("event_id", "code", name="uq_discount_code_event"),)

    event_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("events.id"), default=None)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    discount_type: Mapped[DiscountType] = mapped_column(Enum(DiscountType), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_redemptions: Mapped[int | None] = mapped_column(Integer, default=None)
    discount_metadata: Mapped[dict | None] = mapped_column("metadata_json", JSON, default=None)


class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (UniqueConstraint("registration_id", name="uq_payment_registration"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[PaymentStatus] = mapped_column(Enum(PaymentStatus), default=PaymentStatus.INITIATED)
    gateway_provider: Mapped[str] = mapped_column(String(50), default="razorpay")
    gateway_order_id: Mapped[str | None] = mapped_column(String(100), default=None)
    gateway_payment_id: Mapped[str | None] = mapped_column(String(100), default=None)
    gateway_signature: Mapped[str | None] = mapped_column(String(255), default=None)
    discount_code: Mapped[str | None] = mapped_column(String(50), default=None)
    payment_metadata: Mapped[dict | None] = mapped_column("metadata_json", JSON, default=None)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    refunds: Mapped[list["Refund"]] = relationship(back_populates="payment", cascade="all, delete-orphan")


class Refund(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "refunds"

    payment_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("payments.id"), nullable=False)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    status: Mapped[RefundStatus] = mapped_column(Enum(RefundStatus), default=RefundStatus.DRAFT)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    gateway_refund_id: Mapped[str | None] = mapped_column(String(100), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    payment: Mapped["Payment"] = relationship(back_populates="refunds")
