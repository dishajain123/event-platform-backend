"""Pydantic contracts for assistance requests."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.assistance.models import AssistanceRequestStatus


class AssistanceRequestCreateIn(BaseModel):
    registration_id: uuid.UUID
    reason: str
    requested_fee_waiver_amount: Decimal | None = None


class AssistanceRequestDecideIn(BaseModel):
    approve: bool
    decision_reason: str | None = None
    requested_fee_waiver_amount: Decimal | None = None


class AssistanceRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    registration_id: uuid.UUID
    requester_user_id: uuid.UUID
    reviewer_user_id: uuid.UUID | None
    status: AssistanceRequestStatus
    reason: str
    requested_fee_waiver_amount: Decimal | None
    decision_reason: str | None
    decided_by: uuid.UUID | None
    decided_at: datetime | None
    applied_discount_code: str | None
    created_at: datetime
    updated_at: datetime
