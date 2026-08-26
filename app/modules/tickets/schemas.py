"""Contracts for tickets and check-ins."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.tickets.models import CheckInSource, TicketStatus


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    registration_id: uuid.UUID
    payment_id: uuid.UUID
    user_id: uuid.UUID
    ticket_code: str
    qr_payload: str
    qr_signature: str
    status: TicketStatus
    issued_at: datetime | None
    checked_in_at: datetime | None
    checked_in_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class CheckInOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID | None
    scanned_by: uuid.UUID
    source: CheckInSource
    offline_batch_id: str | None
    synced_at: datetime | None
    scan_payload: str | None
    created_at: datetime
    updated_at: datetime


class CheckInIn(BaseModel):
    venue_id: uuid.UUID | None = None
    offline_batch_id: str | None = None
    scan_payload: str | None = None
    qr_signature: str | None = None


class OfflineCheckInIn(CheckInIn):
    scan_payload: str
    qr_signature: str


class OfflineCheckInBatchIn(BaseModel):
    scans: list[OfflineCheckInIn]
