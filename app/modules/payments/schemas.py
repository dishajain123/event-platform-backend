"""Contracts for payments, webhooks, and refunds."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.payments.models import DiscountType, PaymentStatus, RefundStatus, WebhookProcessingStatus


class PaymentInitiateIn(BaseModel):
    registration_id: uuid.UUID
    discount_code: str | None = None


class PaymentGatewayOrderOut(BaseModel):
    payment_id: uuid.UUID
    gateway_order_id: str
    amount: Decimal
    currency: str
    key_id: str


class PaymentWebhookIn(BaseModel):
    gateway_order_id: str
    gateway_payment_id: str
    gateway_signature: str


class PaymentVerifyIn(PaymentWebhookIn):
    """Client callback contract for an authenticated checkout completion."""


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    registration_id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    currency: str
    status: PaymentStatus
    gateway_provider: str
    gateway_order_id: str | None
    gateway_payment_id: str | None
    gateway_signature: str | None
    discount_code: str | None
    verified_at: datetime | None
    captured_at: datetime | None
    created_at: datetime
    updated_at: datetime
    reconciliation_status: str
    reconciliation_attempts: int
    last_reconciled_at: datetime | None
    reconciliation_error: str | None


class DiscountCodeIn(BaseModel):
    event_id: uuid.UUID | None = None
    code: str
    discount_type: DiscountType
    value: int
    max_redemptions: int | None = None


class DiscountCodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID | None
    code: str
    discount_type: DiscountType
    value: int
    is_active: bool
    max_redemptions: int | None


class RefundRequestIn(BaseModel):
    payment_id: uuid.UUID
    amount: Decimal | None = None
    reason: str | None = None


class RefundApproveIn(BaseModel):
    reason: str | None = None


class RefundOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    payment_id: uuid.UUID
    requested_by: uuid.UUID
    amount: Decimal
    reason: str | None
    status: RefundStatus
    approved_by: uuid.UUID | None
    rejected_by: uuid.UUID | None
    gateway_refund_id: str | None
    approved_at: datetime | None
    processed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
    reconciliation_attempts: int
    last_reconciled_at: datetime | None
    reconciliation_error: str | None


class PaymentWebhookInboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_event_id: str
    provider: str
    event_type: str
    received_at: datetime
    processing_status: WebhookProcessingStatus
    attempts: int
    failure_reason: str | None
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime
