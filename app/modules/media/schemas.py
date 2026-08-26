"""Pydantic contracts for media and highlights."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.media.models import MediaType


class HighlightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    media_id: uuid.UUID
    title: str
    description: str | None
    is_active: bool
    display_order: int
    created_at: datetime
    updated_at: datetime


class MediaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    uploaded_by: uuid.UUID
    title: str
    caption: str | None
    category: str | None
    media_type: MediaType
    storage_key: str
    public_url: str
    is_published: bool
    sort_order: int
    published_at: datetime | None
    published_by: uuid.UUID | None
    highlight: HighlightOut | None = None
    created_at: datetime
    updated_at: datetime


class MediaUploadIn(BaseModel):
    title: str
    caption: str | None = None
    category: str | None = None
    media_type: MediaType
    source_url: str | None = None
    sort_order: int = 0
    is_highlight: bool = False
    highlight_title: str | None = None
    highlight_description: str | None = None
    highlight_order: int = 0


class MediaPublishIn(BaseModel):
    is_published: bool = True


class HighlightCreateIn(BaseModel):
    title: str
    description: str | None = None
    display_order: int = 0
