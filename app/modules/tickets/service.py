"""
QR ticket issuance, verification, and check-in handling.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.modules.identity.models import User
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
            self.settings.ticket_qr_secret.encode(), payload.encode(), hashlib.sha256
        ).hexdigest()

    async def issue_ticket_for_payment(self, payment: Payment) -> Ticket:
        existing = await self.tickets.get_by_registration_id(payment.registration_id)
        if existing is not None:
            return existing
        ticket_code = f"TKT-{secrets.token_hex(8)}"
        payload = f"{ticket_code}:{payment.registration_id}:{payment.id}"
        signature = self._sign_payload(payload)
        ticket = await self.tickets.create(
            event_id=payment.event_id,
            registration_id=payment.registration_id,
            payment_id=payment.id,
            user_id=payment.user_id,
            ticket_code=ticket_code,
            qr_payload=payload,
            qr_signature=signature,
            status=TicketStatus.ISSUED,
            issued_at=datetime.now(timezone.utc),
        )
        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is not None:
            registration.status = RegistrationStatus.CONFIRMED
        await write_audit_log(
            self.db,
            entity_type="ticket",
            entity_id=ticket.id,
            action="issued",
            actor_user_id=payment.user_id,
            after_value={"ticket_code": ticket.ticket_code},
        )
        return ticket

    async def list_my_tickets(self, user: User) -> list[Ticket]:
        return await self.tickets.list_for_user(user.id)

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

    async def verify_qr_payload(self, payload: str, signature: str) -> bool:
        return hmac.compare_digest(self._sign_payload(payload), signature)

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
        if not await self.can_access_ticket(ticket, actor):
            raise InvalidTicketStateError("You cannot check in this ticket.")
        existing = await self.checkins.get_by_ticket_id(ticket.id)
        if existing is not None:
            raise DuplicateCheckInError("This ticket has already been checked in.")
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
        ticket.status = TicketStatus.CHECKED_IN
        ticket.checked_in_at = datetime.now(timezone.utc)
        ticket.checked_in_by = actor.id
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
            if not await self.verify_qr_payload(scan.scan_payload, scan.qr_signature):
                raise InvalidTicketStateError("Invalid offline scan payload.")
            ticket_code = scan.scan_payload.split(":", 1)[0]
            ticket = await self.tickets.get_by_code(ticket_code)
            if ticket is None:
                raise TicketNotFoundError("Ticket not found.")
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
