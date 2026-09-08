"""
Business logic for events: lifecycle transitions (validated against
ALLOWED_TRANSITIONS — no route or caller can push an event into an
invalid state), plus venue/schedule management.
"""
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.event_categories.exceptions import (
    InvalidCategoryRelationshipError,
    MainCategoryNotFoundError,
    SubCategoryNotFoundError,
)
from app.modules.event_categories.repository import MainCategoryRepository, SubCategoryRepository
from app.modules.config_engine.registration_state import (
    RegistrationAvailability,
    calculate_registration_availability,
    parse_registration_end_at,
)
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError, InvalidEventStatusTransitionError, ScheduleConflictError, SponsorNotFoundError, VenueNotFoundError
from app.modules.events.models import ALLOWED_TRANSITIONS, Event, EventStatus, EventTemplate, ScheduleStatus
from app.modules.events.repository import EventRepository, EventTemplateRepository, ScheduleRepository, SponsorRepository, VenueRepository
from app.modules.identity.repository import UserRepository
from app.modules.identity.models import User
from app.modules.rbac.models import AssignmentStatus, Role, RoleAssignment, RoleName
from app.modules.config_engine.models import EventConfiguration, EventFieldSchema
from app.modules.tickets.models import AccessPolicy, AccessZone


class EventService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.events = EventRepository(db)
        self.templates = EventTemplateRepository(db)
        self.venues = VenueRepository(db)
        self.schedule = ScheduleRepository(db)
        self.sponsors = SponsorRepository(db)
        self.main_categories = MainCategoryRepository(db)
        self.sub_categories = SubCategoryRepository(db)
        self.users = UserRepository(db)
        self.configurations = ConfigEngineService(db)

    async def _resolve_category_fields(
        self,
        *,
        main_category_id: uuid.UUID | None = None,
        sub_category_id: uuid.UUID | None = None,
        require_sub_category: bool = True,
        allow_inactive: bool = False,
    ) -> dict[str, uuid.UUID | str | None]:
        if main_category_id is None and sub_category_id is None:
            return {
                "main_category_id": None,
                "sub_category_id": None,
                "category": None,
            }

        main_category = None
        sub_category = None

        if main_category_id is not None:
            main_category = await self.main_categories.get_by_id(main_category_id)
            if main_category is None:
                raise MainCategoryNotFoundError("Main category not found.")
            if not allow_inactive and not main_category.is_active:
                raise InvalidCategoryRelationshipError("The selected main category is inactive.")

        if sub_category_id is not None:
            sub_category = await self.sub_categories.get_by_id(sub_category_id)
            if sub_category is None:
                raise SubCategoryNotFoundError("Sub category not found.")
            if not allow_inactive and not sub_category.is_active:
                raise InvalidCategoryRelationshipError("The selected sub category is inactive.")
            if main_category is None:
                main_category = await self.main_categories.get_by_id(sub_category.main_category_id)
                if main_category is None:
                    raise MainCategoryNotFoundError("Main category not found.")
                if not allow_inactive and not main_category.is_active:
                    raise InvalidCategoryRelationshipError("The selected main category is inactive.")
            elif sub_category.main_category_id != main_category.id:
                raise InvalidCategoryRelationshipError(
                    "The selected sub category does not belong to the selected main category."
                )
        elif require_sub_category and main_category is not None:
            raise InvalidCategoryRelationshipError("Select a sub category for the selected main category.")

        return {
            "main_category_id": main_category.id if main_category else None,
            "sub_category_id": sub_category.id if sub_category else None,
            "category": sub_category.name if sub_category else (main_category.name if main_category else None),
        }

    async def create_event(self, *, created_by: uuid.UUID, **fields) -> Event:
        self._validate_event_dates(fields.get("start_date"), fields.get("end_date"))
        legacy_category = fields.pop("category", None)
        organizer_user_id = fields.get("organizer_user_id")
        if organizer_user_id is not None:
            organizer = await self.users.get_by_id(organizer_user_id)
            if organizer is None:
                raise ValidationError("Selected organizer account does not exist.")
            if not organizer.is_active:
                raise ValidationError("Selected organizer account is inactive.")
        category_fields = await self._resolve_category_fields(
            main_category_id=fields.pop("main_category_id", None),
            sub_category_id=fields.pop("sub_category_id", None),
            require_sub_category=True,
        )
        if legacy_category is not None and category_fields["category"] is None:
            category_fields["category"] = legacy_category
        fields.update(category_fields)
        event = await self.events.create(created_by=created_by, **fields)
        await write_audit_log(
            self.db,
            entity_type="event",
            entity_id=event.id,
            action="created",
            actor_user_id=created_by,
            after_value={
                "name": event.name,
                "status": event.status.value,
                "main_category_id": str(event.main_category_id) if event.main_category_id else None,
                "sub_category_id": str(event.sub_category_id) if event.sub_category_id else None,
                "organizer_user_id": str(event.organizer_user_id) if event.organizer_user_id else None,
            },
        )
        await self.db.commit()
        return await self.get_event_or_raise(event.id)

    @staticmethod
    def _validate_event_dates(start_date, end_date):
        if start_date is None or end_date is None or end_date <= start_date:
            raise ValidationError("Event end date must be after its start date.")

    async def _can_manage_event(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db, actor.id, {RoleName.EVENT_MANAGER}, event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    @staticmethod
    def _shift_datetime(value: str, delta: timedelta) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")) + delta

    @classmethod
    def _shift_detail_dates(cls, details: dict, delta: timedelta) -> dict:
        shifted = dict(details or {})
        for key in ("registration_end_at", "cancellation_deadline_at"):
            value = shifted.get(key)
            if value:
                try:
                    shifted[key] = (datetime.fromisoformat(str(value).replace("Z", "+00:00")) + delta).isoformat()
                except ValueError as exc:
                    raise ValidationError(f"Template contains an invalid {key} value.") from exc
        return shifted

    async def _template_snapshot(self, event_id: uuid.UUID) -> dict:
        event = await self.get_event_or_raise(event_id)
        config = await self.configurations.get_configuration(event_id)
        fields = (await self.db.execute(select(EventFieldSchema).where(EventFieldSchema.event_id == event_id))).scalars().all()
        venues = await self.venues.list_for_event(event_id)
        schedules = await self.schedule.list_for_event(event_id)
        zones = (await self.db.execute(select(AccessZone).where(AccessZone.event_id == event_id))).scalars().all()
        policies = (await self.db.execute(select(AccessPolicy).where(AccessPolicy.event_id == event_id))).scalars().all()
        return {
            "version": 1,
            "source_start_date": event.start_date.isoformat(),
            "event": {
                "description": event.description,
                "category": event.category,
                "main_category_id": str(event.main_category_id) if event.main_category_id else None,
                "sub_category_id": str(event.sub_category_id) if event.sub_category_id else None,
                "organization_id": str(event.organization_id) if event.organization_id else None,
            },
            "configuration": {
                "participation_types": list(config.participation_types),
                "fee_amount": str(config.fee_amount) if config.fee_amount is not None else None,
                "currency": config.currency,
                "capacity": config.capacity,
                "volunteer_open": config.volunteer_open,
                "approval_required": config.approval_required,
                "details": dict(config.details or {}),
                "rules": dict(config.rules or {}),
                "discount_rules": config.discount_rules,
            } if config else None,
            "field_schemas": [{"participation_type": item.participation_type, "fields": item.fields} for item in fields],
            "venues": [{"source_id": str(item.id), "name": item.name, "address": item.address, "latitude": item.latitude, "longitude": item.longitude, "capacity": item.capacity, "availability": item.availability or [], "is_shared": item.is_shared} for item in venues],
            "schedules": [{"venue_source_id": str(item.venue_id) if item.venue_id else None, "title": item.title, "start_time": item.start_time.isoformat(), "end_time": item.end_time.isoformat() if item.end_time else None, "resource_key": item.resource_key, "expected_capacity": item.expected_capacity, "status": item.status.value} for item in schedules if item.status == ScheduleStatus.SCHEDULED],
            "access_zones": [{"source_id": str(item.id), "code": item.code, "name": item.name, "is_active": item.is_active} for item in zones],
            "access_policies": [{"access_type": item.access_type, "allowed_zone_ids": [str(value) for value in (item.allowed_zone_ids or [])], "allows_reentry": item.allows_reentry, "max_entries": item.max_entries, "valid_from": item.valid_from.isoformat() if item.valid_from else None, "valid_until": item.valid_until.isoformat() if item.valid_until else None} for item in policies],
        }

    async def create_template(self, actor: User, *, name: str, description: str | None, source_event_id: uuid.UUID):
        if not await self._can_manage_event(actor, source_event_id):
            raise PermissionDeniedError("You cannot create a template from this event.")
        source = await self.get_event_or_raise(source_event_id)
        template = await self.templates.create(owner_user_id=actor.id, organization_id=source.organization_id, source_event_id=source_event_id, name=name, description=description, snapshot=await self._template_snapshot(source_event_id))
        await write_audit_log(self.db, entity_type="event_template", entity_id=template.id, action="created", actor_user_id=actor.id, after_value={"source_event_id": str(source_event_id), "name": name})
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def _get_visible_template(self, actor: User, template_id: uuid.UUID):
        template = await self.templates.get(template_id)
        if template is None:
            raise NotFoundError("Event template not found.")
        if await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            return template
        assigned = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        if template.owner_user_id != actor.id and (template.source_event_id is None or template.source_event_id not in assigned):
            raise PermissionDeniedError("You cannot access this event template.")
        return template

    async def list_templates(self, actor: User, *, search=None, include_archived=False, page=1, page_size=25):
        if await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            return await self.templates.page(search=search, include_archived=include_archived, page=page, page_size=page_size)
        assigned = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        return await self.templates.page(owner_user_id=actor.id, source_event_ids=assigned, search=search, include_archived=include_archived, page=page, page_size=page_size)

    async def update_template(self, actor: User, template_id: uuid.UUID, **fields):
        template = await self._get_visible_template(actor, template_id)
        if template.owner_user_id != actor.id and not await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            raise PermissionDeniedError("Only the template owner or Operations can update this template.")
        before = {key: getattr(template, key) for key in fields}
        for key, value in fields.items():
            if value is not None or key == "description":
                setattr(template, key, value)
        await write_audit_log(self.db, entity_type="event_template", entity_id=template.id, action="updated", actor_user_id=actor.id, before_value=before, after_value=fields)
        await self.db.commit()
        await self.db.refresh(template)
        return template

    async def archive_template(self, actor: User, template_id: uuid.UUID):
        template = await self._get_visible_template(actor, template_id)
        if template.owner_user_id != actor.id and not await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            raise PermissionDeniedError("Only the template owner or Operations can archive this template.")
        template.is_archived = True
        await write_audit_log(self.db, entity_type="event_template", entity_id=template.id, action="archived", actor_user_id=actor.id)
        await self.db.commit()
        return template

    async def delete_template(self, actor: User, template_id: uuid.UUID):
        template = await self._get_visible_template(actor, template_id)
        if not template.is_archived:
            raise ConflictError("Archive the template before deleting it.")
        if template.owner_user_id != actor.id and not await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            raise PermissionDeniedError("Only the template owner or Operations can delete this template.")
        await write_audit_log(self.db, entity_type="event_template", entity_id=template.id, action="deleted", actor_user_id=actor.id)
        await self.db.delete(template)
        await self.db.commit()

    async def _clone_snapshot(self, actor: User, snapshot: dict, *, name: str, start_date: datetime, end_date: datetime, organization_id: uuid.UUID | None = None):
        self._validate_event_dates(start_date, end_date)
        source_start = datetime.fromisoformat(snapshot["source_start_date"].replace("Z", "+00:00"))
        delta = start_date - source_start
        event_data = snapshot["event"]
        category_fields = await self._resolve_category_fields(main_category_id=uuid.UUID(event_data["main_category_id"]) if event_data.get("main_category_id") else None, sub_category_id=uuid.UUID(event_data["sub_category_id"]) if event_data.get("sub_category_id") else None, require_sub_category=False)
        event = await self.events.create(created_by=actor.id, organizer_user_id=actor.id, organization_id=organization_id or (uuid.UUID(event_data["organization_id"]) if event_data.get("organization_id") else None), name=name, description=event_data.get("description"), start_date=start_date, end_date=end_date, status=EventStatus.DRAFT, **category_fields)
        if not await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}):
            manager_role = (await self.db.execute(select(Role).where(Role.name == RoleName.EVENT_MANAGER))).scalar_one()
            self.db.add(RoleAssignment(user_id=actor.id, role_id=manager_role.id, event_id=event.id, assigned_by=actor.id, status=AssignmentStatus.ACTIVE))
        config_data = snapshot.get("configuration")
        if config_data:
            self.db.add(EventConfiguration(event_id=event.id, participation_types=list(config_data.get("participation_types") or []), fee_amount=config_data.get("fee_amount"), currency=config_data.get("currency", "INR"), capacity=config_data.get("capacity"), volunteer_open=config_data.get("volunteer_open", True), approval_required=config_data.get("approval_required", False), details=self._shift_detail_dates(config_data.get("details") or {}, delta), rules=dict(config_data.get("rules") or {}), discount_rules=config_data.get("discount_rules")))
        for item in snapshot.get("field_schemas", []):
            self.db.add(EventFieldSchema(event_id=event.id, participation_type=item["participation_type"], fields=item.get("fields") or []))
        venue_map = {}
        for item in snapshot.get("venues", []):
            source_id = item["source_id"]
            if item.get("is_shared"):
                shared = await self.venues.get_by_id(uuid.UUID(source_id))
                if shared is None or not shared.is_shared:
                    raise ValidationError("A shared venue in the template is no longer available.")
                venue_map[source_id] = shared.id
            else:
                venue = await self.venues.create(event.id, name=item["name"], address=item.get("address"), latitude=item.get("latitude"), longitude=item.get("longitude"), capacity=item.get("capacity"), availability=item.get("availability") or [], is_shared=False)
                venue_map[source_id] = venue.id
        for item in snapshot.get("schedules", []):
            fields = {"venue_id": venue_map.get(item.get("venue_source_id")) if item.get("venue_source_id") else None, "title": item["title"], "start_time": self._shift_datetime(item["start_time"], delta), "end_time": self._shift_datetime(item["end_time"], delta) if item.get("end_time") else None, "resource_key": item.get("resource_key"), "expected_capacity": item.get("expected_capacity")}
            await self._validate_schedule(event, fields)
            await self.schedule.create(event.id, **fields)
        zone_map = {}
        for item in snapshot.get("access_zones", []):
            zone = AccessZone(event_id=event.id, code=item["code"], name=item["name"], is_active=item.get("is_active", True))
            self.db.add(zone)
            await self.db.flush()
            zone_map[item["source_id"]] = zone.id
        for item in snapshot.get("access_policies", []):
            self.db.add(AccessPolicy(event_id=event.id, access_type=item["access_type"], allowed_zone_ids=[str(zone_map[value]) for value in item.get("allowed_zone_ids", []) if value in zone_map], allows_reentry=item.get("allows_reentry", False), max_entries=item.get("max_entries", 1), valid_from=self._shift_datetime(item["valid_from"], delta) if item.get("valid_from") else None, valid_until=self._shift_datetime(item["valid_until"], delta) if item.get("valid_until") else None))
        return event

    async def duplicate_event(self, actor: User, source_event_id: uuid.UUID, *, name: str, start_date: datetime, end_date: datetime):
        if not await self._can_manage_event(actor, source_event_id):
            raise PermissionDeniedError("You cannot duplicate this event.")
        source = await self.get_event_or_raise(source_event_id)
        event = await self._clone_snapshot(actor, await self._template_snapshot(source.id), name=name, start_date=start_date, end_date=end_date, organization_id=source.organization_id)
        await write_audit_log(self.db, entity_type="event", entity_id=event.id, action="duplicated", actor_user_id=actor.id, after_value={"source_event_id": str(source.id)})
        await self.db.commit()
        return await self.get_event_or_raise(event.id)

    async def create_event_from_template(self, actor: User, template_id: uuid.UUID, *, name: str, start_date: datetime, end_date: datetime):
        template = await self._get_visible_template(actor, template_id)
        event = await self._clone_snapshot(actor, template.snapshot, name=name, start_date=start_date, end_date=end_date, organization_id=template.organization_id)
        await write_audit_log(self.db, entity_type="event", entity_id=event.id, action="created_from_template", actor_user_id=actor.id, after_value={"template_id": str(template.id)})
        await self.db.commit()
        return await self.get_event_or_raise(event.id)

    async def get_event_or_raise(self, event_id: uuid.UUID) -> Event:
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        await self._synchronize_registration_state(event)
        return event

    async def _synchronize_registration_state(self, event: Event) -> None:
        config = event.configuration
        if config is None:
            return
        registered_count = await self.configurations.registrations.count_active_for_event(event.id)
        availability = calculate_registration_availability(
            event_status=event.status,
            capacity=config.capacity,
            registered_count=registered_count,
            registration_end_at=parse_registration_end_at(config.details),
        )
        if event.status == EventStatus.REGISTRATION_OPEN and availability in {
            RegistrationAvailability.CLOSED,
            RegistrationAvailability.FULL,
        }:
            event.status = EventStatus.REGISTRATION_CLOSED
            await self.db.commit()

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
        } and (
            (event.main_category is None or event.main_category.is_active)
            and (
                event.sub_category is None
                or (
                    event.sub_category.is_active
                    and event.main_category_id == event.sub_category.main_category_id
                )
            )
        ):
            return event

        raise PermissionDeniedError("You don't have permission to view this event.")

    async def update_event(self, event_id: uuid.UUID, actor_user_id: uuid.UUID, **fields) -> Event:
        event = await self.get_event_or_raise(event_id)
        before = {
            "name": event.name,
            "description": event.description,
            "organizer_user_id": str(event.organizer_user_id) if event.organizer_user_id else None,
            "main_category_id": str(event.main_category_id) if event.main_category_id else None,
            "sub_category_id": str(event.sub_category_id) if event.sub_category_id else None,
        }
        legacy_category = fields.pop("category", None)
        communication_fields = {"name", "description", "start_date", "end_date"}
        event_changed = bool(communication_fields.intersection(fields))
        if "organizer_user_id" in fields and fields["organizer_user_id"] is not None:
            organizer = await self.users.get_by_id(fields["organizer_user_id"])
            if organizer is None:
                raise ValidationError("Selected organizer account does not exist.")
            if not organizer.is_active:
                raise ValidationError("Selected organizer account is inactive.")
        if "main_category_id" in fields or "sub_category_id" in fields:
            category_fields = await self._resolve_category_fields(
                main_category_id=fields.pop("main_category_id", event.main_category_id),
                sub_category_id=fields.pop("sub_category_id", event.sub_category_id),
                require_sub_category=False,
            )
            if category_fields["main_category_id"] is not None and category_fields["sub_category_id"] is None:
                raise InvalidCategoryRelationshipError("Select a sub category for the selected main category.")
            fields.update(category_fields)
        elif legacy_category is not None:
            fields["category"] = legacy_category
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
            after_value={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in fields.items() if v is not None},
        )
        await self.db.commit()
        if event_changed:
            from app.modules.notifications.service import NotificationService

            await NotificationService(self.db).queue_event_change(
                event.id, reason="The event schedule or details were updated."
            )
        return await self.get_event_or_raise(event.id)

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
        from app.modules.notifications.service import NotificationService

        await NotificationService(self.db).queue_event_change(
            event.id, reason=f"The event status is now {new_status.value.replace('_', ' ')}."
        )
        return await self.get_event_or_raise(event.id)

    async def publish(self, event_id: uuid.UUID, actor_user_id: uuid.UUID) -> Event:
        return await self.transition_status(event_id, EventStatus.PUBLISHED, actor_user_id)

    async def list_events(
        self,
        *,
        include_all_statuses: bool,
        main_category_id: uuid.UUID | None = None,
        sub_category_id: uuid.UUID | None = None,
    ) -> list[Event]:
        category_fields = await self._resolve_category_fields(
            main_category_id=main_category_id,
            sub_category_id=sub_category_id,
            require_sub_category=False,
            allow_inactive=include_all_statuses,
        )
        if include_all_statuses:
            events = await self.events.list_all(
                main_category_id=category_fields["main_category_id"],
                sub_category_id=category_fields["sub_category_id"],
            )
        else:
            events = await self.events.list_public(
                main_category_id=category_fields["main_category_id"],
                sub_category_id=category_fields["sub_category_id"],
            )
        for event in events:
            await self._synchronize_registration_state(event)
        return events

    async def page_events(self, *, include_all_statuses, main_category_id=None, sub_category_id=None, search=None, status=None, page=1, page_size=25):
        events, total = await self.events.page_all(include_all_statuses=include_all_statuses, main_category_id=main_category_id, sub_category_id=sub_category_id, search=search, status=status, page=page, page_size=page_size)
        for event in events:
            await self._synchronize_registration_state(event)
        return events, total

    async def to_response(self, event: Event):
        """Build an EventOut with live capacity/deadline metrics."""
        from app.modules.events.schemas import EventOut

        response = EventOut.model_validate(event)
        if event.configuration is not None:
            configuration = await self.configurations.configuration_response(
                event.id, event.configuration
            )
            response = response.model_copy(update={"configuration": configuration})
        return response

    # ---- Venues ----

    async def add_venue(self, event_id: uuid.UUID, **fields):
        await self.get_event_or_raise(event_id)
        venue = await self.venues.create(event_id, **fields)
        await self.db.commit()
        return venue

    async def update_venue(self, event_id: uuid.UUID, venue_id: uuid.UUID, **fields):
        await self.get_event_or_raise(event_id)
        venue = await self.venues.get_for_event(event_id, venue_id)
        if venue is None:
            raise VenueNotFoundError("Venue not found for this event.")
        if fields.get("capacity") is not None:
            items, _ = await self.schedule.page_for_event(event_id, page=1, page_size=100, status=ScheduleStatus.SCHEDULED)
            if any(item.expected_capacity and item.expected_capacity > fields["capacity"] for item in items if item.venue_id == venue_id):
                raise ScheduleConflictError("Venue capacity is below an existing scheduled slot.", details={"reason_code": "CAPACITY_EXCEEDED", "conflict_type": "venue_capacity", "requested_capacity": fields["capacity"]})
        for key, value in fields.items():
            setattr(venue, key, value)
        await self.db.commit()
        await self.db.refresh(venue)
        return venue

    async def list_venues(self, event_id: uuid.UUID):
        return await self.venues.list_for_event(event_id)

    async def list_assignable_venues(self, event_id: uuid.UUID):
        await self.get_event_or_raise(event_id)
        return await self.venues.list_assignable(event_id)

    # ---- Schedule ----

    @staticmethod
    def _parse_availability(value):
        if not value:
            return []
        windows = []
        for window in value:
            try:
                start = datetime.fromisoformat(str(window["start_time"]).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(window["end_time"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValidationError("Venue availability windows must contain valid start_time and end_time.") from exc
            if end <= start:
                raise ValidationError("Venue availability window end must be after its start.")
            windows.append((start, end))
        return windows

    async def _validate_schedule(self, event: Event, fields: dict, *, exclude_id: uuid.UUID | None = None):
        start, end = fields.get("start_time"), fields.get("end_time")
        if start is None or end is None or end <= start:
            raise ScheduleConflictError("Schedule start and end must be provided, with end after start.", details={"reason_code": "INVALID_TIME_RANGE", "conflict_type": "time_range", "requested_start_time": start.isoformat() if start else None, "requested_end_time": end.isoformat() if end else None})
        if start < event.start_date or end > event.end_date:
            raise ScheduleConflictError("Schedule must fall within the event time range.", details={"reason_code": "INVALID_TIME_RANGE", "conflict_type": "event_window", "requested_start_time": start.isoformat(), "requested_end_time": end.isoformat()})
        venue_id = fields.get("venue_id")
        if venue_id is not None:
            venue = await self.venues.get_by_id(venue_id)
            if venue is None or (venue.event_id != event.id and not venue.is_shared):
                raise VenueNotFoundError("Venue is not available to this event.")
            if venue.capacity is not None and fields.get("expected_capacity") is not None and fields["expected_capacity"] > venue.capacity:
                raise ScheduleConflictError("Expected attendance exceeds venue capacity.", details={"reason_code": "CAPACITY_EXCEEDED", "conflict_type": "venue_capacity", "conflicting_venue_id": str(venue.id), "requested_start_time": start.isoformat(), "requested_end_time": end.isoformat()})
            windows = self._parse_availability(venue.availability)
            if windows and not any(start >= window_start and end <= window_end for window_start, window_end in windows):
                raise ScheduleConflictError("Requested schedule falls outside venue availability.", details={"reason_code": "VENUE_UNAVAILABLE", "conflict_type": "venue_availability", "conflicting_venue_id": str(venue.id), "requested_start_time": start.isoformat(), "requested_end_time": end.isoformat()})
        await self.schedule.lock_conflict_scope(venue_id=venue_id, resource_key=fields.get("resource_key"))
        conflicts = await self.schedule.find_overlapping(venue_id=venue_id, resource_key=fields.get("resource_key"), start_time=start, end_time=end, exclude_id=exclude_id)
        if conflicts:
            item, conflict_event, _ = conflicts[0]
            reason_code = "VENUE_OVERLAP" if venue_id is not None and item.venue_id == venue_id else "RESOURCE_OVERLAP"
            raise ScheduleConflictError(
                f"Schedule conflicts with {conflict_event.name} from {item.start_time.isoformat()} to {item.end_time.isoformat()}.",
                details={"reason_code": reason_code, "conflict_type": "venue" if reason_code == "VENUE_OVERLAP" else "resource", "conflicting_event_id": str(conflict_event.id), "conflicting_event_name": conflict_event.name, "conflicting_schedule_id": str(item.id), "existing_start_time": item.start_time.isoformat(), "existing_end_time": item.end_time.isoformat(), "requested_start_time": start.isoformat(), "requested_end_time": end.isoformat()},
            )

    async def add_schedule_item(self, event_id: uuid.UUID, *, actor_user_id: uuid.UUID | None = None, **fields):
        event = await self.get_event_or_raise(event_id)
        await self._validate_schedule(event, fields)
        item = await self.schedule.create(event_id, **fields)
        await write_audit_log(self.db, entity_type="schedule", entity_id=item.id, action="created", actor_user_id=actor_user_id, after_value={"event_id": str(event_id), "start_time": fields["start_time"].isoformat(), "end_time": fields["end_time"].isoformat()})
        await self.db.commit()
        return item

    async def update_schedule_item(self, event_id: uuid.UUID, schedule_id: uuid.UUID, *, actor_user_id: uuid.UUID | None = None, **fields):
        event = await self.get_event_or_raise(event_id)
        item = await self.schedule.get_for_event(event_id, schedule_id)
        if item is None:
            raise ValidationError("Schedule item not found for this event.")
        if item.status == ScheduleStatus.CANCELLED:
            raise ValidationError("Cancelled schedule items cannot be rescheduled.")
        merged = {"venue_id": item.venue_id, "title": item.title, "start_time": item.start_time, "end_time": item.end_time, "resource_key": item.resource_key, "expected_capacity": item.expected_capacity}
        merged.update(fields)
        await self._validate_schedule(event, merged, exclude_id=item.id)
        for key, value in merged.items():
            setattr(item, key, value)
        await write_audit_log(self.db, entity_type="schedule", entity_id=item.id, action="rescheduled", actor_user_id=actor_user_id, after_value={"event_id": str(event_id), "start_time": item.start_time.isoformat(), "end_time": item.end_time.isoformat()})
        await self.db.commit()
        return item

    async def cancel_schedule_item(self, event_id: uuid.UUID, schedule_id: uuid.UUID, *, actor_user_id: uuid.UUID | None = None):
        await self.get_event_or_raise(event_id)
        item = await self.schedule.get_for_event(event_id, schedule_id)
        if item is None:
            raise ValidationError("Schedule item not found for this event.")
        item.status = ScheduleStatus.CANCELLED
        await write_audit_log(self.db, entity_type="schedule", entity_id=item.id, action="cancelled", actor_user_id=actor_user_id, after_value={"event_id": str(event_id)})
        await self.db.commit()
        return item

    async def delete_schedule_item(self, event_id: uuid.UUID, schedule_id: uuid.UUID, *, actor_user_id: uuid.UUID | None = None):
        await self.get_event_or_raise(event_id)
        item = await self.schedule.get_for_event(event_id, schedule_id)
        if item is None:
            raise ValidationError("Schedule item not found for this event.")
        if item.status != ScheduleStatus.CANCELLED:
            raise ValidationError("Cancel a schedule before deleting it.")
        await self.db.delete(item)
        await write_audit_log(self.db, entity_type="schedule", entity_id=schedule_id, action="deleted", actor_user_id=actor_user_id, after_value={"event_id": str(event_id)})
        await self.db.commit()

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
