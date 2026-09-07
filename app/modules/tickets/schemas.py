"""Contracts for tickets and check-ins."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tickets.models import AccessType, CheckInSource, TicketStatus, TicketTransferStatus, TicketValidationReason


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    registration_id: uuid.UUID
    participant_id: uuid.UUID | None = None
    payment_id: uuid.UUID | None
    user_id: uuid.UUID
    ticket_code: str
    barcode_payload: str
    barcode_signature: str
    access_type: str
    entry_count: int
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    valid_dates: list[date] | None = None
    status: TicketStatus
    issued_at: datetime | None
    checked_in_at: datetime | None
    checked_in_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class TicketValidationOut(BaseModel):
    valid: bool
    reason: TicketValidationReason
    ticket: TicketOut | None = None
    event_id: uuid.UUID | None = None
    message: str


class AccessZoneIn(BaseModel):
    code: str
    name: str
    is_active: bool = True


class AccessZoneOut(AccessZoneIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class AccessPolicyIn(BaseModel):
    access_type: str = AccessType.GENERAL.value
    allowed_zone_ids: list[uuid.UUID] = Field(default_factory=list)
    allows_reentry: bool = False
    max_entries: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    valid_dates: list[date] | None = None


class AccessPolicyOut(AccessPolicyIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class TicketReassignIn(BaseModel):
    user_id: uuid.UUID


class TicketTransferIn(BaseModel):
    recipient_user_id: uuid.UUID


class TicketTransferOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    ticket_id: uuid.UUID
    event_id: uuid.UUID
    from_user_id: uuid.UUID
    to_user_id: uuid.UUID
    status: TicketTransferStatus
    created_at: datetime
    updated_at: datetime
    responded_at: datetime | None
    accepted_at: datetime | None


class TicketTransferPage(BaseModel):
    items: list[TicketTransferOut]
    total: int
    page: int
    page_size: int


class TicketAccessTypeIn(BaseModel):
    access_type: str


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
    exited_at: datetime | None
    scan_payload: str | None
    created_at: datetime
    updated_at: datetime
    entry_number: int


class CheckInIn(BaseModel):
    venue_id: uuid.UUID | None = None
    access_zone_id: uuid.UUID | None = None
    offline_batch_id: str | None = Field(default=None, max_length=100)
    scan_payload: str | None = Field(default=None, max_length=512)
    barcode_signature: str | None = Field(default=None, max_length=128)


class OfflineCheckInIn(CheckInIn):
    scan_payload: str
    barcode_signature: str


class OfflineCheckInBatchIn(BaseModel):
    # Keep server-side sync work bounded even if a compromised client submits
    # a large batch. The mobile queue syncs individual operations by design.
    scans: list[OfflineCheckInIn] = Field(min_length=1, max_length=100)


class ResolveTicketIn(BaseModel):
    """
    Request body for GET-by-scan resolution (Section 9, Phase 5's fix):
    the online check-in scanner's first call after every scan, before it
    can call POST /{ticket_id}/check-in with a real UUID.
    """

    scan_payload: str
    barcode_signature: str
