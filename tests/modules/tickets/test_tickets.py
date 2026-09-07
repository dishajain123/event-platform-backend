"""
Phase 4 ticket coverage.
"""
import hashlib
import hmac
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.service import RegistrationService
from app.modules.tickets.exceptions import DuplicateCheckInError, InvalidTicketStateError
from app.modules.tickets.models import AccessPolicy, CheckInSource, TicketStatus, TicketValidationReason
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
        scan_payload=ticket.barcode_payload,
        barcode_signature=ticket.barcode_signature,
    )
    checkins = await ticket_service.sync_offline_checkins(context["staff"], [offline_scan])

    assert len(checkins) == 1
    assert checkins[0].source == CheckInSource.OFFLINE
    assert checkins[0].synced_at is not None

    refreshed_ticket = await ticket_service.tickets.get_by_registration_id(context["registration"].id)
    assert refreshed_ticket is not None
    assert refreshed_ticket.status == TicketStatus.CHECKED_IN
    refreshed_registration = await RegistrationService(db_session).get_registration_or_raise(
        context["registration"].id
    )
    assert refreshed_registration.status == RegistrationStatus.CHECKED_IN

    replay = await ticket_service.sync_offline_checkins(context["staff"], [offline_scan])
    assert replay[0].id == checkins[0].id

    with pytest.raises(DuplicateCheckInError):
        await ticket_service.check_in(refreshed_ticket.id, context["staff"], source=CheckInSource.ONLINE)


@pytest.mark.asyncio
async def test_offline_replay_requires_current_event_staff_authorization(db_session):
    context = await _make_ticket_context(db_session)
    ticket_service = TicketService(db_session)
    ticket = context["ticket"]
    offline_scan = OfflineCheckInIn(
        offline_batch_id="authorization-replay-1",
        scan_payload=ticket.barcode_payload,
        barcode_signature=ticket.barcode_signature,
    )

    await ticket_service.sync_offline_checkins(context["staff"], [offline_scan])

    assignment = (
        await db_session.execute(
            select(RoleAssignment).where(
                RoleAssignment.user_id == context["staff"].id,
                RoleAssignment.event_id == context["event"].id,
            )
        )
    ).scalar_one()
    await db_session.delete(assignment)
    await db_session.commit()

    with pytest.raises(InvalidTicketStateError, match="check in"):
        await ticket_service.sync_offline_checkins(context["staff"], [offline_scan])


@pytest.mark.asyncio
async def test_online_check_in_can_resolve_a_scanned_ticket_by_payload(db_session):
    """
    Regression test for a real gap found while building the mobile app's
    barcode scanner: POST /{ticket_id}/check-in requires the ticket's real
    UUID, but a scanned barcode payload only ever contains
    "{ticket_code}:{registration_id}:{payment_id_or_free}" — never the
    ticket's UUID. The offline sync path already resolved this
    internally; the online path (Staff Mode's single highest-frequency
    action) had no equivalent at all.
    """
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    ticket = ctx["ticket"]

    resolved = await service.resolve_by_scan_payload(ticket.barcode_payload, ticket.barcode_signature)
    assert resolved.id == ticket.id

    # The resolved ticket's real UUID is what actually unlocks check-in.
    check_in = await service.check_in(resolved.id, ctx["staff"], venue_id=None)
    assert check_in.ticket_id == ticket.id

    # A tampered/wrong signature is correctly rejected, not silently resolved.
    with pytest.raises(InvalidTicketStateError):
        await service.resolve_by_scan_payload(ticket.barcode_payload, "not-the-real-signature")


