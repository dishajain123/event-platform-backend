import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.concurrency import acquire_event_capacity_lock
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.exceptions import PermissionDeniedError
from app.modules.config_engine.registration_state import calculate_registration_availability, parse_registration_end_at
from app.modules.config_engine.repository import EventConfigurationRepository
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES
from app.modules.registrations.repository import RegistrationRepository
from app.modules.guardians.service import GuardianService
from app.modules.teams.repository import TeamRepository
from app.modules.waitlists.exceptions import WaitlistConflictError, WaitlistNotFoundError, WaitlistPermissionError, WaitlistValidationError
from app.modules.waitlists.models import ACTIVE_WAITLIST_STATUSES, WaitlistEntry, WaitlistStatus
from app.modules.waitlists.repository import WaitlistRepository


class WaitlistService:
    PROMOTION_MINUTES = 24 * 60

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = WaitlistRepository(db)
        self.events = EventRepository(db)
        self.configs = EventConfigurationRepository(db)
        self.registrations = RegistrationRepository(db)
        self.guardians = GuardianService(db)
        self.teams = TeamRepository(db)

    async def _global(self, actor: User) -> bool:
        return await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})

    async def _can_manage(self, actor: User, event_id: uuid.UUID) -> bool:
        return await self._global(actor) or await user_has_scoped_role(
            self.db, actor.id, {RoleName.EVENT_MANAGER}, event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def _event_config(self, event_id):
        event = await self.events.get_by_id(event_id)
        config = await self.configs.get_for_event(event_id)
        if event is None or config is None:
            raise WaitlistValidationError("Event configuration was not found.")
        return event, config

    async def _expire_locked(self, now: datetime) -> list[WaitlistEntry]:
        expired = await self.repo.expired_promotions(now)
        for entry in expired:
            entry.status = WaitlistStatus.EXPIRED
            entry.expired_at = now
            await write_audit_log(self.db, entity_type="waitlist", entity_id=entry.id, action="expired", actor_user_id=None, after_value={"event_id": str(entry.event_id)})
            await self._notify(entry, "promotion_expired")
        return expired

    async def _notify(self, entry: WaitlistEntry, kind: str) -> None:
        from app.modules.notifications.models import NotificationChannel, NotificationDeliveryStatus
        from app.modules.notifications.repository import NotificationRepository

        titles = {
            "joined": "You joined the waitlist",
            "promoted": "A place is available",
            "promotion_expired": "Your waitlist offer expired",
            "left": "You left the waitlist",
            "position_changed": "Your waitlist position changed",
            "closed": "The event waitlist is closed",
        }
        bodies = {
            "joined": "You are now in the event waitlist. We will notify you if a place becomes available.",
            "promoted": "A place is available. Complete registration before your promotion offer expires.",
            "promotion_expired": "Your waitlist promotion expired. You may join the waitlist again if it is still open.",
            "left": "You have been removed from the event waitlist.",
            "position_changed": "Your position changed because another waitlist entry was removed.",
            "closed": "Registration for this event has closed, so this waitlist is no longer active.",
        }
        dedupe_key = f"waitlist:{entry.id}:{kind}"
        if kind == "position_changed":
            dedupe_key = f"{dedupe_key}:{datetime.now(timezone.utc).isoformat()}"
        notification = await NotificationRepository(self.db).create(
            event_id=entry.event_id, recipient_user_id=entry.user_id,
            channel=NotificationChannel.PUSH, title=titles[kind], body=bodies[kind],
            target_metadata={"waitlist_id": str(entry.id), "event_id": str(entry.event_id), "action": kind, "position": await self._position(entry) if kind == "position_changed" else None, "deep_link": f"/events/{entry.event_id}/register" if kind == "promoted" else None},
            delivery_status=NotificationDeliveryStatus.QUEUED,
            notification_type="waitlist", dedupe_key=dedupe_key,
        )
        return notification

    async def _close_waiting(self, event_id: uuid.UUID) -> int:
        closed = 0
        while True:
            entries, _ = await self.repo.waiting_page(
                event_ids={event_id}, status=WaitlistStatus.WAITING,
                page=1, page_size=100,
            )
            if not entries:
                break
            for entry in entries:
                entry.status = WaitlistStatus.CLOSED
                await write_audit_log(
                    self.db, entity_type="waitlist", entity_id=entry.id,
                    action="closed", actor_user_id=None,
                    after_value={"event_id": str(event_id)},
                )
                await self._notify(entry, "closed")
                closed += 1
            if len(entries) < 100:
                break
        return closed

    async def _position(self, entry: WaitlistEntry) -> int | None:
        if entry.status != WaitlistStatus.WAITING:
            return None
        return await self.repo.count_waiting_before(entry) + 1

    async def _out(self, entry: WaitlistEntry):
        from app.modules.waitlists.schemas import WaitlistOut
        return WaitlistOut.model_validate(entry).model_copy(update={"position": await self._position(entry)})

    async def join(self, actor: User, event_id: uuid.UUID, participation_type: str, child_id=None, team_id=None):
        event, config = await self._event_config(event_id)
        if participation_type not in config.participation_types:
            raise WaitlistValidationError("This participation type is not enabled for the event.")
        if child_id is not None:
            await self.guardians.ensure_guardian_can_register_for_child(actor.id, child_id)
        if participation_type == "team":
            if team_id is None:
                raise WaitlistValidationError("A team waitlist entry must reference a team.")
            team = await self.teams.get_by_id(team_id)
            if team is None or team.event_id != event_id or team.captain_user_id != actor.id:
                raise WaitlistValidationError("You cannot join this team's event waitlist.")
        elif team_id is not None:
            raise WaitlistValidationError("Only team entries may reference a team.")
        now = datetime.now(timezone.utc)
        await acquire_event_capacity_lock(self.db, event_id)
        # Re-check capacity after locking so a concurrent registration or
        # cancellation cannot make the waitlist eligibility decision stale.
        availability = calculate_registration_availability(
            event_status=event.status, capacity=config.capacity,
            registered_count=await self.registrations.count_active_for_event(event_id),
            registration_end_at=parse_registration_end_at(config.details), now=now,
        )
        if availability != "full":
            raise WaitlistValidationError("The event is accepting registrations; join the waitlist after it reaches capacity.")
        existing = await self.repo.find_active(event_id=event_id, user_id=actor.id, child_id=child_id, team_id=team_id, participation_type=participation_type)
        if existing is not None:
            raise WaitlistConflictError("You are already on this waitlist.")
        entry = await self.repo.create(event_id=event_id, user_id=actor.id, child_id=child_id, team_id=team_id, participation_type=participation_type, status=WaitlistStatus.WAITING, joined_at=now)
        await write_audit_log(self.db, entity_type="waitlist", entity_id=entry.id, action="joined", actor_user_id=actor.id, after_value={"event_id": str(event_id), "participation_type": participation_type})
        await self._notify(entry, "joined")
        await self.db.commit()
        return await self._out(entry)

    async def leave(self, actor: User, entry_id: uuid.UUID):
        entry = await self.repo.get(entry_id)
        if entry is None:
            raise WaitlistNotFoundError("Waitlist entry not found.")
        if entry.user_id != actor.id and not await self._can_manage(actor, entry.event_id):
            raise WaitlistPermissionError("You cannot modify this waitlist entry.")
        if entry.status not in ACTIVE_WAITLIST_STATUSES:
            raise WaitlistValidationError("This waitlist entry is no longer active.")
        await acquire_event_capacity_lock(self.db, entry.event_id)
        entry.status = WaitlistStatus.LEFT
        entry.left_at = datetime.now(timezone.utc)
        page = 1
        while True:
            remaining, _ = await self.repo.waiting_page(
                event_ids={entry.event_id},
                participation_type=entry.participation_type,
                status=WaitlistStatus.WAITING,
                page=page,
                page_size=100,
            )
            for remaining_entry in remaining:
                await self._notify(remaining_entry, "position_changed")
            if len(remaining) < 100:
                break
            page += 1
        await write_audit_log(self.db, entity_type="waitlist", entity_id=entry.id, action="left", actor_user_id=actor.id, after_value={"event_id": str(entry.event_id)})
        await self._notify(entry, "left")
        await self.db.commit()
        return await self._out(entry)

    async def promote_next(self, event_id: uuid.UUID, participation_type: str | None = None):
        await acquire_event_capacity_lock(self.db, event_id)
        now = datetime.now(timezone.utc)
        await self._expire_locked(now)
        event, config = await self._event_config(event_id)
        if config.capacity is None:
            return None
        active_count = await self.registrations.count_active_for_event(event_id)
        availability = calculate_registration_availability(
            event_status=event.status, capacity=config.capacity,
            registered_count=active_count,
            registration_end_at=parse_registration_end_at(config.details), now=now,
        )
        if availability == "closed":
            await self._close_waiting(event_id)
            return None
        if availability not in {"open", "limited"}:
            return None
        if participation_type is None:
            # FIFO across participation types when a generic seat is released.
            entry = (await self.repo.waiting_page(event_ids={event_id}, status=WaitlistStatus.WAITING, page=1, page_size=1))[0]
            entry = entry[0] if entry else None
        else:
            entry = await self.repo.next_waiting(event_id, participation_type)
        if entry is None:
            return None
        timeout = int((config.details or {}).get("waitlist_promotion_timeout_minutes", self.PROMOTION_MINUTES))
        entry.status = WaitlistStatus.PROMOTED
        entry.promoted_at = now
        entry.promotion_expires_at = now + timedelta(minutes=max(1, min(timeout, 7 * 24 * 60)))
        await write_audit_log(self.db, entity_type="waitlist", entity_id=entry.id, action="promoted", actor_user_id=None, after_value={"event_id": str(event_id), "expires_at": entry.promotion_expires_at.isoformat()})
        await self._notify(entry, "promoted")
        return entry

    async def retry(self, actor: User, entry_id: uuid.UUID):
        entry = await self.repo.get(entry_id)
        if entry is None:
            raise WaitlistNotFoundError("Waitlist entry not found.")
        if not await self._can_manage(actor, entry.event_id):
            raise WaitlistPermissionError("You cannot retry this waitlist entry.")
        if entry.status != WaitlistStatus.EXPIRED:
            raise WaitlistValidationError("Only expired waitlist offers can be retried.")
        await acquire_event_capacity_lock(self.db, entry.event_id)
        event, config = await self._event_config(entry.event_id)
        availability = calculate_registration_availability(
            event_status=event.status, capacity=config.capacity,
            registered_count=await self.registrations.count_active_for_event(entry.event_id),
            registration_end_at=parse_registration_end_at(config.details),
            now=datetime.now(timezone.utc),
        )
        if availability not in {"full", "limited"}:
            raise WaitlistValidationError("This event no longer needs a waitlist offer.")
        entry.status = WaitlistStatus.WAITING
        entry.joined_at = datetime.now(timezone.utc)
        entry.expired_at = None
        entry.promoted_at = None
        entry.promotion_expires_at = None
        await write_audit_log(self.db, entity_type="waitlist", entity_id=entry.id, action="retry", actor_user_id=actor.id, after_value={"event_id": str(entry.event_id)})
        await self._notify(entry, "joined")
        await self.db.commit()
        return await self._out(entry)

    async def expire_and_promote(self):
        now = datetime.now(timezone.utc)
        expired = await self._expire_locked(now)
        promoted = 0
        event_ids = set(await self.repo.event_ids_with_waiting())
        event_ids.update(entry.event_id for entry in expired)
        for event_id in event_ids:
            if await self.promote_next(event_id):
                promoted += 1
        if expired or promoted:
            await self.db.commit()
        return promoted

    async def list_mine(self, actor: User, *, page=1, page_size=25):
        items, total = await self.repo.waiting_page(event_ids=None, user_id=actor.id, page=page, page_size=page_size)
        return [await self._out(entry) for entry in items], total

    async def page_manageable(self, actor: User, *, event_id=None, status=None, participation_type=None, search=None, page=1, page_size=25):
        if await self._global(actor):
            event_ids = None
        else:
            event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
            if event_id is not None and event_id not in event_ids:
                raise WaitlistPermissionError("You don't have permission to manage this event waitlist.")
        items, total = await self.repo.waiting_page(event_ids=event_ids, event_id=event_id, status=status, participation_type=participation_type, search=search, page=page, page_size=page_size)
        return [await self._out(entry) for entry in items], total
