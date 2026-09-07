"""
Signed Code 128 ticket issuance, verification, and check-in handling.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.modules.identity.models import User
from app.modules.events.models import Event
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository
from app.modules.tickets.exceptions import DuplicateCheckInError, InvalidTicketStateError, TicketNotFoundError
from app.modules.tickets.models import CheckIn, CheckInSource, Ticket, TicketStatus
from app.modules.tickets.repository import CheckInRepository, TicketRepository
from app.modules.rbac.models import RoleName
from app.modules.tickets.schemas import OfflineCheckInIn


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
    ) -> Ticket:
        """
        Shared by both ticket-issuance paths — the payment webhook (see
        issue_ticket_for_payment) and free/no-payment registrations (see
        issue_ticket_for_registration). Whichever path calls it, the
        registration ends up CONFIRMED and a real, scannable ticket
        exists — a ticket's existence always means "confirmed," whether
        or not money changed hands.
        """
        existing = await self.tickets.get_by_registration_id(registration_id)
        if existing is not None:
            return existing
        ticket_code = f"TKT-{secrets.token_hex(8)}"
        payload = f"{ticket_code}:{event_id}:{registration_id}:{payment_id or 'free'}"
        signature = self._sign_payload(payload)
        ticket = await self.tickets.create(
            event_id=event_id,
            registration_id=registration_id,
            payment_id=payment_id,
            user_id=user_id,
            ticket_code=ticket_code,
            barcode_payload=payload,
            barcode_signature=signature,
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
        return await self._create_ticket(
            event_id=payment.event_id,
            registration_id=payment.registration_id,
            payment_id=payment.id,
            user_id=payment.user_id,
        )

    async def issue_ticket_for_registration(self, registration) -> Ticket:
        """
        The fix for free events: called directly from
        RegistrationService whenever a registration reaches its final
        "no payment needed" state (APPROVED with no fee configured),
        since issue_ticket_for_payment only ever runs from inside the
        payment webhook — a path free registrations never touch.
        """
        return await self._create_ticket(
            event_id=registration.event_id,
            registration_id=registration.id,
            payment_id=None,
            user_id=registration.user_id,
        )

    async def list_my_tickets(self, user: User) -> list[Ticket]:
        return await self.tickets.list_for_user(user.id)

    async def page_checkins(self, event_id, venue_id, *, page=1, page_size=25):
        return await self.checkins.page_for_event(event_id, venue_id, page=page, page_size=page_size)

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
        offline_batch_id: str | None = None,
        scan_payload: str | None = None,
        source: CheckInSource = CheckInSource.ONLINE,
    ) -> CheckIn:
        ticket = await self.get_ticket_or_raise(ticket_id)
        if not await self.can_check_in_ticket(ticket, actor):
            raise InvalidTicketStateError("You cannot check in this ticket.")
        existing = await self.checkins.get_by_ticket_id(ticket.id)
        if existing is not None:
            raise DuplicateCheckInError("This ticket has already been checked in.")
        if ticket.status != TicketStatus.ISSUED:
            raise InvalidTicketStateError("This ticket is not valid for check-in.")
        event = await self.db.get(Event, ticket.event_id)
        event_end = event.end_date if event is not None else None
        if event_end is not None and event_end.tzinfo is None:
            event_end = event_end.replace(tzinfo=timezone.utc)
        if event_end is None or datetime.now(timezone.utc) >= event_end:
            raise InvalidTicketStateError("This ticket has expired because the event has ended.")
        if ticket.payment_id is not None:
            payment = await self.db.get(Payment, ticket.payment_id)
            if payment is None or payment.status != PaymentStatus.VERIFIED:
                raise InvalidTicketStateError("Payment has not been verified for this ticket.")
        registration = await self.registrations.get_by_id(ticket.registration_id)
        if registration is None or registration.status not in {
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.REFUND_FAILED,
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
                synced_at=datetime.now(timezone.utc) if source == CheckInSource.OFFLINE else None,
            )
        except IntegrityError as exc:
            await self.db.rollback()
            raise DuplicateCheckInError("This ticket has already been checked in.") from exc
        ticket.status = TicketStatus.CHECKED_IN
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
