"""
Phase 4 payment coverage.
"""
import hashlib
import hmac
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.payments.models import PaymentStatus, RefundStatus
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.service import RegistrationService
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
    assert ticket.qr_signature

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
    assert refreshed_payment.status == PaymentStatus.REFUNDED
