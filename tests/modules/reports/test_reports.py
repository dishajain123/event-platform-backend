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
from app.modules.registrations.models import RegistrationStatus
from app.modules.reports.service import ReportService
from app.modules.reports.analytics_service import AnalyticsService
from app.modules.tickets.models import CheckInSource
from app.modules.tickets.service import TicketService
from app.modules.waitlists.models import WaitlistEntry, WaitlistStatus
from app.modules.reports.exceptions import ReportEventNotFoundError
from app.exceptions import PermissionDeniedError


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
async def test_phase22_analytics_is_authoritative_and_zero_safe(db_session):
    event, staff, registration, payment = await _make_event_with_paid_checked_in_registration(db_session)
    analytics = AnalyticsService(db_session)
    result = await analytics.overview(event.id, include_financial=True)
    assert result["registrations"]["total"] == 1
    assert result["attendance"]["check_ins"] == 1
    assert result["revenue"]["gross"] == Decimal("1000.00")
    assert result["revenue"]["net_collected"] == Decimal("1000.00")
    series = await analytics.timeseries(event.id)
    assert series["registrations"]
    assert series["payments"]


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


@pytest.mark.asyncio
async def test_command_center_aggregates_authoritative_event_state(db_session):
    event, staff, registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    db_session.add(WaitlistEntry(
        event_id=event.id,
        user_id=registration.user_id,
        participation_type="individual",
        status=WaitlistStatus.WAITING,
        joined_at=datetime.now(timezone.utc),
    ))
    await db_session.flush()

    result = await ReportService(db_session).get_command_center(
        event_ids={event.id}, event_id=event.id, page=1, page_size=25,
    )

    assert result.total == 1
    assert len(result.items) == 1
    item = result.items[0]
    assert item.capacity == 50
    assert item.capacity_used == 1
    assert item.tickets["checked_in"] == 1
    assert item.waitlist["waiting"] == 1
    assert any(alert.code == "waitlist_attention" for alert in result.alerts)
    assert result.totals.registrations["checked_in"] == 1


@pytest.mark.asyncio
async def test_command_center_empty_event_is_safe(db_session):
    creator = User(mobile_number="+919700000099")
    db_session.add(creator)
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=20)
    event = await EventService(db_session).create_event(
        created_by=creator.id, name="Empty Operations Event", description=None,
        category="test", start_date=start, end_date=start + timedelta(days=1), organization_id=None,
    )

    result = await ReportService(db_session).get_command_center(
        event_ids={event.id}, page=1, page_size=25,
    )

    assert result.total == 1
    assert result.items[0].capacity_used == 0
    assert all(value == 0 for value in result.items[0].registrations.values())
    assert all(value == 0 for value in result.items[0].tickets.values())


@pytest.mark.asyncio
async def test_command_center_rejects_unassigned_event(db_session):
    event, _staff, _registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    outsider = User(mobile_number="+919700000098")
    db_session.add(outsider)
    await db_session.flush()

    with pytest.raises(PermissionDeniedError):
        await ReportService(db_session).get_command_center(
            event_ids=set(), event_id=event.id, page=1, page_size=25,
        )


@pytest.mark.asyncio
async def test_attendance_report_distinguishes_attendees_no_shows_and_reentries(db_session):
    event, staff, attended, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    no_show_user = User(mobile_number="+919700000077", name="No Show")
    db_session.add(no_show_user)
    await db_session.flush()
    no_show = await RegistrationService(db_session).create_registration(
        event_id=event.id, actor=no_show_user, participation_type="individual",
        date_of_birth=date(2012, 1, 1), child_id=None, team_id=None,
        documents_provided=[], answers={}, participants=[],
    )
    no_show.status = RegistrationStatus.CONFIRMED
    await db_session.flush()

    report = await ReportService(db_session).get_event_attendance_report(event.id)
    assert report.eligible_registrations == 2
    assert report.checked_in_participants == 1
    assert report.no_shows == 1
    assert report.attendance_rate_pct == 50.0
    assert report.total_entries == 1
    assert report.reentry_count == 0
    page = await ReportService(db_session).page_event_attendance_participants(
        event.id, page=1, page_size=1, attendance="no_show"
    )
    assert page.total == 1
    assert page.items[0].registration_id == no_show.id
    assert page.items[0].attendance_status == "no_show"


@pytest.mark.asyncio
async def test_attendance_report_is_empty_safe(db_session):
    creator = User(mobile_number="+919700000076")
    db_session.add(creator)
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=20)
    event = await EventService(db_session).create_event(
        created_by=creator.id, name="Empty Attendance Event", description=None,
        category="test", start_date=start, end_date=start + timedelta(days=1), organization_id=None,
    )
    report = await ReportService(db_session).get_event_attendance_report(event.id)
    assert report.eligible_registrations == 0
    assert report.checked_in_participants == 0
    assert report.no_shows == 0
    assert report.attendance_rate_pct is None
    assert report.checkins_over_time == []


