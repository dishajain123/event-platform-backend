"""
Signed Code 128 ticket issuance, verification, and check-in handling.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.audit import write_audit_log
from app.core.concurrency import acquire_advisory_lock
from app.core.permissions import user_has_scoped_role
from app.modules.identity.models import User
from app.modules.notifications.service import NotificationService
from app.modules.events.models import Event
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.models import RegistrationParticipant
from app.modules.registrations.repository import RegistrationRepository
from app.modules.tickets.exceptions import DuplicateCheckInError, InvalidTicketStateError, TicketNotFoundError
from app.modules.tickets.models import AccessPolicy, AccessType, AccessZone, CheckIn, CheckInSource, Ticket, TicketStatus, TicketTransfer, TicketTransferStatus, TicketValidationReason
from app.modules.tickets.repository import CheckInRepository, TicketRepository
from app.modules.rbac.models import RoleName
from app.modules.tickets.schemas import OfflineCheckInIn, TicketValidationOut


class TicketService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.tickets = TicketRepository(db)
        self.checkins = CheckInRepository(db)
        self.registrations = RegistrationRepository(db)

    def _sign_payload(self, payload: str) -> str:
        return hmac.new(
            self.settings.ticket_barcode_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def _create_ticket(
        self,
        *,
        event_id: uuid.UUID,
        registration_id: uuid.UUID,
        payment_id: uuid.UUID | None,
        user_id: uuid.UUID,
        participant_id: uuid.UUID | None = None,
    ) -> Ticket:
        """
        Shared by both ticket-issuance paths — the payment webhook (see
        issue_ticket_for_payment) and free/no-payment registrations (see
        issue_ticket_for_registration). Whichever path calls it, the
        registration ends up CONFIRMED and a real, scannable ticket
        exists — a ticket's existence always means "confirmed," whether
        or not money changed hands.
        """
        existing = (
            await self.tickets.get_by_registration_id(registration_id)
            if participant_id is None
            else await self.db.scalar(select(Ticket).where(Ticket.participant_id == participant_id))
        )
        if existing is not None:
            return existing
        ticket_code = f"TKT-{secrets.token_hex(8)}"
        payload = f"{ticket_code}:{event_id}:{registration_id}:{payment_id or 'free'}"
        signature = self._sign_payload(payload)
        policy_result = await self.db.execute(select(AccessPolicy).where(AccessPolicy.event_id == event_id, AccessPolicy.access_type == AccessType.GENERAL.value))
        policy = policy_result.scalar_one_or_none()
        ticket = await self.tickets.create(
            event_id=event_id,
            registration_id=registration_id,
            participant_id=participant_id,
            payment_id=payment_id,
            user_id=user_id,
            ticket_code=ticket_code,
            barcode_payload=payload,
            barcode_signature=signature,
            access_type=policy.access_type if policy else AccessType.GENERAL.value,
            access_policy_id=policy.id if policy else None,
            valid_from=policy.valid_from if policy else None,
            valid_until=policy.valid_until if policy else None,
            valid_dates=policy.valid_dates if policy else None,
            # Keep ISSUED for wire/database compatibility; validation treats
            # it as the legacy spelling of the new ACTIVE state.
            status=TicketStatus.ISSUED,
            issued_at=datetime.now(timezone.utc),
        )
        registration = await self.registrations.get_by_id(registration_id)
        if registration is not None:
            registration.status = RegistrationStatus.CONFIRMED
        await write_audit_log(
            self.db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="issued",
            actor_user_id=user_id,
            after_value={"ticket_code": ticket.ticket_code, "payment_id": str(payment_id) if payment_id else None},
        )
        return ticket

    async def issue_ticket_for_payment(self, payment: Payment) -> Ticket:
        registration = await self.registrations.get_by_id(payment.registration_id)
        return await self._issue_registration_tickets(registration, payment.id, payment.user_id)

    async def issue_ticket_for_registration(self, registration) -> Ticket:
        """
        The fix for free events: called directly from
        RegistrationService whenever a registration reaches its final
        "no payment needed" state (APPROVED with no fee configured),
        since issue_ticket_for_payment only ever runs from inside the
        payment webhook — a path free registrations never touch.
        """
        return await self._issue_registration_tickets(registration, None, registration.user_id)

    async def _issue_registration_tickets(self, registration, payment_id, fallback_user_id) -> Ticket:
        """Issue one independently verifiable ticket for every team participant.

        The team registration remains the payment/capacity aggregate, but a
        participant ticket is the access-control unit. Repeated webhook/free
        issuance is idempotent by participant_id.
        """
        participant_result = await self.db.execute(
            select(RegistrationParticipant).where(
                RegistrationParticipant.registration_id == registration.id
            ).order_by(RegistrationParticipant.created_at, RegistrationParticipant.id)
        )
        participants = list(participant_result.scalars().all())
        if registration.team_id is not None and participants:
            tickets = []
            for participant in participants:
                tickets.append(await self._create_ticket(
                    event_id=registration.event_id,
                    registration_id=registration.id,
                    payment_id=payment_id,
                    user_id=participant.user_id or fallback_user_id,
                    participant_id=participant.id,
                ))
            registration.status = RegistrationStatus.CONFIRMED
            return tickets[0]
        return await self._create_ticket(
            event_id=registration.event_id,
            registration_id=registration.id,
            payment_id=payment_id,
            user_id=fallback_user_id,
        )

    async def list_my_tickets(self, user: User) -> list[Ticket]:
        return await self.tickets.list_for_user(user.id)

    async def page_incoming_transfers(self, user: User, *, page=1, page_size=25):
        return await self.tickets.page_transfers(
            recipient_user_id=user.id,
            status=TicketTransferStatus.PENDING,
            page=page,
            page_size=page_size,
        )

    async def page_event_transfers(self, event_id, *, status=None, search=None, page=1, page_size=25):
        return await self.tickets.page_transfers(
            event_id=event_id,
            status=status,
            search=search,
            page=page,
            page_size=page_size,
        )

    async def page_checkins(self, event_id, venue_id, *, page=1, page_size=25):
        return await self.checkins.page_for_event(event_id, venue_id, page=page, page_size=page_size)

    async def create_zone(self, event_id, payload):
        zone = AccessZone(event_id=event_id, code=payload.code.strip(), name=payload.name.strip(), is_active=payload.is_active)
        self.db.add(zone)
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(zone)
        return zone

    async def list_zones(self, event_id):
        result = await self.db.execute(select(AccessZone).where(AccessZone.event_id == event_id).order_by(AccessZone.code))
        return list(result.scalars().all())

    async def upsert_policy(self, event_id, payload):
        result = await self.db.execute(select(AccessPolicy).where(AccessPolicy.event_id == event_id, AccessPolicy.access_type == payload.access_type))
        policy = result.scalar_one_or_none()
        values = payload.model_dump()
        values["allowed_zone_ids"] = [str(value) for value in payload.allowed_zone_ids]
        values["valid_dates"] = [value.isoformat() for value in payload.valid_dates] if payload.valid_dates else None
        if payload.allowed_zone_ids:
            zones = list((await self.db.execute(select(AccessZone).where(AccessZone.event_id == event_id, AccessZone.id.in_(payload.allowed_zone_ids), AccessZone.is_active.is_(True)))).scalars().all())
            if len(zones) != len(set(payload.allowed_zone_ids)):
                raise InvalidTicketStateError("Access policy contains an inactive or cross-event zone.")
        if policy is None:
            policy = AccessPolicy(event_id=event_id, **values)
            self.db.add(policy)
        else:
            for key, value in values.items():
                setattr(policy, key, value)
        await self.db.commit()
        await self.db.refresh(policy)
        return policy

    async def list_policies(self, event_id):
        result = await self.db.execute(select(AccessPolicy).where(AccessPolicy.event_id == event_id).order_by(AccessPolicy.access_type))
        return list(result.scalars().all())

    async def page_tickets(self, event_id, **filters):
        return await self.tickets.page_for_event(event_id, **filters)

    async def revoke_ticket(self, ticket_id, actor):
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        ticket.status = TicketStatus.REVOKED
        await write_audit_log(self.db, entity_type="ticket", entity_id=ticket.id, action="revoked", actor_user_id=actor.id, after_value={"event_id": str(ticket.event_id)})
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def _ticket_lifecycle_notification(self, *, event_id, user_id, title, body, kind, transfer_id):
        try:
            service = NotificationService(self.db)
            notification = await service._queue_automated(
                event_id=event_id,
                user_id=user_id,
                title=title,
                body=body,
                notification_type="ticket_transfer",
                dedupe_key=f"ticket-transfer:{transfer_id}:{kind}:{user_id}",
                target_metadata={"event_id": str(event_id), "transfer_id": str(transfer_id), "notification": kind},
            )
            if notification is None:
                return
            await self.db.commit()
            if service.settings.environment == "production":
                from app.workers.notification_tasks import deliver_notification_batch
                deliver_notification_batch.delay([str(notification.id)])
            else:
                try:
                    await service.deliver_notification(notification.id)
                except Exception:
                    pass
        except Exception:
            await self.db.rollback()

    async def initiate_transfer(self, ticket_id, actor: User, recipient_user_id):
        await acquire_advisory_lock(self.db, f"ticket-transfer:{ticket_id}")
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        recipient = await self.db.get(User, recipient_user_id)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        if recipient is None or recipient.id == actor.id or ticket.user_id != actor.id:
            raise InvalidTicketStateError("The ticket recipient is not valid.")
        if ticket.status in {TicketStatus.CANCELLED, TicketStatus.REVOKED, TicketStatus.EXPIRED, TicketStatus.USED, TicketStatus.CHECKED_IN} or ticket.entry_count > 0:
            raise InvalidTicketStateError("A used, cancelled, revoked, expired, or checked-in ticket cannot be transferred.")
        if await self.tickets.get_pending_transfer(ticket.id, for_update=True):
            raise InvalidTicketStateError("This ticket already has a pending transfer.")
        transfer = TicketTransfer(ticket_id=ticket.id, event_id=ticket.event_id, from_user_id=actor.id, to_user_id=recipient.id, status=TicketTransferStatus.PENDING)
        self.db.add(transfer)
        await self.db.flush()
        await write_audit_log(self.db, entity_type="ticket_transfer", entity_id=transfer.id, action="initiated", actor_user_id=actor.id, after_value={"event_id": str(ticket.event_id), "ticket_id": str(ticket.id), "to_user_id": str(recipient.id)})
        await self.db.commit()
        await self._ticket_lifecycle_notification(event_id=ticket.event_id, user_id=recipient.id, title="Ticket transfer request", body="You have received a ticket transfer request.", kind="transfer_initiated", transfer_id=transfer.id)
        return transfer

    async def respond_transfer(self, transfer_id, actor: User, accept: bool):
        await acquire_advisory_lock(self.db, f"ticket-transfer:{transfer_id}")
        transfer = await self.tickets.get_transfer(transfer_id, for_update=True)
        if transfer is None or transfer.status != TicketTransferStatus.PENDING:
            raise InvalidTicketStateError("This transfer is no longer pending.")
        if transfer.to_user_id != actor.id:
            raise InvalidTicketStateError("You cannot respond to this transfer.")
        ticket = await self.tickets.get_by_id(transfer.ticket_id, for_update=True)
        if ticket is None or ticket.user_id != transfer.from_user_id or ticket.status in {TicketStatus.CANCELLED, TicketStatus.REVOKED, TicketStatus.EXPIRED, TicketStatus.USED, TicketStatus.CHECKED_IN} or ticket.entry_count > 0:
            raise InvalidTicketStateError("This ticket is no longer transferable.")
        now = datetime.now(timezone.utc)
        transfer.status = TicketTransferStatus.ACCEPTED if accept else TicketTransferStatus.REJECTED
        transfer.responded_at = now
        if accept:
            ticket.user_id = actor.id
            if ticket.participant_id:
                participant = await self.db.get(RegistrationParticipant, ticket.participant_id)
                if participant is not None:
                    participant.user_id = actor.id
            transfer.accepted_at = now
        await write_audit_log(self.db, entity_type="ticket_transfer", entity_id=transfer.id, action="accepted" if accept else "rejected", actor_user_id=actor.id, after_value={"event_id": str(transfer.event_id), "ticket_id": str(ticket.id)})
        await self.db.commit()
        await self._ticket_lifecycle_notification(event_id=transfer.event_id, user_id=transfer.from_user_id, title="Ticket transfer accepted" if accept else "Ticket transfer rejected", body="Your ticket ownership has changed." if accept else "Your ticket transfer request was rejected.", kind="transfer_accepted" if accept else "transfer_rejected", transfer_id=transfer.id)
        return transfer

    async def cancel_transfer(self, transfer_id, actor: User):
        transfer = await self.tickets.get_transfer(transfer_id, for_update=True)
        if transfer is None or transfer.status != TicketTransferStatus.PENDING or transfer.from_user_id != actor.id:
            raise InvalidTicketStateError("This transfer cannot be cancelled.")
        transfer.status = TicketTransferStatus.CANCELLED
        transfer.responded_at = datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="ticket_transfer", entity_id=transfer.id, action="cancelled", actor_user_id=actor.id, after_value={"event_id": str(transfer.event_id)})
        await self.db.commit()
        return transfer

    async def cancel_transfer_as_staff(self, transfer_id, event_id, actor: User):
        await acquire_advisory_lock(self.db, f"ticket-transfer:{transfer_id}")
        transfer = await self.tickets.get_transfer(transfer_id, for_update=True)
        if transfer is None or transfer.event_id != event_id or transfer.status != TicketTransferStatus.PENDING:
            raise InvalidTicketStateError("This transfer is no longer pending for this event.")
        transfer.status = TicketTransferStatus.CANCELLED
        transfer.responded_at = datetime.now(timezone.utc)
        await write_audit_log(
            self.db,
            entity_type="ticket_transfer",
            entity_id=transfer.id,
            action="cancelled_by_staff",
            actor_user_id=actor.id,
            after_value={"event_id": str(event_id), "ticket_id": str(transfer.ticket_id)},
        )
        await self.db.commit()
        await self.db.refresh(transfer)
        return transfer

    async def reassign_ticket(self, ticket_id, target_user_id, actor):
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        target = await self.db.get(User, target_user_id)
        if target is None:
            raise InvalidTicketStateError("The target ticket owner does not exist.")
        if ticket.status in {TicketStatus.CANCELLED, TicketStatus.REVOKED, TicketStatus.EXPIRED, TicketStatus.USED, TicketStatus.CHECKED_IN} or ticket.entry_count > 0:
            raise InvalidTicketStateError("A used, cancelled, revoked, expired, or checked-in ticket cannot be reassigned.")
        old_user = ticket.user_id
        ticket.user_id = target_user_id
        await write_audit_log(self.db, entity_type="ticket", entity_id=ticket.id, action="reassigned", actor_user_id=actor.id, before_value={"user_id": str(old_user)}, after_value={"user_id": str(target_user_id), "event_id": str(ticket.event_id)})
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def check_out(self, ticket_id: uuid.UUID, actor: User) -> CheckIn:
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        if not await self.can_check_in_ticket(ticket, actor):
            raise InvalidTicketStateError("You cannot check out this ticket.")
        latest = await self.checkins.get_by_ticket_id(ticket.id)
        if latest is None or latest.exited_at is not None:
            raise InvalidTicketStateError("This ticket is not currently inside the venue.")
        latest.exited_at = datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="ticket", entity_id=ticket.id, action="checked_out", actor_user_id=actor.id, after_value={"event_id": str(ticket.event_id)})
        await self.db.commit()
        await self.db.refresh(latest)
        return latest

    async def assign_access_type(self, ticket_id, access_type: str, actor):
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        result = await self.db.execute(select(AccessPolicy).where(AccessPolicy.event_id == ticket.event_id, AccessPolicy.access_type == access_type.strip().lower()))
        policy = result.scalar_one_or_none()
        if policy is None:
            raise InvalidTicketStateError("No access policy exists for this access type.")
        ticket.access_type = policy.access_type
        ticket.access_policy_id = policy.id
        ticket.valid_from = policy.valid_from
        ticket.valid_until = policy.valid_until
        ticket.valid_dates = policy.valid_dates
        await write_audit_log(self.db, entity_type="ticket", entity_id=ticket.id, action="access_type_changed", actor_user_id=actor.id, after_value={"event_id": str(ticket.event_id), "access_type": ticket.access_type})
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def replace_ticket(self, ticket_id, actor):
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        if ticket.status in {TicketStatus.CANCELLED, TicketStatus.REVOKED} or ticket.entry_count > 0:
            raise InvalidTicketStateError("A cancelled, revoked, or already-used ticket cannot be replaced.")
        old_code = ticket.ticket_code
        ticket.ticket_code = f"TKT-{secrets.token_hex(8)}"
        ticket.barcode_payload = f"{ticket.ticket_code}:{ticket.event_id}:{ticket.registration_id}:{ticket.payment_id or 'free'}"
        ticket.barcode_signature = self._sign_payload(ticket.barcode_payload)
        ticket.status = TicketStatus.ACTIVE
        ticket.entry_count = 0
        ticket.checked_in_at = None
        ticket.checked_in_by = None
        await write_audit_log(self.db, entity_type="ticket", entity_id=ticket.id, action="replaced", actor_user_id=actor.id, before_value={"ticket_code": old_code}, after_value={"ticket_code": ticket.ticket_code, "event_id": str(ticket.event_id)})
        await self.db.commit()
        await self.db.refresh(ticket)
        return ticket

    async def get_ticket_or_raise(self, ticket_id: uuid.UUID) -> Ticket:
        ticket = await self.tickets.get_by_id(ticket_id)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        return ticket

    async def can_access_ticket(self, ticket: Ticket, actor: User) -> bool:
        if ticket.user_id == actor.id:
            return True
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER},
            ticket.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def can_check_in_ticket(self, ticket: Ticket, actor: User) -> bool:
        """Gate operations are staff-only; ticket ownership grants viewing only."""
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER},
            ticket.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def verify_barcode_payload(self, payload: str, signature: str) -> bool:
        return hmac.compare_digest(self._sign_payload(payload), signature)

    async def resolve_by_scan_payload(self, scan_payload: str, barcode_signature: str) -> Ticket:
        """
        The scanner sends a signed barcode value. The ticket UUID is not
        embedded in that value, so the backend resolves it before check-in.
        """
        if not await self.verify_barcode_payload(scan_payload, barcode_signature):
            raise InvalidTicketStateError("Invalid or tampered barcode.")
        parts = scan_payload.split(":")
        ticket_code = parts[0]
        ticket = await self.tickets.get_by_code(ticket_code)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        # New tickets carry their event ID inside the signed value. Keep
        # accepting the legacy three-part payload for tickets issued before
        # the migration, but enforce the stronger binding for new tickets.
        if len(parts) == 4 and parts[1] != str(ticket.event_id):
            raise InvalidTicketStateError("Barcode is for a different event.")
        return ticket

    async def validate_scan(self, scan_payload: str, barcode_signature: str, actor: User, *, event_id: uuid.UUID | None = None, access_zone_id: uuid.UUID | None = None) -> TicketValidationOut:
        if not await self.verify_barcode_payload(scan_payload, barcode_signature):
            return TicketValidationOut(valid=False, reason=TicketValidationReason.INVALID_SIGNATURE, message="The barcode signature is invalid.")
        parts = scan_payload.split(":")
        ticket = await self.tickets.get_by_code(parts[0]) if parts else None
        if ticket is None:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.UNKNOWN_TICKET, message="Ticket not found.")
        if len(parts) == 4 and parts[1] != str(ticket.event_id):
            return TicketValidationOut(valid=False, reason=TicketValidationReason.WRONG_EVENT, event_id=ticket.event_id, message="This ticket belongs to another event.")
        if event_id is not None and ticket.event_id != event_id:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.WRONG_EVENT, event_id=ticket.event_id, message="This ticket belongs to another event.")
        if not await self.can_check_in_ticket(ticket, actor):
            return TicketValidationOut(valid=False, reason=TicketValidationReason.UNAUTHORIZED_STAFF, event_id=ticket.event_id, message="You are not authorized to scan this event.")
        if ticket.status in {TicketStatus.CANCELLED, TicketStatus.REVOKED}:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.CANCELLED, ticket=ticket, event_id=ticket.event_id, message="This ticket has been cancelled or revoked.")
        if ticket.status == TicketStatus.EXPIRED:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.EXPIRED, ticket=ticket, event_id=ticket.event_id, message="This ticket has expired.")
        if ticket.status in {TicketStatus.USED, TicketStatus.CHECKED_IN} and ticket.entry_count >= 1:
            policy = await self.db.get(AccessPolicy, ticket.access_policy_id) if ticket.access_policy_id else None
            if policy is None or not policy.allows_reentry or ticket.entry_count >= policy.max_entries:
                return TicketValidationOut(valid=False, reason=TicketValidationReason.ALREADY_USED, ticket=ticket, event_id=ticket.event_id, message="This ticket has already been used.")
        now = datetime.now(timezone.utc)
        event = await self.db.get(Event, ticket.event_id)
        if event is not None and event.end_date and now >= (event.end_date.replace(tzinfo=timezone.utc) if event.end_date.tzinfo is None else event.end_date):
            return TicketValidationOut(valid=False, reason=TicketValidationReason.EVENT_ENDED, ticket=ticket, event_id=ticket.event_id, message="The event has ended.")
        if ticket.valid_from and now < ticket.valid_from:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.OUTSIDE_TIME_WINDOW, ticket=ticket, event_id=ticket.event_id, message="This ticket is not active yet.")
        if ticket.valid_until and now >= ticket.valid_until:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.EXPIRED, ticket=ticket, event_id=ticket.event_id, message="This ticket has expired.")
        if ticket.valid_dates and now.date().isoformat() not in {str(value) for value in ticket.valid_dates}:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.OUTSIDE_TIME_WINDOW, ticket=ticket, event_id=ticket.event_id, message="This pass is not valid on this date.")
        if ticket.access_policy_id:
            policy = await self.db.get(AccessPolicy, ticket.access_policy_id)
            if policy and policy.allowed_zone_ids and (access_zone_id is None or str(access_zone_id) not in {str(value) for value in policy.allowed_zone_ids}):
                return TicketValidationOut(valid=False, reason=TicketValidationReason.ACCESS_DENIED, ticket=ticket, event_id=ticket.event_id, message="This pass is not valid for this access zone.")
        if access_zone_id is not None:
            zone = await self.db.get(AccessZone, access_zone_id)
            if zone is None or zone.event_id != ticket.event_id or not zone.is_active:
                return TicketValidationOut(valid=False, reason=TicketValidationReason.ACCESS_DENIED, ticket=ticket, event_id=ticket.event_id, message="This access zone is not valid for the event.")
        if ticket.payment_id is not None:
            payment = await self.db.get(Payment, ticket.payment_id)
            if payment is None or payment.status == PaymentStatus.REFUNDED:
                return TicketValidationOut(valid=False, reason=TicketValidationReason.REFUNDED, ticket=ticket, event_id=ticket.event_id, message="This ticket has been refunded.")
            if payment.status != PaymentStatus.VERIFIED:
                return TicketValidationOut(valid=False, reason=TicketValidationReason.PAYMENT_NOT_VERIFIED, ticket=ticket, event_id=ticket.event_id, message="Payment has not been verified.")
        registration = await self.registrations.get_by_id(ticket.registration_id)
        if registration is None or registration.status not in {RegistrationStatus.CONFIRMED, RegistrationStatus.REFUND_FAILED, RegistrationStatus.CHECKED_IN}:
            return TicketValidationOut(valid=False, reason=TicketValidationReason.REGISTRATION_NOT_CONFIRMED, ticket=ticket, event_id=ticket.event_id, message="Registration is not confirmed.")
        return TicketValidationOut(valid=True, reason=TicketValidationReason.VALID, ticket=ticket, event_id=ticket.event_id, message="Ticket is valid.")

    async def resolve_by_ticket_code(self, ticket_code: str, actor: User) -> Ticket:
        """
        The manual-entry fallback for a damaged/unreadable barcode deliberately
        does NOT require the barcode signature because the high-entropy code
        is only a manual fallback; the camera-scan path
        (resolve_by_scan_payload) does require it. A human can't
        type a cryptographic signature from memory, so this instead
        relies on: (1) the caller already being an authenticated,
        can_access_ticket-checked Staff Mode account (enforced in the
        router, same as every other ticket endpoint), and (2)
        ticket_code itself already being a high-entropy random string
        (`TKT-` + 16 hex chars), not something guessable. This is a
        narrower trust model than the signed-payload path, used only for
        the fallback case, never the primary scan flow.
        """
        ticket = await self.tickets.get_by_code(ticket_code)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        return ticket

    async def check_in(
        self,
        ticket_id: uuid.UUID,
        actor: User,
        *,
        venue_id: uuid.UUID | None = None,
        access_zone_id: uuid.UUID | None = None,
        offline_batch_id: str | None = None,
        scan_payload: str | None = None,
        source: CheckInSource = CheckInSource.ONLINE,
    ) -> CheckIn:
        ticket = await self.tickets.get_by_id(ticket_id, for_update=True)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found.")
        if not await self.can_check_in_ticket(ticket, actor):
            raise InvalidTicketStateError("You cannot check in this ticket.")
        # Replays must still pass the current staff/event authorization gate.
        # The idempotency record proves that the operation was already applied;
        # it must not become a bypass after a staff assignment is revoked.
        if offline_batch_id:
            existing = await self.checkins.get_by_offline_batch_id(offline_batch_id)
            if existing is not None:
                if existing.ticket_id != ticket.id or existing.scanned_by != actor.id:
                    raise InvalidTicketStateError("This offline operation key is already used.")
                return existing
        policy = await self.db.get(AccessPolicy, ticket.access_policy_id) if ticket.access_policy_id else None
        if policy and policy.allowed_zone_ids and (access_zone_id is None or str(access_zone_id) not in {str(value) for value in policy.allowed_zone_ids}):
            raise InvalidTicketStateError("This pass is not valid for this access zone.")
        if access_zone_id is not None:
            zone = await self.db.get(AccessZone, access_zone_id)
            if zone is None or zone.event_id != ticket.event_id or not zone.is_active:
                raise InvalidTicketStateError("This access zone is not valid for the event.")
        if ticket.status in {TicketStatus.USED, TicketStatus.CHECKED_IN} and (policy is None or not policy.allows_reentry or ticket.entry_count >= policy.max_entries):
            raise DuplicateCheckInError("This ticket has already been checked in.")
        if ticket.status not in {TicketStatus.ACTIVE, TicketStatus.ISSUED, TicketStatus.USED, TicketStatus.CHECKED_IN}:
            raise InvalidTicketStateError("This ticket is not valid for check-in.")
        event = await self.db.get(Event, ticket.event_id)
        event_end = event.end_date if event is not None else None
        if event_end is not None and event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=timezone.utc)
        if event_end is None or datetime.now(timezone.utc) >= event_end:
            raise InvalidTicketStateError("This ticket has expired because the event has ended.")
        now = datetime.now(timezone.utc)
        if ticket.valid_from and now < ticket.valid_from:
            raise InvalidTicketStateError("This ticket is not active yet.")
        if ticket.valid_until and now >= ticket.valid_until:
            raise InvalidTicketStateError("This ticket has expired.")
        if ticket.valid_dates and now.date().isoformat() not in {str(value) for value in ticket.valid_dates}:
            raise InvalidTicketStateError("This pass is not valid on this date.")
        if ticket.payment_id is not None:
            payment = await self.db.get(Payment, ticket.payment_id)
            if payment is None or payment.status != PaymentStatus.VERIFIED:
                raise InvalidTicketStateError("Payment has not been verified for this ticket.")
        registration = await self.registrations.get_by_id(ticket.registration_id)
        if registration is None or registration.status not in {
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.REFUND_FAILED,
            RegistrationStatus.CHECKED_IN,
        }:
            raise InvalidTicketStateError("Registration is not confirmed.")
        try:
            check_in = await self.checkins.create(
                ticket_id=ticket.id,
                event_id=ticket.event_id,
                venue_id=venue_id,
                scanned_by=actor.id,
                source=source,
                offline_batch_id=offline_batch_id,
                scan_payload=scan_payload,
                entry_number=ticket.entry_count + 1,
                synced_at=datetime.now(timezone.utc) if source == CheckInSource.OFFLINE else None,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            if offline_batch_id:
                existing = await self.checkins.get_by_offline_batch_id(offline_batch_id)
                if existing is not None and existing.ticket_id == ticket.id and existing.scanned_by == actor.id:
                    return existing
            raise DuplicateCheckInError("This ticket has already been checked in.") from exc
        ticket.entry_count += 1
        # Preserve the existing CHECKED_IN wire state for the first entry;
        # USED represents later entries under an explicit re-entry policy.
        ticket.status = TicketStatus.CHECKED_IN if ticket.entry_count == 1 else TicketStatus.USED
        ticket.checked_in_at = datetime.now(timezone.utc)
        ticket.checked_in_by = actor.id
        registration.status = RegistrationStatus.CHECKED_IN
        registration.checked_in_at = ticket.checked_in_at
        await write_audit_log(
            self.db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="checked_in",
            actor_user_id=actor.id,
            after_value={"venue_id": str(venue_id) if venue_id else None},
        )
        await self.db.commit()
        await self.db.refresh(check_in)
        return check_in

    async def list_checkins(self, event_id: uuid.UUID, venue_id: uuid.UUID | None = None) -> list[CheckIn]:
        return await self.checkins.list_for_event(event_id, venue_id)

    async def sync_offline_checkins(self, actor: User, scans: list[OfflineCheckInIn]) -> list[CheckIn]:
        processed: list[CheckIn] = []
        for scan in scans:
            ticket = await self.resolve_by_scan_payload(scan.scan_payload, scan.barcode_signature)
            processed.append(
                await self.check_in(
                    ticket.id,
                    actor,
                    venue_id=scan.venue_id,
                    offline_batch_id=scan.offline_batch_id,
                    scan_payload=scan.scan_payload,
                    source=CheckInSource.OFFLINE,
                )
            )
        return processed
