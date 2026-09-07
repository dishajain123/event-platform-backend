"""
Registration lifecycle and scope-aware access rules.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.concurrency import acquire_event_capacity_lock
from app.core.permissions import user_has_scoped_role
from app.modules.config_engine.service import ConfigEngineService
from app.modules.config_engine.registration_state import (
    RegistrationAvailability,
    calculate_registration_availability,
    parse_cancellation_deadline_at,
    parse_registration_end_at,
)
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
from app.modules.events.models import EventStatus
from app.modules.registrations.repository import RegistrationRepository
from app.modules.rbac.models import RoleName
from app.modules.guardians.service import GuardianService
from app.modules.teams.repository import TeamRepository


logger = logging.getLogger(__name__)


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

    async def page_registrations(
        self,
        event_ids: set[uuid.UUID] | None,
        *,
        page: int,
        page_size: int,
        search: str | None = None,
        status=None,
        participation_type: str | None = None,
    ):
        return await self.registrations.page_for_events(
            event_ids,
            page=page,
            page_size=page_size,
            search=search,
            status=status,
            participation_type=participation_type,
        )

    async def _get_config_or_raise(self, event_id: uuid.UUID):
        config = await self.config.get_configuration(event_id)
        if config is None:
            raise InvalidRegistrationStateError("Event configuration is missing.")
        return config

    async def _ensure_registration_open(self, event, config) -> None:
        active_count = await self.registrations.count_active_for_event(event.id)
        registration_end_at = parse_registration_end_at(config.details)
        now = datetime.now(timezone.utc)
        if registration_end_at is not None and now >= registration_end_at:
            if event.status == EventStatus.REGISTRATION_OPEN:
                event.status = EventStatus.REGISTRATION_CLOSED
                await self.db.commit()
            raise InvalidRegistrationStateError("Registration is closed for this event.")
        if event.status in {
            EventStatus.REGISTRATION_CLOSED,
            EventStatus.LIVE,
            EventStatus.COMPLETED,
            EventStatus.ARCHIVED,
        }:
            raise InvalidRegistrationStateError("Registration is closed for this event.")
        availability = calculate_registration_availability(
            event_status=event.status,
            capacity=config.capacity,
            registered_count=active_count,
            registration_end_at=registration_end_at,
        )
        if availability == RegistrationAvailability.FULL:
            event.status = EventStatus.REGISTRATION_CLOSED
            await self.db.commit()
            raise RegistrationCapacityExceededError("Registration capacity has been reached.")

    async def _ensure_capacity(self, event_id: uuid.UUID) -> None:
        """
        Checked while holding this event's advisory capacity lock (see
        create_registration) — the COUNT() here is only race-safe because
        no other concurrent registration for this same event_id can be
        running its own capacity check or insert at the same time.
        """
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

        if participation_type == "team":
            if team_id is None:
                raise InvalidRegistrationStateError("A team registration must reference a team.")
            team = await TeamRepository(self.db).get_by_id(team_id)
            if team is None or team.event_id != event_id or team.captain_user_id != actor.id:
                raise InvalidRegistrationStateError("You cannot register this team for the event.")
        elif team_id is not None:
            raise InvalidRegistrationStateError("Only team registrations may reference a team.")

        # BUG FIX: team_member_count must only ever be meaningful for
        # participation_type == "team" — it was previously defaulted to
        # len(participants) or 1 for EVERY participation type, which meant
        # any event configuring a team_size rule (needed to support team
        # registrations at all) would incorrectly apply that same rule to
        # every individual/viewer registration too, since 1 < min_size
        # spuriously failed the check. Only team registrations pass a
        # real team_member_count through to the rule engine; everything
        # else passes None, which the rule engine already correctly
        # treats as "no team_size check applies."
        if participation_type == "team":
            if team_member_count is None:
                team_member_count = len(participants) or 1
        else:
            team_member_count = None

        # Serializes everything below, for THIS event only, against any
        # other concurrent registration attempt for the same event —
        # closes the race window between "check capacity/duplicates" and
        # "actually insert the registration." Released automatically when
        # this method's transaction commits (or rolls back) below.
        await acquire_event_capacity_lock(self.db, event_id)

        await self._ensure_registration_open(event, config)
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
            cancellation_deadline_at=parse_cancellation_deadline_at(config.details),
        )
        for participant in participants:
            await self.registrations.add_participant(
                registration_id=registration.id,
                user_id=participant.get("user_id") or (actor.id if participant.get("is_captain") else None),
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

        capacity_warning_notifications = []
        active_count = None
        # Close the event in the same transaction when this registration
        # consumes the final active seat.
        if config.capacity is not None:
            active_count = await self.registrations.count_active_for_event(event_id)
            if active_count >= config.capacity:
                event.status = EventStatus.REGISTRATION_CLOSED
            elif active_count / config.capacity >= 0.8:
                try:
                    from app.modules.notifications.service import NotificationService

                    capacity_warning_notifications = await NotificationService(
                        self.db
                    ).queue_capacity_warning(
                        event_id=event_id,
                        registered_count=active_count,
                        capacity=config.capacity,
                    )
                except Exception:
                    # Registration success must not depend on an external
                    # notification provider or an inbox write.
                    logger.exception("Unable to queue capacity warning for event %s", event_id)

        await write_audit_log(
            self.db,
            entity_type="registration",
            entity_id=registration.id,
            action="created",
            actor_user_id=actor.id,
            after_value={"event_id": str(event_id), "status": registration.status.value},
        )

        # BUG FIX: a free (no-fee), no-approval-required registration
        # previously never received a ticket at all — ticket issuance
        # was only ever wired to the payment webhook, a path a free
        # event's registration never touches. Without this, check-in
        # via barcode scan was completely impossible for any free event.
        if registration.status == RegistrationStatus.APPROVED and (
            config.fee_amount is None or float(config.fee_amount) == 0
        ):
            from app.modules.tickets.service import TicketService

            await TicketService(self.db).issue_ticket_for_registration(registration)

        await self.db.commit()
        for notification in capacity_warning_notifications:
            try:
                from app.modules.notifications.service import NotificationService

                await NotificationService(self.db).deliver_notification(notification.id)
            except Exception:
                logger.exception("Unable to deliver capacity warning %s", notification.id)
        # Re-fetch via get_by_id (eager-loads participants) rather than
        # db.refresh(registration), which only reloads column attributes,
        # not relationships — see the fix note in repository.py's
        # get_by_id for why this matters for the API response.
        return await self.registrations.get_by_id(registration.id)

    async def get_registration_or_raise(self, registration_id: uuid.UUID) -> Registration:
        registration = await self.registrations.get_by_id(registration_id)
        if registration is None:
            raise RegistrationNotFoundError("Registration not found.")
        return registration

    async def list_registrations_for_actor(self, actor: User) -> list[Registration]:
        return await self.registrations.list_for_user(actor.id)

    async def list_registrations_for_event(self, event_id: uuid.UUID) -> list[Registration]:
        return await self.registrations.list_for_event(event_id)

    async def list_registrations_for_events(self, event_ids: set[uuid.UUID]) -> list[Registration]:
        return await self.registrations.list_for_events(event_ids)

    async def list_all_registrations(self) -> list[Registration]:
        return await self.registrations.list_all()

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

        # Same fix as create_registration: an approved registration for a
        # free (no-fee) event is now in its final "no payment needed"
        # state — issue the ticket right here, since the payment webhook
        # path this event will never touch is the only other place a
        # ticket would otherwise get created.
        if approve and registration.status == RegistrationStatus.APPROVED:
            config = await self.config.get_configuration(registration.event_id)
            if config is not None and (config.fee_amount is None or float(config.fee_amount) == 0):
                from app.modules.tickets.service import TicketService

                await TicketService(self.db).issue_ticket_for_registration(registration)

        await self.db.commit()
        # Same fix as create_registration — re-fetch with participants
        # eager-loaded rather than a plain db.refresh().
        return await self.registrations.get_by_id(registration.id)

    async def _reopen_event_if_capacity_available(self, event, config) -> None:
        """Release a seat without reopening an event past its deadline."""
        if event.status != EventStatus.REGISTRATION_CLOSED or config.capacity is None:
            return
        count = await self.registrations.count_active_for_event(event.id)
        availability = calculate_registration_availability(
            event_status=EventStatus.REGISTRATION_OPEN,
            capacity=config.capacity,
            registered_count=count,
            registration_end_at=parse_registration_end_at(config.details),
        )
        if availability in {RegistrationAvailability.OPEN, RegistrationAvailability.LIMITED}:
            event.status = EventStatus.REGISTRATION_OPEN

    async def cancel_registration(
        self, registration_id: uuid.UUID, actor: User, reason: str | None = None
    ) -> Registration:
        """Cancel a registration, or begin its payment refund lifecycle."""
        registration = await self.get_registration_or_raise(registration_id)
        await acquire_event_capacity_lock(self.db, registration.event_id)
        registration = await self.get_registration_or_raise(registration_id)
        is_owner = registration.user_id == actor.id
        if not is_owner and not await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            registration.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        ):
            raise RegistrationScopeError("You cannot cancel this registration.")

        eligible = {
            RegistrationStatus.STARTED,
            RegistrationStatus.SUBMITTED,
            RegistrationStatus.PENDING_VERIFICATION,
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.APPROVED,
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.REFUND_FAILED,
        }
        if registration.status not in eligible:
            raise InvalidRegistrationStateError(
                f"Registration is already in '{registration.status.value}' and cannot be cancelled."
            )

        if registration.child_id is not None and is_owner:
            await self.guardians.ensure_guardian_can_register_for_child(actor.id, registration.child_id)

        event = await self._get_event_or_raise(registration.event_id)
        config = await self._get_config_or_raise(registration.event_id)
        cancellation_deadline = registration.cancellation_deadline_at
        if cancellation_deadline is None:
            cancellation_deadline = parse_cancellation_deadline_at(config.details)
        if is_owner and cancellation_deadline is not None:
            deadline = cancellation_deadline
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= deadline:
                raise InvalidRegistrationStateError("The cancellation deadline has passed.")

        now = datetime.now(timezone.utc)
        registration.cancellation_requested_at = now
        registration.cancellation_reason = reason
        registration.cancelled_by = actor.id
        registration.cancellation_deadline_at = cancellation_deadline

        from app.modules.payments.models import PaymentStatus
        from app.modules.payments.service import PaymentService
        from app.modules.tickets.models import TicketStatus
        from app.modules.tickets.repository import TicketRepository

        payment = await PaymentService(self.db).payments.get_by_registration_id(registration.id)
        if payment is not None and payment.status == PaymentStatus.VERIFIED:
            await PaymentService(self.db).request_refund(
                payment_id=payment.id,
                actor=actor,
                amount=None,
                reason=reason or "Participant cancellation",
                commit=False,
            )
            registration.status = RegistrationStatus.REFUND_PENDING
            action = "refund_requested_for_cancellation"
        else:
            if payment is not None and payment.status == PaymentStatus.INITIATED:
                payment.status = PaymentStatus.FAILED
            registration.status = RegistrationStatus.CANCELLED
            registration.cancelled_at = now
            ticket = await TicketRepository(self.db).get_by_registration_id(registration.id)
            if ticket is not None and ticket.status == TicketStatus.ISSUED:
                ticket.status = TicketStatus.CANCELLED
            await self._reopen_event_if_capacity_available(event, config)
            action = "cancelled"

        await write_audit_log(
            self.db,
            entity_type="registration",
            entity_id=registration.id,
            action=action,
            actor_user_id=actor.id,
            after_value={"status": registration.status.value, "reason": reason},
        )
        await self.db.commit()
        return await self.registrations.get_by_id(registration.id)
