"""Phase 16 ticket transfer, validity, and access-control coverage."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.notifications.models import Notification
from app.modules.identity.models import User
from app.modules.tickets.exceptions import InvalidTicketStateError
from app.modules.tickets.models import AccessPolicy, TicketStatus, TicketTransferStatus
from app.modules.tickets.service import TicketService

from tests.modules.tickets.test_tickets import _make_ticket_context


@pytest.mark.asyncio
async def test_ticket_transfer_changes_authoritative_owner_and_is_idempotently_notified(db_session):
    context = await _make_ticket_context(db_session)
    recipient = User(mobile_number="+919310000099")
    db_session.add(recipient)
    await db_session.flush()
    service = TicketService(db_session)

    transfer = await service.initiate_transfer(context["ticket"].id, context["registrant"], recipient.id)
    assert transfer.status == TicketTransferStatus.PENDING
    queued = list((await db_session.execute(select(Notification))).scalars())
    assert queued, "transfer notification was not queued"
    accepted = await service.respond_transfer(transfer.id, recipient, True)
    assert accepted.status == TicketTransferStatus.ACCEPTED

    ticket = await service.tickets.get_by_id(context["ticket"].id)
    assert ticket.user_id == recipient.id
    assert await service.can_access_ticket(ticket, context["registrant"]) is False
    assert (await db_session.execute(select(Notification).where(Notification.dedupe_key.like(f"ticket-transfer:{transfer.id}:%")))).scalars().all()


@pytest.mark.asyncio
async def test_used_ticket_cannot_be_transferred_and_valid_dates_fail_closed(db_session):
    context = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    policy = AccessPolicy(
        event_id=context["event"].id,
        access_type="general",
        allowed_zone_ids=[],
        allows_reentry=False,
        max_entries=1,
        valid_dates=[(datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()],
    )
    db_session.add(policy)
    await db_session.flush()
    ticket = context["ticket"]
    ticket.access_policy_id = policy.id
    ticket.valid_dates = policy.valid_dates
    await db_session.commit()

    validation = await service.validate_scan(ticket.barcode_payload, ticket.barcode_signature, context["staff"], event_id=context["event"].id)
    assert validation.valid is False
    assert validation.reason.value == "outside_time_window"

    ticket.valid_dates = None
    await db_session.commit()
    await service.check_in(ticket.id, context["staff"])
    recipient = User(mobile_number="+919310000098")
    db_session.add(recipient)
    await db_session.flush()
    with pytest.raises(InvalidTicketStateError):
        await service.initiate_transfer(ticket.id, context["registrant"], recipient.id)


@pytest.mark.asyncio
async def test_pending_transfer_cannot_be_replaced_or_accepted_by_wrong_user(db_session):
    context = await _make_ticket_context(db_session)
    recipient = User(mobile_number="+919310000097")
    attacker = User(mobile_number="+919310000096")
    db_session.add_all([recipient, attacker])
    await db_session.flush()
    service = TicketService(db_session)
    transfer = await service.initiate_transfer(context["ticket"].id, context["registrant"], recipient.id)

    with pytest.raises(InvalidTicketStateError):
        await service.initiate_transfer(context["ticket"].id, context["registrant"], attacker.id)
    with pytest.raises(InvalidTicketStateError):
        await service.respond_transfer(transfer.id, attacker, True)

    rejected = await service.respond_transfer(transfer.id, recipient, False)
    assert rejected.status == TicketTransferStatus.REJECTED


@pytest.mark.asyncio
async def test_reentry_requires_checkout_and_respects_limit(db_session):
    context = await _make_ticket_context(db_session)
    service = TicketService(db_session)
    policy = AccessPolicy(event_id=context["event"].id, access_type="general", allowed_zone_ids=[], allows_reentry=True, max_entries=2)
    db_session.add(policy)
    await db_session.flush()
    context["ticket"].access_policy_id = policy.id
    await db_session.commit()

    await service.check_in(context["ticket"].id, context["staff"])
    checked_out = await service.check_out(context["ticket"].id, context["staff"])
    assert checked_out.exited_at is not None
    await service.check_in(context["ticket"].id, context["staff"])
    await service.check_out(context["ticket"].id, context["staff"])
    with pytest.raises(InvalidTicketStateError):
        await service.check_out(context["ticket"].id, context["staff"])


@pytest.mark.asyncio
async def test_transfer_inbox_and_event_admin_queue_are_scoped_and_staff_cancel_is_idempotent(db_session):
    context = await _make_ticket_context(db_session)
    recipient = User(mobile_number="+919310000095")
    db_session.add(recipient)
    await db_session.flush()
    service = TicketService(db_session)

    transfer = await service.initiate_transfer(context["ticket"].id, context["registrant"], recipient.id)
    incoming, incoming_total = await service.page_incoming_transfers(recipient)
    assert incoming_total == 1
    assert incoming[0].id == transfer.id

    event_items, event_total = await service.page_event_transfers(context["event"].id, status="pending", page=1, page_size=1)
    assert event_total == 1
    assert event_items[0].event_id == context["event"].id

    cancelled = await service.cancel_transfer_as_staff(transfer.id, context["event"].id, context["staff"])
    assert cancelled.status == TicketTransferStatus.CANCELLED
    empty, total = await service.page_incoming_transfers(recipient)
    assert empty == []
    assert total == 0
    with pytest.raises(InvalidTicketStateError):
        await service.cancel_transfer_as_staff(transfer.id, context["event"].id, context["staff"])