@pytest.mark.asyncio
async def test_structured_validation_covers_signature_scope_and_valid_ticket(db_session):
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    ticket = ctx["ticket"]
    valid = await service.validate_scan(ticket.barcode_payload, ticket.barcode_signature, ctx["staff"], event_id=ctx["event"].id)
    assert valid.valid is True and valid.reason == TicketValidationReason.VALID
    wrong_event = await service.validate_scan(ticket.barcode_payload, ticket.barcode_signature, ctx["staff"], event_id=uuid.uuid4())
    assert wrong_event.valid is False and wrong_event.reason == TicketValidationReason.WRONG_EVENT
    invalid = await service.validate_scan(ticket.barcode_payload, "forged", ctx["staff"])
    assert invalid.valid is False and invalid.reason == TicketValidationReason.INVALID_SIGNATURE


@pytest.mark.asyncio
async def test_access_policy_reentry_and_revocation_are_enforced(db_session):
    ctx = await _make_ticket_context(db_session)
    policy = AccessPolicy(event_id=ctx["event"].id, access_type="general", allowed_zone_ids=[], allows_reentry=True, max_entries=2)
    db_session.add(policy)
    await db_session.flush()
    ticket = ctx["ticket"]
    ticket.access_policy_id = policy.id
    await db_session.commit()
    service = TicketService(db_session)
    await service.check_in(ticket.id, ctx["staff"])
    second = await service.validate_scan(ticket.barcode_payload, ticket.barcode_signature, ctx["staff"], event_id=ctx["event"].id)
    assert second.valid is True
    await service.check_in(ticket.id, ctx["staff"])
    ticket.status = TicketStatus.REVOKED
    await db_session.commit()
    revoked = await service.validate_scan(ticket.barcode_payload, ticket.barcode_signature, ctx["staff"])
    assert revoked.valid is False and revoked.reason == TicketValidationReason.CANCELLED


@pytest.mark.asyncio
async def test_access_policy_assignment_and_unused_ticket_replacement_are_audited(db_session):
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    policy = AccessPolicy(event_id=ctx["event"].id, access_type="vip", allowed_zone_ids=[], allows_reentry=False, max_entries=1)
    db_session.add(policy)
    await db_session.flush()
    await service.assign_access_type(ctx["ticket"].id, "vip", ctx["staff"])
    replaced = await service.replace_ticket(ctx["ticket"].id, ctx["staff"])
    assert replaced.access_type == "vip" and replaced.entry_count == 0


@pytest.mark.asyncio
async def test_restricted_access_policy_fails_closed_without_zone(db_session):
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    policy = AccessPolicy(event_id=ctx["event"].id, access_type="general", allowed_zone_ids=[str(uuid.uuid4())], allows_reentry=False, max_entries=1)
    db_session.add(policy)
    await db_session.flush()
    ctx["ticket"].access_policy_id = policy.id
    await db_session.commit()
    result = await service.validate_scan(ctx["ticket"].barcode_payload, ctx["ticket"].barcode_signature, ctx["staff"])
    assert result.valid is False and result.reason == TicketValidationReason.ACCESS_DENIED


@pytest.mark.asyncio
async def test_barcode_payload_cannot_be_rebound_to_another_event(db_session):
    ctx = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    ticket = ctx["ticket"]
    assert ticket is not None

    rebound_payload = ticket.barcode_payload.replace(str(ctx["event"].id), str(ctx["registration"].id), 1)
    rebound_signature = service._sign_payload(rebound_payload)

    with pytest.raises(InvalidTicketStateError, match="different event"):
        await service.resolve_by_scan_payload(rebound_payload, rebound_signature)


@pytest.mark.asyncio
async def test_expired_event_ticket_cannot_be_checked_in(db_session):
    ctx = await _make_ticket_context(db_session)
    ctx["event"].end_date = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.flush()

    with pytest.raises(InvalidTicketStateError, match="expired"):
        await TicketService(db_session).check_in(ctx["ticket"].id, ctx["staff"])


@pytest.mark.asyncio
async def test_manual_ticket_code_lookup_works_without_a_signature(db_session):
    """
    The manual-entry fallback for a damaged/unreadable barcode,
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
