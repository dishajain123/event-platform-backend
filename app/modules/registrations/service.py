"""
Registration lifecycle and scope-aware access rules.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.registrations.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationStateError,
    RegistrationCapacityExceededError,
    RegistrationNotFoundError,
    RegistrationScopeError,
)
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository
from app.modules.rbac.models import RoleName
from app.modules.guardians.service import GuardianService


class RegistrationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.registrations = RegistrationRepository(db)
        self.events = EventRepository(db)
        self.config = ConfigEngineService(db)
        self.guardians = GuardianService(db)

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def _get_config_or_raise(self, event_id: uuid.UUID):
        config = await self.config.get_configuration(event_id)
        if config is None:
            raise InvalidRegistrationStateError("Event configuration is missing.")
        return config

    async def _ensure_capacity(self, event_id: uuid.UUID) -> None:
        config = await self._get_config_or_raise(event_id)
        if config.capacity is None:
            return
        active_count = await self.registrations.count_active_for_event(event_id)
        if active_count >= config.capacity:
            raise RegistrationCapacityExceededError("Registration capacity has been reached.")

    async def _ensure_no_duplicate(
        self,
        *,
        event_id: uuid.UUID,
        user_id: uuid.UUID,
        child_id: uuid.UUID | None,
        participation_type: str,
    ) -> None:
        duplicate = await self.registrations.find_duplicate(
            event_id=event_id,
            user_id=user_id,
            child_id=child_id,
            participation_type=participation_type,
        )
        if duplicate is not None:
            raise DuplicateRegistrationError("A registration already exists for this participant.")

    async def create_registration(
        self,
        *,
        event_id: uuid.UUID,
        actor: User,
        participation_type: str,
        date_of_birth=None,
        child_id: uuid.UUID | None = None,
        team_id: uuid.UUID | None = None,
        documents_provided: list[str],
        answers: dict,
        participants: list[dict],
        team_member_count: int | None = None,
    ) -> Registration:
        event = await self._get_event_or_raise(event_id)
        config = await self._get_config_or_raise(event_id)
        if participation_type not in config.participation_types:
            raise InvalidRegistrationStateError(
                f"Participation type '{participation_type}' is not enabled for this event."
            )

        if child_id is not None:
            await self.guardians.ensure_guardian_can_register_for_child(actor.id, child_id)

        if team_member_count is None:
            team_member_count = len(participants) or 1

        await self._ensure_no_duplicate(
            event_id=event_id,
            user_id=actor.id,
            child_id=child_id,
            participation_type=participation_type,
        )
        await self._ensure_capacity(event_id)

        is_valid, errors = await self.config.validate_registration(
            event_id,
            participation_type,
            date_of_birth,
            team_member_count,
            documents_provided,
            answers,
        )
        if not is_valid:
            message = "; ".join(error.message for error in errors)
            raise InvalidRegistrationStateError(message)

        registration = await self.registrations.create(
            event_id=event_id,
            user_id=actor.id,
            child_id=child_id,
            team_id=team_id,
            participation_type=participation_type,
            status=RegistrationStatus.STARTED,
            submitted_at=datetime.now(timezone.utc),
        )
        for participant in participants:
            await self.registrations.add_participant(
                registration_id=registration.id,
                user_id=actor.id if participant.get("is_captain") else None,
                full_name=participant["full_name"],
                date_of_birth=participant.get("date_of_birth"),
                is_captain=participant.get("is_captain", False),
            )

        if config.approval_required:
            registration.status = RegistrationStatus.PENDING_VERIFICATION
        elif config.fee_amount is not None and float(config.fee_amount) > 0:
            registration.status = RegistrationStatus.PENDING_PAYMENT
        else:
            registration.status = RegistrationStatus.APPROVED

        await write_audit_log(
            self.db,
            entity_type="registration",
            entity_id=registration.id,
            action="created",
            actor_user_id=actor.id,
            after_value={"event_id": str(event_id), "status": registration.status.value},
        )
        await self.db.commit()
        await self.db.refresh(registration)
        return registration

    async def get_registration_or_raise(self, registration_id: uuid.UUID) -> Registration:
        registration = await self.registrations.get_by_id(registration_id)
        if registration is None:
            raise RegistrationNotFoundError("Registration not found.")
        return registration

    async def list_registrations_for_actor(self, actor: User) -> list[Registration]:
        return await self.registrations.list_for_user(actor.id)

    async def list_registrations_for_event(self, event_id: uuid.UUID) -> list[Registration]:
        return await self.registrations.list_for_event(event_id)

    async def can_manage_registration(self, actor: User, registration: Registration) -> bool:
        if registration.user_id == actor.id:
            return True
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            registration.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def get_registration_visible_to_actor(
        self, actor: User, registration_id: uuid.UUID
    ) -> Registration:
        registration = await self.get_registration_or_raise(registration_id)
        if not await self.can_manage_registration(actor, registration):
            raise RegistrationScopeError("You cannot access this registration.")
        return registration

    async def decide_registration(
        self,
        registration_id: uuid.UUID,
        actor: User,
        approve: bool,
        reason: str | None = None,
    ) -> Registration:
        registration = await self.get_registration_visible_to_actor(actor, registration_id)
        if registration.status not in {
            RegistrationStatus.PENDING_VERIFICATION,
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.SUBMITTED,
            RegistrationStatus.STARTED,
        }:
            raise InvalidRegistrationStateError(
                f"Registration is already in '{registration.status.value}' and cannot be changed."
            )

        if approve:
            registration.status = RegistrationStatus.APPROVED
            registration.approved_by = actor.id
            registration.rejected_by = None
            registration.rejection_reason = None
            action = "approved"
        else:
            registration.status = RegistrationStatus.REJECTED
            registration.rejected_by = actor.id
            registration.rejection_reason = reason
            action = "rejected"

        await write_audit_log(
            self.db,
            entity_type="registration",
            entity_id=registration.id,
            action=action,
            actor_user_id=actor.id,
            after_value={"status": registration.status.value, "reason": reason},
        )
        await self.db.commit()
        await self.db.refresh(registration)
        return registration
