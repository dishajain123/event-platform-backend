"""
Assistance requests and reviewer decisions.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class AssistanceRequestStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssistanceRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "assistance_requests"
    __table_args__ = (UniqueConstraint("registration_id", name="uq_assistance_registration"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    status: Mapped[AssistanceRequestStatus] = mapped_column(
        Enum(AssistanceRequestStatus), default=AssistanceRequestStatus.PENDING
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_fee_waiver_amount: Mapped[float | None] = mapped_column(
        Numeric(10, 2), default=None
    )
    decision_reason: Mapped[str | None] = mapped_column(Text, default=None)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    applied_discount_code: Mapped[str | None] = mapped_column(String(50), default=None)
