"""
Business logic for events: lifecycle transitions (validated against
ALLOWED_TRANSITIONS — no route or caller can push an event into an
invalid state), plus venue/schedule management.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.events.exceptions import EventNotFoundError, InvalidEventStatusTransitionError, SponsorNotFoundError
from app.modules.events.models import ALLOWED_TRANSITIONS, Event, EventStatus
from app.modules.events.repository import EventRepository, ScheduleRepository, SponsorRepository, VenueRepository
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName


class EventService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventRepository(db)
        self.venues = VenueRepository(db)
        self.schedule = ScheduleRepository(db)
        self.sponsors = SponsorRepository(db)

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

    async def get_event_visible_to_actor(self, event_id: uuid.UUID, actor: User | None) -> Event:
        event = await self.get_event_or_raise(event_id)

        if actor is not None:
            if await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
                return event
            if await user_has_scoped_role(
                self.db,
                actor.id,
                {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR},
                event_id,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            ):
                return event

        if event.status in {
            EventStatus.PUBLISHED,
            EventStatus.REGISTRATION_OPEN,
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.LIVE,
            EventStatus.COMPLETED,
        }:
            return event

        raise PermissionDeniedError("You don't have permission to view this event.")

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

    # ---- Sponsors ----

    async def list_sponsors(self, event_id: uuid.UUID):
        await self.get_event_or_raise(event_id)
        return await self.sponsors.list_for_event(event_id)

    async def add_sponsor(self, event_id: uuid.UUID, **fields):
        await self.get_event_or_raise(event_id)
        sponsor = await self.sponsors.create(event_id, **fields)
        await self.db.commit()
        await self.db.refresh(sponsor)
        return sponsor

    async def delete_sponsor(self, event_id: uuid.UUID, sponsor_id: uuid.UUID) -> None:
        await self.get_event_or_raise(event_id)
        sponsor = await self.sponsors.get_by_id(sponsor_id)
        if sponsor is None or sponsor.event_id != event_id:
            raise SponsorNotFoundError("Sponsor not found.")
        await self.sponsors.delete(sponsor)
        await self.db.commit()
