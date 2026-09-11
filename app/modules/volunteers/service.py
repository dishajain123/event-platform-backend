import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_scoped_event_ids
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.config_engine.repository import EventConfigurationRepository
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.staff.service import StaffService
from app.modules.volunteers.models import (
    ALLOWED_VOLUNTEER_TRANSITIONS,
    VolunteerApplication,
    VolunteerApplicationStatus,
    VolunteerApplicationType,
)
from app.modules.volunteers.repository import VolunteerRepository


class VolunteerService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = VolunteerRepository(db)
        self.events = EventRepository(db)
        self.configurations = EventConfigurationRepository(db)

    async def _global_manage(self, actor: User) -> bool:
        return await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})

    async def _can_manage_event(self, actor: User, event_id: uuid.UUID) -> bool:
        return await self._global_manage(actor) or event_id in await user_scoped_event_ids(
            self.db, actor.id, {RoleName.EVENT_MANAGER}
        )

    async def _get_or_raise(self, application_id: uuid.UUID) -> VolunteerApplication:
        item = await self.repo.get(application_id)
        if item is None:
            raise NotFoundError("Volunteer application not found.")
        return item

    async def create_application(self, actor: User, payload: dict):
        event_id = payload.pop("event_id")
        application_type = payload.get("application_type", VolunteerApplicationType.VOLUNTEER)
        if await self.events.get_by_id(event_id) is None:
            raise ValidationError("Event not found.")
        config = await self.configurations.get_for_event(event_id)
        if config is None or not config.volunteer_open:
            raise ValidationError("This event is not accepting volunteer applications.")
        if await self.repo.get_for_user_event(actor.id, event_id, application_type):
            raise ConflictError("You have already applied to volunteer for this event.")
        payload.update(user_id=actor.id, event_id=event_id, phone=actor.mobile_number)
        item = await self.repo.create(**payload)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("You have already applied to volunteer for this event.") from exc
        await self.db.refresh(item)
        return item

    async def list_mine(self, actor: User):
        return await self.repo.list_for_user(actor.id)

    async def list_manageable(self, actor: User, event_id=None, status=None, search=None, application_type=None):
        if await self._global_manage(actor):
            event_ids = {event_id} if event_id else None
        else:
            event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
            if event_id is not None:
                if event_id not in event_ids:
                    raise PermissionDeniedError("You don't have permission to manage volunteers for this event.")
                event_ids = {event_id}
        return await self.repo.list_for_events(event_ids, status, search, application_type)

    async def page_manageable(self, actor: User, event_id=None, status=None, search=None, application_type=None, *, page=1, page_size=25):
        if await self._global_manage(actor):
            event_ids = {event_id} if event_id else None
        else:
            event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
            if event_id is not None:
                if event_id not in event_ids:
                    raise PermissionDeniedError("You don't have permission to manage volunteers for this event.")
                event_ids = {event_id}
        return await self.repo.page_for_events(event_ids, page=page, page_size=page_size, status=status, search=search, application_type=application_type)

    async def get_visible(self, actor: User, application_id: uuid.UUID):
        item = await self._get_or_raise(application_id)
        if item.user_id == actor.id or await self._can_manage_event(actor, item.event_id):
            return item
        raise PermissionDeniedError("You cannot access this volunteer application.")

    async def update_status(self, actor: User, application_id: uuid.UUID, status: VolunteerApplicationStatus):
        item = await self._get_or_raise(application_id)
        if not await self._can_manage_event(actor, item.event_id):
            raise PermissionDeniedError("You cannot manage this volunteer application.")
        if status not in ALLOWED_VOLUNTEER_TRANSITIONS[item.status]:
            raise ValidationError(f"Cannot move application from {item.status} to {status}.")
        item.status = status
        item.reviewed_by = actor.id
        item.reviewed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def activate(self, actor: User, application_id: uuid.UUID):
        item = await self._get_or_raise(application_id)
        if not await self._can_manage_event(actor, item.event_id):
            raise PermissionDeniedError("You cannot activate volunteers for this event.")
        if item.status != VolunteerApplicationStatus.APPROVED:
            raise ValidationError("Approve the application before activating the volunteer.")
        if item.activated_staff_assignment_id:
            raise ConflictError("This volunteer is already activated for the event.")
        user = await self.db.get(User, item.user_id)
        if user is None:
            raise NotFoundError("Volunteer applicant account not found.")
        if item.application_type == VolunteerApplicationType.EVENT_MANAGER:
            raise ValidationError("An admin must designate this account in Admin Accounts, then select it as the event's primary manager.")
        staff = StaffService(self.db)
        role_name = (
            RoleName.EVENT_MANAGER
            if item.application_type == VolunteerApplicationType.EVENT_MANAGER
            else RoleName.STAFF_MEMBER
        )
        role_label = "Event Manager" if item.application_type == VolunteerApplicationType.EVENT_MANAGER else "Volunteer"
        assignment = await staff.create_assignment(
            event_id=item.event_id, actor=actor, invitee_mobile=user.mobile_number,
            role_name=role_name, role_label=role_label, full_name=item.full_name,
        )
        activated = await staff.accept_assignment(assignment.id, user)
        item.activated_staff_assignment_id = activated.id
        await self.db.commit()
        await self.db.refresh(item)
        return item
