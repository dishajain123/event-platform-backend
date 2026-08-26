"""
Media uploads and editorial highlights for an event.
"""
import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class MediaType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    OTHER = "other"


class Media(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "media"

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    uploaded_by: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, default=None)
    category: Mapped[str | None] = mapped_column(String(100), default=None)
    media_type: Mapped[MediaType] = mapped_column(Enum(MediaType), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    public_url: Mapped[str] = mapped_column(String(500), nullable=False)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUIDType, ForeignKey("users.id"), default=None)

    highlight: Mapped["Highlight | None"] = relationship(
        back_populates="media", cascade="all, delete-orphan", uselist=False
    )


class Highlight(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "highlights"
    __table_args__ = (UniqueConstraint("media_id", name="uq_highlight_media"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    media_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("media.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0)

    media: Mapped["Media"] = relationship(back_populates="highlight")