@pytest.mark.asyncio
async def test_attendance_history_is_scoped_to_owner(db_session):
    event, _staff, registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    page = await ReportService(db_session).page_my_attendance_history(registration.user_id, page=1, page_size=100)
    assert page.total == 1
    assert page.items[0].event_id == event.id
    assert page.items[0].attended is True
    other = User(mobile_number="+919700000075")
    db_session.add(other)
    await db_session.flush()
    other_page = await ReportService(db_session).page_my_attendance_history(other.id, page=1, page_size=100)
    assert other_page.total == 0
    assert other_page.items == []


@pytest.mark.asyncio
async def test_command_center_global_and_manager_scopes_are_event_bounded(db_session):
    event, _staff, _registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    creator = User(mobile_number="+919700000097")
    db_session.add(creator)
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=25)
    other_event = await EventService(db_session).create_event(
        created_by=creator.id, name="Second Operations Event", description=None,
        category="test", start_date=start, end_date=start + timedelta(days=1), organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        other_event.id, participation_types=["individual"], fee_amount=None,
        currency="INR", capacity=10, approval_required=False, rules={}, discount_rules=None,
    )

    global_view = await ReportService(db_session).get_command_center(
        event_ids=None, page=1, page_size=25,
    )
    manager_view = await ReportService(db_session).get_command_center(
        event_ids={event.id}, page=1, page_size=25,
    )

    assert global_view.total == 2
    assert {item.event_id for item in manager_view.items} == {event.id}
    with pytest.raises(PermissionDeniedError):
        await ReportService(db_session).get_command_center(
            event_ids={event.id}, event_id=other_event.id, page=1, page_size=25,
        )


@pytest.mark.asyncio
async def test_scoped_event_manager_can_reach_analytics_and_attendance_access_checks(db_session):
    """
    Regression test for a bug found in audit: reports/router.py's
    _require_analytics_access() and _require_attendance_access() both call
    user_has_scoped_role(), which the module never imported — a NameError
    that's invisible to a global-role admin (the `or`'s first operand
    short-circuits before the undefined name is ever touched) but crashes
    every scoped Event Manager, the exact audience these endpoints are for.

    The existing tests in this file only ever call ReportService/
    AnalyticsService directly, bypassing router.py entirely, which is why
    the bug shipped despite a passing test suite. This test calls the
    router-level helper functions themselves, as a scoped-only (non-global)
    Event Manager, so this specific class of "the router helper references
    a name it never imported" bug can't silently reappear.
    """
    from app.modules.reports.router import _require_analytics_access, _require_attendance_access

    event, staff, _registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)

    # staff holds EVENT_MANAGER scoped to `event` only (see the fixture) —
    # no global role — so the first operand of the `or` in both helpers
    # evaluates to False and must fall through to user_has_scoped_role().
    assert await _require_analytics_access(event.id, staff, db_session) in (True, False)
    assert await _require_attendance_access(event.id, staff, db_session) is None

    # And an actor with no relationship to the event at all is still
    # correctly rejected, not just "doesn't crash".
    stranger = User(mobile_number="+919700000098")
    db_session.add(stranger)
    await db_session.flush()
    with pytest.raises(PermissionDeniedError):
        await _require_analytics_access(event.id, stranger, db_session)
    with pytest.raises(PermissionDeniedError):
        await _require_attendance_access(event.id, stranger, db_session)


@pytest.mark.asyncio
async def test_attendance_history_excludes_non_attending_registrations(db_session):
    """
    Regression test for a bug found in audit: page_attendance_history()
    computed its eligible-status filter (CONFIRMED/CHECKED_IN/REFUND_FAILED)
    but never applied it to the query, so a user's "my attendance history"
    included every registration regardless of status.
    """
    event, staff, registration, _payment = await _make_event_with_paid_checked_in_registration(db_session)
    registrant = await db_session.get(User, registration.user_id)

    # A second, cancelled registration for the same user at a different
    # event must NOT show up in their attendance history.
    creator = User(mobile_number="+919700000099")
    db_session.add(creator)
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=60)
    other_event = await EventService(db_session).create_event(
        created_by=creator.id, name="Cancelled-Only Event", description=None,
        category="test", start_date=start, end_date=start + timedelta(days=1), organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        other_event.id, participation_types=["individual"], fee_amount=None,
        currency="INR", capacity=10, approval_required=False, rules={}, discount_rules=None,
    )
    other_registration = await RegistrationService(db_session).create_registration(
        event_id=other_event.id, actor=registrant, participation_type="individual",
        date_of_birth=date(2012, 1, 1), child_id=None, team_id=None,
        documents_provided=[], answers={}, participants=[],
    )
    other_registration.status = RegistrationStatus.CANCELLED
    await db_session.flush()

    items, total = await ReportService(db_session).repo.page_attendance_history(registrant.id, page=1, page_size=25)

    assert total == 1
    assert {item[2] for item in items} == {registration.id}
    assert other_registration.id not in {item[2] for item in items}