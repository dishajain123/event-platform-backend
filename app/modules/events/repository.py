import uuid

from sqlalchemy import and_, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus, EventTemplate, ScheduleItem, ScheduleStatus, Sponsor, SponsorStatus, Venue


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
            .execution_options(populate_existing=True)
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
        stmt = stmt.where(Event.status.in_(visible_statuses)).execution_options(
            populate_existing=True
        )
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
        stmt = stmt.execution_options(populate_existing=True)
        if main_category_id is not None:
            stmt = stmt.where(Event.main_category_id == main_category_id)
        if sub_category_id is not None:
            stmt = stmt.where(Event.sub_category_id == sub_category_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def page_all(self, *, include_all_statuses: bool, main_category_id=None, sub_category_id=None, search=None, status=None, page=1, page_size=25):
        filters = []
        if not include_all_statuses:
            filters.append(Event.status.in_([EventStatus.PUBLISHED, EventStatus.REGISTRATION_OPEN, EventStatus.REGISTRATION_CLOSED, EventStatus.LIVE, EventStatus.COMPLETED]))
        if main_category_id is not None:
            filters.append(Event.main_category_id == main_category_id)
        if sub_category_id is not None:
            filters.append(Event.sub_category_id == sub_category_id)
        if status is not None:
            filters.append(Event.status == status)
        if search:
            filters.append(Event.name.ilike(f"%{search.strip()}%"))
        total = await self.db.scalar(select(func.count(Event.id)).where(*filters)) or 0
        stmt = select(Event).options(selectinload(Event.main_category), selectinload(Event.sub_category), selectinload(Event.organizer), selectinload(Event.configuration)).where(*filters)
        result = await self.db.execute(stmt.order_by(Event.created_at.desc(), Event.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total


class EventTemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields) -> EventTemplate:
        template = EventTemplate(**fields)
        self.db.add(template)
        await self.db.flush()
        return template

    async def get(self, template_id: uuid.UUID) -> EventTemplate | None:
        return await self.db.get(EventTemplate, template_id)

    async def page(self, *, owner_user_id=None, source_event_ids=None, search=None, include_archived=False, page=1, page_size=25):
        filters = []
        if owner_user_id is not None and source_event_ids is not None:
            if not source_event_ids:
                filters.append(EventTemplate.owner_user_id == owner_user_id)
            else:
                filters.append(or_(EventTemplate.owner_user_id == owner_user_id, EventTemplate.source_event_id.in_(source_event_ids)))
        elif owner_user_id is not None:
            filters.append(EventTemplate.owner_user_id == owner_user_id)
        elif source_event_ids is not None:
            if not source_event_ids:
                return [], 0
            filters.append(EventTemplate.source_event_id.in_(source_event_ids))
        if not include_archived:
            filters.append(EventTemplate.is_archived.is_(False))
        if search:
            term = f"%{search.strip()}%"
            filters.append(EventTemplate.name.ilike(term) | EventTemplate.description.ilike(term))
        total = int(await self.db.scalar(select(func.count(EventTemplate.id)).where(*filters)) or 0)
        result = await self.db.execute(
            select(EventTemplate).where(*filters)
            .order_by(EventTemplate.created_at.desc(), EventTemplate.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total


class VenueRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, event_id: uuid.UUID, **kwargs) -> Venue:
        venue = Venue(event_id=event_id, **kwargs)
        self.db.add(venue)
        await self.db.flush()
        return venue

    async def list_for_event(self, event_id: uuid.UUID) -> list[Venue]:
        result = await self.db.execute(select(Venue).where(Venue.event_id == event_id).order_by(Venue.name.asc(), Venue.id.asc()))
        return list(result.scalars().all())

    async def list_assignable(self, event_id: uuid.UUID) -> list[Venue]:
        result = await self.db.execute(select(Venue).where((Venue.event_id == event_id) | (Venue.is_shared.is_(True))).order_by(Venue.name.asc(), Venue.id.asc()))
        return list(result.scalars().all())

    async def get_for_event(self, event_id: uuid.UUID, venue_id: uuid.UUID) -> Venue | None:
        result = await self.db.execute(select(Venue).where(Venue.id == venue_id, Venue.event_id == event_id))
        return result.scalar_one_or_none()

    async def get_by_id(self, venue_id: uuid.UUID) -> Venue | None:
        result = await self.db.execute(select(Venue).where(Venue.id == venue_id))
        return result.scalar_one_or_none()


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
            select(ScheduleItem).where(ScheduleItem.event_id == event_id).order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        )
        return list(result.scalars().all())

    async def get_for_event(self, event_id: uuid.UUID, schedule_id: uuid.UUID) -> ScheduleItem | None:
        result = await self.db.execute(select(ScheduleItem).where(ScheduleItem.id == schedule_id, ScheduleItem.event_id == event_id))
        return result.scalar_one_or_none()

    async def page_for_event(self, event_id: uuid.UUID, *, page=1, page_size=25, status=None, search=None):
        filters = [ScheduleItem.event_id == event_id]
        if status is not None:
            filters.append(ScheduleItem.status == status)
        if search:
            filters.append(ScheduleItem.title.ilike(f"%{search.strip()}%"))
        total = await self.db.scalar(select(func.count(ScheduleItem.id)).where(*filters)) or 0
        result = await self.db.execute(select(ScheduleItem).where(*filters).order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), int(total)

    async def lock_conflict_scope(self, *, venue_id: uuid.UUID | None, resource_key: str | None) -> None:
        bind = self.db.sync_session.bind
        if bind is None or bind.dialect.name != "postgresql":
            return
        keys = [f"venue:{venue_id}" if venue_id else None, f"resource:{resource_key}" if resource_key else None]
        for key in filter(None, keys):
            await self.db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    async def find_overlapping(self, *, venue_id: uuid.UUID | None, resource_key: str | None, start_time, end_time, exclude_id: uuid.UUID | None = None):
        filters = [
            ScheduleItem.status != ScheduleStatus.CANCELLED,
            ScheduleItem.start_time < end_time,
            ScheduleItem.end_time > start_time,
        ]
        if exclude_id is not None:
            filters.append(ScheduleItem.id != exclude_id)
        scopes = []
        if venue_id is not None:
            scopes.append(ScheduleItem.venue_id == venue_id)
        if resource_key:
            scopes.append(ScheduleItem.resource_key == resource_key)
        if not scopes:
            return []
        result = await self.db.execute(
            select(ScheduleItem, Event, Venue)
            .join(Event, Event.id == ScheduleItem.event_id)
            .outerjoin(Venue, Venue.id == ScheduleItem.venue_id)
            .where(and_(*filters), *scopes)
            .order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc())
        )
        return list(result.all())


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
            select(Sponsor)
            .where(
                Sponsor.event_id == event_id,
                Sponsor.status.in_([SponsorStatus.CONFIRMED, SponsorStatus.ACTIVE]),
            )
            .order_by(Sponsor.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_id(self, sponsor_id: uuid.UUID) -> Sponsor | None:
        return await self.db.get(Sponsor, sponsor_id)

    async def delete(self, sponsor: Sponsor) -> None:
        await self.db.delete(sponsor)
