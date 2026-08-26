"""Data access for media and highlights."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
        return await self.db.get(Media, media_id)

    async def list_for_event(self, event_id: uuid.UUID) -> list[Media]:
        result = await self.db.execute(select(Media).where(Media.event_id == event_id))
        return list(result.scalars().all())

    async def list_published_for_event(self, event_id: uuid.UUID) -> list[Media]:
        result = await self.db.execute(
            select(Media).where(Media.event_id == event_id, Media.is_published.is_(True))
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
