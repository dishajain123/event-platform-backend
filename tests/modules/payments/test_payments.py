"""
Phase 4 payment coverage.
"""
import hashlib
import hmac
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.payments.models import PaymentStatus, PaymentWebhookInbox, RefundStatus, WebhookProcessingStatus
from app.modules.payments.exceptions import PaymentVerificationFailedError
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.service import RegistrationService
from app.modules.registrations.models import RegistrationStatus
from app.integrations.payment_gateway_client import RazorpayPaymentGatewayClient
from app.modules.tickets.exceptions import InvalidTicketStateError
from app.modules.tickets.models import CheckInSource, TicketStatus
from app.modules.tickets.service import TicketService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_paid_registration(db_session):
    creator = User(mobile_number="+919300000001")
    registrant = User(mobile_number="+919300000002")
    staff = User(mobile_number="+919300000003")
    operator = User(mobile_number="+919300000004")
    admin = User(mobile_number="+919300000005")
    db_session.add_all([creator, registrant, staff, operator, admin])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=45)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 4 Payments Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=1000.0,
        currency="INR",
        capacity=50,
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
    await _assign_role(db_session, operator, RoleName.FINANCE_OPERATOR)
    await _assign_role(db_session, admin, RoleName.FINANCE_ADMIN)

    return {
        "event": event,
        "registrant": registrant,
        "staff": staff,
        "operator": operator,
        "admin": admin,
        "registration": registration,
        "payment": payment,
    }


def _gateway_signature(order_id: str, payment_id: str) -> str:
    secret = get_settings().payment_gateway_key_secret.encode()
    payload = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _webhook_signature(body: bytes) -> str:
    secret = get_settings().payment_gateway_webhook_secret.encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


@pytest.mark.asyncio
async def test_payment_webhook_issues_ticket_and_refund_flow(db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    ticket_service = TicketService(db_session)

    gateway_payment_id = "pay_test_0001"
    signature = _gateway_signature(context["payment"].gateway_order_id, gateway_payment_id)

    payment = await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        gateway_payment_id,
        signature,
    )

    assert payment.status == PaymentStatus.VERIFIED
    assert payment.gateway_payment_id == gateway_payment_id
    assert payment.registration_id == context["registration"].id

    ticket = await ticket_service.tickets.get_by_registration_id(context["registration"].id)
    assert ticket is not None
    assert ticket.status == TicketStatus.ISSUED
    assert ticket.barcode_signature

    second_pass = await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        gateway_payment_id,
        signature,
    )
    assert second_pass.status == PaymentStatus.VERIFIED
    assert (await ticket_service.tickets.get_by_registration_id(context["registration"].id)).id == ticket.id

    check_in = await ticket_service.check_in(ticket.id, context["staff"], source=CheckInSource.ONLINE)
    assert check_in.source == CheckInSource.ONLINE
    assert ticket.status == TicketStatus.CHECKED_IN

    refund = await payment_service.request_refund(
        payment_id=payment.id,
        actor=context["operator"],
        amount=Decimal("250.00"),
        reason="Partial refund requested by finance",
    )
    assert refund.status == RefundStatus.PENDING_ADMIN_APPROVAL

    approved = await payment_service.approve_refund(
        refund.id,
        context["admin"],
        reason="Approved after review",
    )
    assert approved.status == RefundStatus.PROCESSED
    assert approved.gateway_refund_id is not None
    assert approved.processed_at is not None

    refreshed_payment = await payment_service.payments.get_by_id(payment.id)
    assert refreshed_payment is not None
    # A partial refund does not invalidate the payment or its already-used
    # ticket. Full refunds transition the payment to REFUNDED and cancel an
    # unused issued ticket.
    assert refreshed_payment.status == PaymentStatus.VERIFIED
    assert (await RegistrationService(db_session).get_registration_or_raise(context["registration"].id)).status == RegistrationStatus.CONFIRMED


@pytest.mark.asyncio
async def test_paid_cancellation_waits_for_full_refund_then_cancels_ticket(db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        "pay_test_cancel",
        _gateway_signature(context["payment"].gateway_order_id, "pay_test_cancel"),
    )

    registration_service = RegistrationService(db_session)
    pending = await registration_service.cancel_registration(
        context["registration"].id, context["registrant"], "Cannot attend"
    )
    assert pending.status == RegistrationStatus.REFUND_PENDING
    assert await registration_service.registrations.count_active_for_event(context["event"].id) == 1

    refund = await payment_service.refunds.list_all()
    approved = await payment_service.approve_refund(refund[-1].id, context["admin"], "Approved")
    assert approved.status == RefundStatus.PROCESSED
    cancelled = await registration_service.get_registration_or_raise(context["registration"].id)
    assert cancelled.status == RegistrationStatus.CANCELLED
    ticket = await TicketService(db_session).tickets.get_by_registration_id(context["registration"].id)
    assert ticket.status == TicketStatus.CANCELLED


