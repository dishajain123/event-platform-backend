"""
Phase 4 ticket coverage.
"""
import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.service import RegistrationService
from app.modules.tickets.exceptions import DuplicateCheckInError
from app.modules.tickets.models import CheckInSource, TicketStatus
from app.modules.tickets.schemas import OfflineCheckInIn
from app.modules.tickets.service import TicketService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


def _gateway_signature(order_id: str, payment_id: str) -> str:
    secret = get_settings().payment_gateway_key_secret.encode()
    payload = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


async def _make_ticket_context(db_session):
    creator = User(mobile_number="+919310000001")
    registrant = User(mobile_number="+919310000002")
    staff = User(mobile_number="+919310000003")
    db_session.add_all([creator, registrant, staff])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=20)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 4 Ticket Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=750.0,
        currency="INR",
        capacity=25,
        approval_required=False,
        rules={},
        discount_rules=None,
    )

    registration = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=registrant,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    payment = await PaymentService(db_session).initiate_payment(
        registration_id=registration.id,
        actor=registrant,
    )

    await _assign_role(db_session, staff, RoleName.EVENT_MANAGER, event.id)

    gateway_payment_id = "pay_test_0200"
    signature = _gateway_signature(payment.gateway_order_id, gateway_payment_id)
    await PaymentService(db_session).handle_webhook(payment.gateway_order_id, gateway_payment_id, signature)

    ticket = await TicketService(db_session).tickets.get_by_registration_id(registration.id)
    return {
        "event": event,
        "registrant": registrant,
        "staff": staff,
        "registration": registration,
        "payment": payment,
        "ticket": ticket,
    }


@pytest.mark.asyncio
async def test_offline_checkin_sync_creates_checkin_and_blocks_duplicate_scan(db_session):
    context = await _make_ticket_context(db_session)
    ticket_service = TicketService(db_session)
    ticket = context["ticket"]
    assert ticket is not None

    offline_scan = OfflineCheckInIn(
        venue_id=None,
        offline_batch_id="batch-1",
        scan_payload=ticket.qr_payload,
        qr_signature=ticket.qr_signature,
    )
    checkins = await ticket_service.sync_offline_checkins(context["staff"], [offline_scan])

    assert len(checkins) == 1
    assert checkins[0].source == CheckInSource.OFFLINE
    assert checkins[0].synced_at is not None

    refreshed_ticket = await ticket_service.tickets.get_by_registration_id(context["registration"].id)
    assert refreshed_ticket is not None
    assert refreshed_ticket.status == TicketStatus.CHECKED_IN

    with pytest.raises(DuplicateCheckInError):
        await ticket_service.check_in(refreshed_ticket.id, context["staff"], source=CheckInSource.ONLINE)


@pytest.mark.asyncio
async def test_online_check_in_can_resolve_a_scanned_ticket_by_payload(db_session):
    """
    Regression test for a real gap found while building the mobile app's
    QR scanner: POST /{ticket_id}/check-in requires the ticket's real
    UUID, but a scanned QR's qr_payload only ever contains
    "{ticket_code}:{registration_id}:{payment_id_or_free}" — never the
    ticket's UUID. The offline sync path already resolved this
    internally; the online path (Staff Mode's single highest-frequency
    action) had no equivalent at all.
    """
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    ticket = ctx["ticket"]

    resolved = await service.resolve_by_scan_payload(ticket.qr_payload, ticket.qr_signature)
    assert resolved.id == ticket.id

    # The resolved ticket's real UUID is what actually unlocks check-in.
    check_in = await service.check_in(resolved.id, ctx["staff"], venue_id=None)
    assert check_in.ticket_id == ticket.id

    # A tampered/wrong signature is correctly rejected, not silently resolved.
    from app.modules.tickets.exceptions import InvalidTicketStateError

    with pytest.raises(InvalidTicketStateError):
        await service.resolve_by_scan_payload(ticket.qr_payload, "not-the-real-signature")


@pytest.mark.asyncio
async def test_manual_ticket_code_lookup_works_without_a_signature(db_session):
    """
    The manual-entry fallback for a damaged/unreadable QR (Section 8,
    Phase 5) — a human can't type a cryptographic signature, so this
    path deliberately looks up by ticket_code alone, relying on the
    caller already being an authenticated, permission-checked staff
    account rather than payload-signature verification.
    """
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    ticket = ctx["ticket"]

    resolved = await service.resolve_by_ticket_code(ticket.ticket_code, ctx["staff"])
    assert resolved.id == ticket.id

    from app.modules.tickets.exceptions import TicketNotFoundError

    with pytest.raises(TicketNotFoundError):
        await service.resolve_by_ticket_code("TKT-doesnotexist00", ctx["staff"])