"""
Proves the reports module (previously a completely empty shell) works
against real data: a verified payment, an issued ticket, and a
check-in, all correctly reflected in both the operations and
financial aggregations.
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
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.service import RegistrationService
from app.modules.reports.service import ReportService
from app.modules.tickets.models import CheckInSource
from app.modules.tickets.service import TicketService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


def _gateway_signature(order_id: str, payment_id: str) -> str:
    secret = get_settings().payment_gateway_key_secret.encode()
    payload = f"{order_id}|{payment_id}".encode()
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


async def _make_event_with_paid_checked_in_registration(db_session):
    creator = User(mobile_number="+919700000001")
    registrant = User(mobile_number="+919700000002")
    staff = User(mobile_number="+919700000003")
    db_session.add_all([creator, registrant, staff])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=40)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Reports Fixture Event",
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
    await _assign_role(db_session, staff, RoleName.EVENT_MANAGER, event.id)

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

    payment_service = PaymentService(db_session)
    payment = await payment_service.initiate_payment(registration_id=registration.id, actor=registrant)
    gateway_payment_id = "pay_report_test_0001"
    signature = _gateway_signature(payment.gateway_order_id, gateway_payment_id)
    payment = await payment_service.handle_webhook(payment.gateway_order_id, gateway_payment_id, signature)

    ticket_service = TicketService(db_session)
    ticket = await ticket_service.tickets.get_by_registration_id(registration.id)
    await ticket_service.check_in(ticket.id, staff, source=CheckInSource.ONLINE)

    return event, staff, registration, payment


@pytest.mark.asyncio
async def test_event_operations_report_reflects_real_registrations_and_checkins(db_session):
    event, staff, registration, payment = await _make_event_with_paid_checked_in_registration(db_session)
    service = ReportService(db_session)

    report = await service.get_event_operations_report(event.id)

    assert report.event_id == event.id
    assert report.total_registrations == 1
    assert report.active_registrations == 1
    assert report.capacity == 50
    assert report.capacity_used == 1
    assert report.capacity_utilization_pct == 2.0
    assert report.total_check_ins == 1
    assert report.unique_tickets_checked_in == 1
    statuses = {b.status: b.count for b in report.registrations_by_status}
    assert sum(statuses.values()) == 1


@pytest.mark.asyncio
async def test_event_financial_report_reflects_verified_payment(db_session):
    event, staff, registration, payment = await _make_event_with_paid_checked_in_registration(db_session)
    service = ReportService(db_session)

    report = await service.get_event_financial_report(event.id)

    assert report.event_id == event.id
    assert report.total_revenue == Decimal("1000.00")
    assert report.verified_payment_count == 1
    assert report.pending_payment_count == 0
    assert report.failed_payment_count == 0
    assert report.total_refunded == Decimal("0")
    assert report.net_revenue == Decimal("1000.00")


@pytest.mark.asyncio
async def test_platform_operations_report_aggregates_across_events(db_session):
    event, staff, registration, payment = await _make_event_with_paid_checked_in_registration(db_session)
    service = ReportService(db_session)

    report = await service.get_platform_operations_report()

    assert report.total_events >= 1
    assert report.total_registrations_across_events >= 1
    assert report.total_check_ins_across_events >= 1
    assert any(e.event_id == event.id for e in report.events)


@pytest.mark.asyncio
async def test_event_summary_for_manager_excludes_refund_detail(db_session):
    """The scoped Event Manager view shows revenue collected, but its
    schema has no failed-payment/refund breakdown fields at all —
    that's the enforced boundary from the platform's role matrix."""
    event, staff, registration, payment = await _make_event_with_paid_checked_in_registration(db_session)
    service = ReportService(db_session)

    summary = await service.get_event_summary_for_manager(event.id)

    assert summary.revenue_collected == Decimal("1000.00")
    assert not hasattr(summary, "failed_payment_count")
    assert not hasattr(summary, "total_refunded")