import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class WaitlistStatus(StrEnum):
    WAITING = "waiting"
    PROMOTED = "promoted"
    EXPIRED = "expired"
    LEFT = "left"
    CLOSED = "closed"


ACTIVE_WAITLIST_STATUSES = {WaitlistStatus.WAITING, WaitlistStatus.PROMOTED}


class WaitlistEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "waitlist_entries"
    __table_args__ = (
        UniqueConstraint(
            "event_id", "user_id", "child_id", "team_id", "participation_type",
            "status", name="uq_waitlist_active_identity",
        ),
        Index(
            "ix_waitlist_entries_fifo",
            "event_id", "participation_type", "status", "joined_at", "id",
        ),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False, index=True)
    child_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("child_profiles.id"), default=None)
    team_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("teams.id"), default=None)
    participation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[WaitlistStatus] = mapped_column(Enum(WaitlistStatus), default=WaitlistStatus.WAITING, nullable=False, index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    promotion_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
