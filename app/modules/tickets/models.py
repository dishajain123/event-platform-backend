"""
Tickets and check-ins.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class TicketStatus(StrEnum):
    ACTIVE = "active"
    ISSUED = "issued"
    USED = "used"
    CHECKED_IN = "checked_in"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    REVOKED = "revoked"


class AccessType(StrEnum):
    GENERAL = "general"
    VIP = "vip"
    STAFF = "staff"
    ORGANIZER = "organizer"
    MEDIA = "media"


class TicketTransferStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TicketValidationReason(StrEnum):
    VALID = "valid"
    WRONG_EVENT = "wrong_event"
    INVALID_SIGNATURE = "invalid_signature"
    UNKNOWN_TICKET = "unknown_ticket"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    ALREADY_USED = "already_used"
    ACCESS_DENIED = "access_denied"
    OUTSIDE_TIME_WINDOW = "outside_time_window"
    EVENT_ENDED = "event_ended"
    PAYMENT_NOT_VERIFIED = "payment_not_verified"
    REGISTRATION_NOT_CONFIRMED = "registration_not_confirmed"
    UNAUTHORIZED_STAFF = "unauthorized_staff"


class CheckInSource(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class AccessZone(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "access_zones"
    __table_args__ = (UniqueConstraint("event_id", "code", name="uq_access_zone_event_code"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AccessPolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "access_policies"
    __table_args__ = (UniqueConstraint("event_id", "access_type", name="uq_access_policy_event_type"),)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)
    access_type: Mapped[str] = mapped_column(String(40), nullable=False)
    allowed_zone_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    allows_reentry: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_entries: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_dates: Mapped[list | None] = mapped_column(JSON, default=None)


class Ticket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("ticket_code", name="uq_ticket_code"),
        UniqueConstraint("participant_id", name="uq_ticket_participant"),
        Index("ix_tickets_event_access_status", "event_id", "access_type", "status", "created_at"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    participant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("registration_participants.id"), default=None
    )
    # Nullable because a free (no-fee) event's registration never
    # creates a Payment row at all — see issue_ticket_for_registration()
    # in service.py, the code path that issues a ticket with no payment.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("payments.id"), default=None
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    ticket_code: Mapped[str] = mapped_column(String(80), nullable=False)
    barcode_payload: Mapped[str] = mapped_column(Text, nullable=False)
    barcode_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    access_type: Mapped[str] = mapped_column(String(40), default=AccessType.GENERAL.value, nullable=False)
    access_policy_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("access_policies.id"), default=None)
    entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    valid_dates: Mapped[list | None] = mapped_column(JSON, default=None)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus), default=TicketStatus.ACTIVE)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)

    check_ins: Mapped[list["CheckIn"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class CheckIn(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "check_ins"
    __table_args__ = (
        UniqueConstraint("ticket_id", "entry_number", name="uq_checkin_ticket_entry"),
        Index("uq_checkins_offline_batch_id", "offline_batch_id", unique=True, postgresql_where=text("offline_batch_id IS NOT NULL")),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tickets.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    scanned_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    source: Mapped[CheckInSource] = mapped_column(Enum(CheckInSource), default=CheckInSource.ONLINE)
    offline_batch_id: Mapped[str | None] = mapped_column(String(100), default=None)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    scan_payload: Mapped[str | None] = mapped_column(Text, default=None)
    entry_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    ticket: Mapped["Ticket"] = relationship(back_populates="check_ins")


class TicketTransfer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "ticket_transfers"
    __table_args__ = (
        Index("ix_ticket_transfers_recipient_status", "to_user_id", "status", "created_at"),
        Index("ix_ticket_transfers_ticket_pending", "ticket_id", unique=True, postgresql_where=text("status = 'PENDING'")),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tickets.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    from_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    to_user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    status: Mapped[TicketTransferStatus] = mapped_column(Enum(TicketTransferStatus), default=TicketTransferStatus.PENDING, nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
