"""
Business logic for events: lifecycle transitions (validated against
ALLOWED_TRANSITIONS — no route or caller can push an event into an
invalid state), plus venue/schedule management.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.events.exceptions import EventNotFoundError, InvalidEventStatusTransitionError
from app.modules.events.models import ALLOWED_TRANSITIONS, Event, EventStatus
from app.modules.events.repository import EventRepository, ScheduleRepository, VenueRepository


class EventService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventRepository(db)
        self.venues = VenueRepository(db)
        self.schedule = ScheduleRepository(db)

    async def create_event(self, *, created_by: uuid.UUID, **fields) -> Event:
        event = await self.events.create(created_by=created_by, **fields)
        await write_audit_log(
            self.db,
            entity_type="event",
            entity_id=event.id,
            action="created",
            actor_user_id=created_by,
            after_value={"name": event.name, "status": event.status.value},
        )
        await self.db.commit()
        return event

    async def get_event_or_raise(self, event_id: uuid.UUID) -> Event:
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def update_event(self, event_id: uuid.UUID, actor_user_id: uuid.UUID, **fields) -> Event:
        event = await self.get_event_or_raise(event_id)
        before = {"name": event.name, "description": event.description}
        for key, value in fields.items():
            if value is not None:
                setattr(event, key, value)
        await write_audit_log(
            self.db,
            entity_type="event",
            entity_id=event.id,
            action="updated",
            actor_user_id=actor_user_id,
            before_value=before,
            after_value={k: v for k, v in fields.items() if v is not None},
        )
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def transition_status(
        self, event_id: uuid.UUID, new_status: EventStatus, actor_user_id: uuid.UUID
    ) -> Event:
        event = await self.get_event_or_raise(event_id)
        allowed_next = ALLOWED_TRANSITIONS.get(event.status, set())
        if new_status not in allowed_next:
            raise InvalidEventStatusTransitionError(
                f"Cannot move an event from '{event.status.value}' to '{new_status.value}'. "
                f"Valid next states are: {[s.value for s in allowed_next] or 'none (terminal state)'}."
            )
        old_status = event.status
        event.status = new_status
        await write_audit_log(
            self.db,
            entity_type="event",
            entity_id=event.id,
            action="status_changed",
            actor_user_id=actor_user_id,
            before_value={"status": old_status.value},
            after_value={"status": new_status.value},
        )
        await self.db.commit()
        await self.db.refresh(event)
        return event

    async def publish(self, event_id: uuid.UUID, actor_user_id: uuid.UUID) -> Event:
        return await self.transition_status(event_id, EventStatus.PUBLISHED, actor_user_id)

    async def list_events(self, *, include_all_statuses: bool) -> list[Event]:
        if include_all_statuses:
            return await self.events.list_all()
        return await self.events.list_public()

    # ---- Venues ----

    async def add_venue(self, event_id: uuid.UUID, **fields):
        await self.get_event_or_raise(event_id)
        venue = await self.venues.create(event_id, **fields)
        await self.db.commit()
        return venue

    async def list_venues(self, event_id: uuid.UUID):
        return await self.venues.list_for_event(event_id)

    # ---- Schedule ----

    async def add_schedule_item(self, event_id: uuid.UUID, **fields):
        await self.get_event_or_raise(event_id)
        item = await self.schedule.create(event_id, **fields)
        await self.db.commit()
        return item

    async def list_schedule(self, event_id: uuid.UUID):
        return await self.schedule.list_for_event(event_id)