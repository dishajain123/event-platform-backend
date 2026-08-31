"""
Tickets and check-ins.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class TicketStatus(StrEnum):
    ISSUED = "issued"
    CHECKED_IN = "checked_in"
    CANCELLED = "cancelled"


class CheckInSource(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"


class Ticket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("registration_id", name="uq_ticket_registration"),
        UniqueConstraint("ticket_code", name="uq_ticket_code"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("registrations.id"), nullable=False
    )
    # Nullable because a free (no-fee) event's registration never
    # creates a Payment row at all — see issue_ticket_for_registration()
    # in service.py, the code path that issues a ticket with no payment.
    payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("payments.id"), default=None
    )
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    ticket_code: Mapped[str] = mapped_column(String(80), nullable=False)
    qr_payload: Mapped[str] = mapped_column(Text, nullable=False)
    qr_signature: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(Enum(TicketStatus), default=TicketStatus.ISSUED)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    checked_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    checked_in_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)

    check_ins: Mapped[list["CheckIn"]] = relationship(back_populates="ticket", cascade="all, delete-orphan")


class CheckIn(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "check_ins"
    __table_args__ = (UniqueConstraint("ticket_id", name="uq_checkin_ticket"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("tickets.id"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    venue_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("venues.id"), default=None)
    scanned_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    source: Mapped[CheckInSource] = mapped_column(Enum(CheckInSource), default=CheckInSource.ONLINE)
    offline_batch_id: Mapped[str | None] = mapped_column(String(100), default=None)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    scan_payload: Mapped[str | None] = mapped_column(Text, default=None)

    ticket: Mapped["Ticket"] = relationship(back_populates="check_ins")