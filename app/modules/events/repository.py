import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.events.models import Event, EventStatus, ScheduleItem, Sponsor, Venue


class EventRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Event:
        event = Event(**kwargs)
        self.db.add(event)
        await self.db.flush()
        return event

    async def get_by_id(self, event_id: uuid.UUID) -> Event | None:
        return await self.db.get(Event, event_id)

    async def list_public(self, min_status: EventStatus = EventStatus.PUBLISHED) -> list[Event]:
        """Used by the mobile app — only events at PUBLISHED or later are visible."""
        visible_statuses = [
            EventStatus.PUBLISHED,
            EventStatus.REGISTRATION_OPEN,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.LIVE,
            EventStatus.COMPLETED,
        ]
        result = await self.db.execute(select(Event).where(Event.status.in_(visible_statuses)))
        return list(result.scalars().all())

    async def list_all(self) -> list[Event]:
        """Used by the console — every status is visible."""
        result = await self.db.execute(select(Event))
        return list(result.scalars().all())


class VenueRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, event_id: uuid.UUID, **kwargs) -> Venue:
        venue = Venue(event_id=event_id, **kwargs)
        self.db.add(venue)
        await self.db.flush()
        return venue

    async def list_for_event(self, event_id: uuid.UUID) -> list[Venue]:
        result = await self.db.execute(select(Venue).where(Venue.event_id == event_id))
        return list(result.scalars().all())


class ScheduleRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, event_id: uuid.UUID, **kwargs) -> ScheduleItem:
        item = ScheduleItem(event_id=event_id, **kwargs)
        self.db.add(item)
        await self.db.flush()
        return item

    async def list_for_event(self, event_id: uuid.UUID) -> list[ScheduleItem]:
        result = await self.db.execute(
            select(ScheduleItem).where(ScheduleItem.event_id == event_id)
        )
        return list(result.scalars().all())


class SponsorRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, event_id: uuid.UUID, **kwargs) -> Sponsor:
        sponsor = Sponsor(event_id=event_id, **kwargs)
        self.db.add(sponsor)
        await self.db.flush()
        return sponsor

    async def list_for_event(self, event_id: uuid.UUID) -> list[Sponsor]:
        result = await self.db.execute(
            select(Sponsor).where(Sponsor.event_id == event_id).order_by(Sponsor.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, sponsor_id: uuid.UUID) -> Sponsor | None:
        return await self.db.get(Sponsor, sponsor_id)

    async def delete(self, sponsor: Sponsor) -> None:
        await self.db.delete(sponsor)
