import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
        stmt = (
            select(Event)
            .options(
                selectinload(Event.main_category),
                selectinload(Event.sub_category),
                selectinload(Event.organizer),
                selectinload(Event.configuration),
            )
            .where(Event.id == event_id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_public(
        self,
        min_status: EventStatus = EventStatus.PUBLISHED,
        *,
        main_category_id: uuid.UUID | None = None,
        sub_category_id: uuid.UUID | None = None,
    ) -> list[Event]:
        """Used by the mobile app — only events at PUBLISHED or later are visible."""
        visible_statuses = [
            EventStatus.PUBLISHED,
            EventStatus.REGISTRATION_OPEN,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.LIVE,
            EventStatus.COMPLETED,
        ]
        stmt = select(Event).options(
            selectinload(Event.main_category),
            selectinload(Event.sub_category),
            selectinload(Event.organizer),
            selectinload(Event.configuration),
        )
        stmt = stmt.where(Event.status.in_(visible_statuses))
        if main_category_id is not None:
            stmt = stmt.where(Event.main_category_id == main_category_id)
        if sub_category_id is not None:
            stmt = stmt.where(Event.sub_category_id == sub_category_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_all(
        self,
        *,
        main_category_id: uuid.UUID | None = None,
        sub_category_id: uuid.UUID | None = None,
    ) -> list[Event]:
        """Used by the console — every status is visible."""
        stmt = select(Event).options(
            selectinload(Event.main_category),
            selectinload(Event.sub_category),
            selectinload(Event.organizer),
            selectinload(Event.configuration),
        )
        if main_category_id is not None:
            stmt = stmt.where(Event.main_category_id == main_category_id)
        if sub_category_id is not None:
            stmt = stmt.where(Event.sub_category_id == sub_category_id)
        result = await self.db.execute(stmt)
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
