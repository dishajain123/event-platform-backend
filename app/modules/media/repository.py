"""Data access for media and highlights."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.media.models import Highlight, Media


class MediaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Media:
        media = Media(**kwargs)
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_by_id(self, media_id: uuid.UUID) -> Media | None:
        # BUG FIX: was `self.db.get(Media, media_id)`, which does not
        # eager-load relationships. MediaOut serializes `highlight`, and
        # accessing that lazy-loaded relationship outside an active
        # async context (FastAPI's post-request response serialization)
        # raises MissingGreenlet — same root cause as the identical fix
        # in registrations/repository.py.
        result = await self.db.execute(
            select(Media).options(selectinload(Media.highlight)).where(Media.id == media_id)
        )
        return result.scalar_one_or_none()

    async def list_for_event(self, event_id: uuid.UUID) -> list[Media]:
        result = await self.db.execute(
            select(Media).options(selectinload(Media.highlight)).where(Media.event_id == event_id)
        )
        return list(result.scalars().all())

    async def list_published_for_event(self, event_id: uuid.UUID) -> list[Media]:
        result = await self.db.execute(
            select(Media)
            .options(selectinload(Media.highlight))
            .where(Media.event_id == event_id, Media.is_published.is_(True))
        )
        return list(result.scalars().all())


class HighlightRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Highlight:
        highlight = Highlight(**kwargs)
        self.db.add(highlight)
        await self.db.flush()
        return highlight

    async def get_by_media_id(self, media_id: uuid.UUID) -> Highlight | None:
        result = await self.db.execute(select(Highlight).where(Highlight.media_id == media_id))
        return result.scalar_one_or_none()

    async def list_for_event(self, event_id: uuid.UUID) -> list[Highlight]:
        result = await self.db.execute(
            select(Highlight).where(Highlight.event_id == event_id, Highlight.is_active.is_(True))
        )
        return list(result.scalars().all())