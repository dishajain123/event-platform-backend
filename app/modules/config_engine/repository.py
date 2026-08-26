import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.config_engine.models import EventConfiguration, EventFieldSchema


class EventConfigurationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_event(self, event_id: uuid.UUID) -> EventConfiguration | None:
        result = await self.db.execute(
            select(EventConfiguration).where(EventConfiguration.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def upsert(self, event_id: uuid.UUID, **fields) -> EventConfiguration:
        existing = await self.get_for_event(event_id)
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
            await self.db.flush()
            return existing
        config = EventConfiguration(event_id=event_id, **fields)
        self.db.add(config)
        await self.db.flush()
        return config


class EventFieldSchemaRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_event_and_type(
        self, event_id: uuid.UUID, participation_type: str
    ) -> EventFieldSchema | None:
        result = await self.db.execute(
            select(EventFieldSchema).where(
                EventFieldSchema.event_id == event_id,
                EventFieldSchema.participation_type == participation_type,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, event_id: uuid.UUID, participation_type: str, fields: list[dict]
    ) -> EventFieldSchema:
        existing = await self.get_for_event_and_type(event_id, participation_type)
        if existing:
            existing.fields = fields
            await self.db.flush()
            return existing
        schema = EventFieldSchema(event_id=event_id, participation_type=participation_type, fields=fields)
        self.db.add(schema)
        await self.db.flush()
        return schema