@pytest.mark.asyncio
async def test_failed_refund_keeps_payment_and_ticket_valid(monkeypatch, db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        "pay_test_failed_refund",
        _gateway_signature(context["payment"].gateway_order_id, "pay_test_failed_refund"),
    )
    await RegistrationService(db_session).cancel_registration(
        context["registration"].id, context["registrant"], "Please refund"
    )

    def fail_refund(**_kwargs):
        raise RuntimeError("gateway unavailable")

    monkeypatch.setattr(RazorpayPaymentGatewayClient, "initiate_refund", fail_refund)
    refund = (await payment_service.refunds.list_all())[-1]
    failed = await payment_service.approve_refund(refund.id, context["admin"], "Retry later")
    assert failed.status == RefundStatus.FAILED
    registration = await RegistrationService(db_session).get_registration_or_raise(context["registration"].id)
    assert registration.status == RegistrationStatus.REFUND_FAILED
    assert (await payment_service.payments.get_by_id(context["payment"].id)).status == PaymentStatus.VERIFIED


@pytest.mark.asyncio
async def test_cancelled_registration_cannot_check_in(db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        "pay_test_cancel_checkin",
        _gateway_signature(context["payment"].gateway_order_id, "pay_test_cancel_checkin"),
    )
    registration_service = RegistrationService(db_session)
    await registration_service.cancel_registration(context["registration"].id, context["registrant"])
    refund = (await payment_service.refunds.list_all())[-1]
    await payment_service.approve_refund(refund.id, context["admin"], "Approved")
    ticket = await TicketService(db_session).tickets.get_by_registration_id(context["registration"].id)
    with pytest.raises(InvalidTicketStateError):
        await TicketService(db_session).check_in(ticket.id, context["staff"])


@pytest.mark.asyncio
async def test_razorpay_webhook_is_durable_and_idempotent(db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    payload = {
        "id": "evt_payment_captured_1",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_webhook_1",
                    "order_id": context["payment"].gateway_order_id,
                    "amount": 100000,
                    "currency": "INR",
                }
            }
        },
    }
    body = json.dumps(payload).encode()
    first = await payment_service.handle_gateway_webhook(body, _webhook_signature(body), payload)
    second = await payment_service.handle_gateway_webhook(body, _webhook_signature(body), payload)

    assert first.status == PaymentStatus.VERIFIED
    assert second.id == first.id
    inbox = (await db_session.execute(select(PaymentWebhookInbox))).scalar_one()
    assert inbox.processing_status == WebhookProcessingStatus.PROCESSED
    assert inbox.attempts == 1
    assert await TicketService(db_session).tickets.get_by_registration_id(context["registration"].id) is not None


@pytest.mark.asyncio
async def test_webhook_amount_mismatch_is_rejected_before_confirmation(db_session):
    context = await _make_paid_registration(db_session)
    payload = {
        "id": "evt_payment_amount_mismatch",
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_amount_mismatch",
                    "order_id": context["payment"].gateway_order_id,
                    "amount": 1,
                    "currency": "INR",
                }
            }
        },
    }
    body = json.dumps(payload).encode()

    with pytest.raises(PaymentVerificationFailedError):
        await PaymentService(db_session).handle_gateway_webhook(
            body, _webhook_signature(body), payload
        )

    await db_session.refresh(context["payment"])
    assert context["payment"].status == PaymentStatus.INITIATED
    inbox = (
        await db_session.execute(
            select(PaymentWebhookInbox).where(
                PaymentWebhookInbox.provider_event_id == "evt_payment_amount_mismatch"
            )
        )
    ).scalar_one()
    assert inbox.processing_status == WebhookProcessingStatus.FAILED


@pytest.mark.asyncio
async def test_invalid_webhook_signature_is_not_persisted(db_session):
    context = await _make_paid_registration(db_session)
    payload = {
        "id": "evt_invalid_signature",
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_bad", "order_id": context["payment"].gateway_order_id}}},
    }
    body = json.dumps(payload).encode()
    with pytest.raises(Exception):
        await PaymentService(db_session).handle_gateway_webhook(body, "forged", payload)
    assert (await db_session.execute(select(PaymentWebhookInbox))).scalars().all() == []


@pytest.mark.asyncio
async def test_processed_refund_webhook_completes_registration_lifecycle(db_session):
    context = await _make_paid_registration(db_session)
    payment_service = PaymentService(db_session)
    await payment_service.handle_webhook(
        context["payment"].gateway_order_id,
        "pay_refund_webhook",
        _gateway_signature(context["payment"].gateway_order_id, "pay_refund_webhook"),
    )
    await RegistrationService(db_session).cancel_registration(
        context["registration"].id, context["registrant"], "Please refund"
    )
    refund = (await payment_service.refunds.list_all())[-1]
    refund.status = RefundStatus.PROCESSING
    refund.gateway_refund_id = "rfnd_webhook_1"
    await db_session.commit()
    payload = {
        "id": "evt_refund_processed_1",
        "event": "refund.processed",
        "payload": {
            "refund": {
                "entity": {
                    "id": refund.gateway_refund_id,
                    "payment_id": context["payment"].gateway_payment_id,
                    "amount": 100000,
                    "status": "processed",
                }
            }
        },
    }
    body = json.dumps(payload).encode()
    await payment_service.handle_gateway_webhook(body, _webhook_signature(body), payload)
    registration = await RegistrationService(db_session).get_registration_or_raise(context["registration"].id)
    ticket = await TicketService(db_session).tickets.get_by_registration_id(context["registration"].id)
    assert registration.status == RegistrationStatus.CANCELLED
    assert ticket.status == TicketStatus.CANCELLED
    assert (await payment_service.payments.get_by_id(context["payment"].id)).status == PaymentStatus.REFUNDED
