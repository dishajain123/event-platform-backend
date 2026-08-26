"""
Shared SQLAlchemy declarative base and mixins.

Every model in every module inherits from Base plus whichever mixins
it needs — this is what guarantees every table in the platform has a
UUID primary key and created_at/updated_at without repeating that
boilerplate in seventeen different models.py files.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# SQLAlchemy's dialect-agnostic Uuid type: renders as native UUID on
# Postgres in production, and as CHAR(32) on SQLite for fast local tests —
# same model code works against both without an if/else anywhere.
UUIDType = Uuid(as_uuid=True)


class UUIDPrimaryKeyMixin:
    """Every table uses a UUID primary key, generated application-side."""

    id: Mapped[uuid.UUID] = mapped_column(UUIDType, primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """created_at is set once; updated_at is refreshed on every update."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SoftDeleteMixin:
    """Rows are never hard-deleted where history/audit matters — flagged instead."""

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None