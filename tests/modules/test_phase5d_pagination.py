"""Focused verification for the Phase 5C bounded collection endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from inspect import signature

import pytest
from sqlalchemy import select

from app.exceptions import PermissionDeniedError
from app.modules.assistance.models import AssistanceRequest, AssistanceRequestStatus
from app.modules.assistance.service import AssistanceService
from app.modules.assistance.router import list_assistance_requests
from app.modules.events.models import Event, EventStatus
from app.modules.events.repository import EventRepository
from app.modules.events.router import list_events
from app.modules.funnels.models import CompetitionStage, Entry, EntryStatus, StageType
from app.modules.funnels.router import list_entries
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository
from app.modules.identity.service import IdentityService
from app.modules.identity.router import list_accounts
from app.modules.media.models import Media, MediaType
from app.modules.media.service import MediaService
from app.modules.media.router import list_event_media
from app.modules.notifications.models import Notification, NotificationChannel, NotificationDeliveryStatus
from app.modules.notifications.service import NotificationService
from app.modules.notifications.router import list_notifications_for_event
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.sponsorships.models import SponsorshipInquiry, SponsorshipInquiryEvent, SponsorshipInquiryStatus
from app.modules.sponsorships.service import SponsorshipService
from app.modules.sponsorships.router import list_inquiries
from app.modules.staff.models import StaffAssignment, StaffAssignmentStatus
from app.modules.staff.service import StaffService
from app.modules.staff.router import list_staff_assignments
from app.modules.teams.models import Team, TeamStatus
from app.modules.teams.router import list_teams
from app.modules.tickets.models import CheckIn, CheckInSource, Ticket
from app.modules.tickets.router import list_checkins
from app.modules.tickets.service import TicketService
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationStatus, VolunteerApplicationType
from app.modules.volunteers.service import VolunteerService
from app.modules.volunteers.router import list_manageable


def test_all_phase5c_page_sizes_have_a_server_enforced_maximum():
    routes = (
        list_events,
        list_accounts,
        list_notifications_for_event,
        list_checkins,
        list_manageable,
        list_inquiries,
        list_staff_assignments,
        list_teams,
        list_assistance_requests,
        list_event_media,
        list_entries,
    )
    for route in routes:
        page_size = signature(route).parameters["page_size"].default
        assert any(getattr(metadata, "le", None) == 100 for metadata in page_size.metadata)


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _event(db, suffix: str) -> Event:
    creator = User(mobile_number=f"+919700000{suffix}")
    db.add(creator)
    await db.flush()
    start = datetime.now(timezone.utc) + timedelta(days=10)
    event = Event(
        name=f"Pagination Event {suffix}",
        description="fixture",
        category="test",
        start_date=start,
        end_date=start + timedelta(days=1),
        status=EventStatus.PUBLISHED,
        created_by=creator.id,
    )
    db.add(event)
    await db.flush()
    return event


@pytest.mark.asyncio
async def test_events_and_accounts_are_bounded_and_stable(db_session, fake_redis):
    event_a = await _event(db_session, "101")
    event_b = await _event(db_session, "102")
    events, total = await EventRepository(db_session).page_all(
        include_all_statuses=True, page=1, page_size=1
    )
    assert total == 2
    assert len(events) == 1
    events_2, _ = await EventRepository(db_session).page_all(
        include_all_statuses=True, page=2, page_size=1
    )
    assert {events[0].id, events_2[0].id} == {event_a.id, event_b.id}
    empty, empty_total = await EventRepository(db_session).page_all(
        include_all_statuses=True, page=99, page_size=1
    )
    assert empty == [] and empty_total == 2

    users, user_total = await UserRepository(db_session).page_all(page=1, page_size=1)
    assert len(users) == 1 and user_total == 2
    page_accounts, account_total = await IdentityService(db_session, fake_redis).page_accounts(page=99, page_size=25)
    assert page_accounts == [] and account_total == 2


@pytest.mark.asyncio
async def test_notifications_are_event_scoped_and_paginated(db_session):
    event_a = await _event(db_session, "103")
    event_b = await _event(db_session, "104")
    manager = User(mobile_number="+919700000105")
    outsider = User(mobile_number="+919700000106")
    recipient = User(mobile_number="+919700000107")
    db_session.add_all([manager, outsider, recipient])
    await db_session.flush()
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    for event in (event_a, event_b):
        db_session.add(Notification(
            event_id=event.id, recipient_user_id=recipient.id,
            channel=NotificationChannel.PUSH, title="Notice", body=str(event.id),
            delivery_status=NotificationDeliveryStatus.SENT,
        ))
    await db_session.flush()
    items, total = await NotificationService(db_session).page_notifications_for_event(
        manager, event_a.id, page=1, page_size=1
    )
    assert len(items) == 1 and total == 1 and items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await NotificationService(db_session).page_notifications_for_event(outsider, event_a.id)
    assert await NotificationService(db_session).page_notifications_for_event(
        manager, event_a.id, page=2, page_size=1
    ) == ([], 1)


@pytest.mark.asyncio
async def test_checkins_are_event_scoped_and_page_without_full_load(db_session):
    event_a = await _event(db_session, "108")
    event_b = await _event(db_session, "109")
    manager = User(mobile_number="+919700000110")
    outsider = User(mobile_number="+919700000111")
    scanner = User(mobile_number="+919700000112")
    db_session.add_all([manager, outsider, scanner])
    await db_session.flush()
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    for event in (event_a, event_b):
        ticket = Ticket(event_id=event.id, registration_id=event.id, user_id=scanner.id, ticket_code=f"TKT-{event.id}", barcode_payload="payload", barcode_signature="signature")
        db_session.add(ticket)
        await db_session.flush()
        db_session.add(CheckIn(ticket_id=ticket.id, event_id=event.id, scanned_by=scanner.id, source=CheckInSource.ONLINE))
    await db_session.flush()
    page = await list_checkins(str(event_a.id), page=1, page_size=1, current_user=manager, db=db_session, service=TicketService(db_session))
    assert page.total == 1 and len(page.items) == 1 and page.items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await list_checkins(str(event_a.id), page=1, page_size=1, current_user=outsider, db=db_session, service=TicketService(db_session))


@pytest.mark.asyncio
async def test_volunteers_and_sponsorship_inquiries_preserve_event_scope(db_session):
    event_a = await _event(db_session, "113")
    event_b = await _event(db_session, "114")
    manager = User(mobile_number="+919700000115")
    outsider = User(mobile_number="+919700000116")
    applicant = User(mobile_number="+919700000117")
    db_session.add_all([manager, outsider, applicant])
    await db_session.flush()
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    for event in (event_a, event_b):
        db_session.add(VolunteerApplication(
            event_id=event.id, user_id=applicant.id, application_type=VolunteerApplicationType.VOLUNTEER,
            full_name=f"Applicant {event.id}", phone=applicant.mobile_number,
            status=VolunteerApplicationStatus.SUBMITTED,
        ))
    inquiry_a = SponsorshipInquiry(
        user_id=applicant.id, company_name="Company A", contact_person="Contact A",
        phone=applicant.mobile_number, email="a@example.com", status=SponsorshipInquiryStatus.NEW,
    )
    inquiry_b = SponsorshipInquiry(
        user_id=applicant.id, company_name="Company B", contact_person="Contact B",
        phone=applicant.mobile_number, email="b@example.com", status=SponsorshipInquiryStatus.NEW,
    )
    db_session.add_all([inquiry_a, inquiry_b])
    await db_session.flush()
    db_session.add_all([
        SponsorshipInquiryEvent(inquiry_id=inquiry_a.id, event_id=event_a.id),
        SponsorshipInquiryEvent(inquiry_id=inquiry_b.id, event_id=event_b.id),
    ])
    await db_session.flush()

    volunteer_items, volunteer_total = await VolunteerService(db_session).page_manageable(
        manager, page=1, page_size=1, search="Applicant"
    )
    assert volunteer_total == 1 and volunteer_items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await VolunteerService(db_session).page_manageable(outsider, event_id=event_a.id)

    sponsor_items, sponsor_total = await SponsorshipService(db_session).page_manageable_inquiries(
        manager, page=1, page_size=1, search="Company"
    )
    assert sponsor_total == 1 and sponsor_items[0].id == inquiry_a.id
    with pytest.raises(PermissionDeniedError):
        await SponsorshipService(db_session).page_manageable_inquiries(outsider, event_id=event_a.id)


@pytest.mark.asyncio
async def test_staff_and_teams_are_scoped_and_paginated(db_session):
    event_a = await _event(db_session, "118")
    event_b = await _event(db_session, "119")
    manager = User(mobile_number="+919700000120")
    outsider = User(mobile_number="+919700000121")
    invitee = User(mobile_number="+919700000122")
    db_session.add_all([manager, outsider, invitee])
    await db_session.flush()
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    staff = StaffAssignment(
        event_id=event_a.id, invitee_mobile=invitee.mobile_number, full_name="Invitee",
        role_label="Marshal", role_name=RoleName.STAFF_MEMBER,
        status=StaffAssignmentStatus.INVITED, invited_by=manager.id,
    )
    db_session.add(staff)
    team_a = Team(event_id=event_a.id, captain_user_id=invitee.id, name="A", status=TeamStatus.DRAFT)
    team_b = Team(event_id=event_b.id, captain_user_id=invitee.id, name="B", status=TeamStatus.DRAFT)
    db_session.add_all([team_a, team_b])
    await db_session.flush()

    staff_items, staff_total = await StaffService(db_session).page_assignments(event_id=event_a.id, actor=manager, page=1, page_size=1)
    assert staff_total == 1 and staff_items[0].event_id == event_a.id
    teams = await list_teams(event_id=event_a.id, page=1, page_size=1, current_user=manager, db=db_session, service=__import__("app.modules.teams.service", fromlist=["TeamService"]).TeamService(db_session))
    assert teams.total == 1 and teams.items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await list_teams(event_id=event_a.id, page=1, page_size=1, current_user=outsider, db=db_session, service=__import__("app.modules.teams.service", fromlist=["TeamService"]).TeamService(db_session))


@pytest.mark.asyncio
async def test_assistance_media_and_competition_entries_are_bounded_and_scoped(db_session):
    event_a = await _event(db_session, "123")
    event_b = await _event(db_session, "124")
    manager = User(mobile_number="+919700000125")
    outsider = User(mobile_number="+919700000126")
    requester = User(mobile_number="+919700000127")
    db_session.add_all([manager, outsider, requester])
    await db_session.flush()
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)

    request = AssistanceRequest(
        event_id=event_a.id, registration_id=event_a.id, requester_user_id=requester.id,
        status=AssistanceRequestStatus.PENDING, reason="Need help", requested_fee_waiver_amount=Decimal("10"),
    )
    db_session.add(request)
    media_a = Media(event_id=event_a.id, uploaded_by=manager.id, title="A", media_type=MediaType.IMAGE, storage_key="a", public_url="https://example.com/a", is_published=True, sort_order=1)
    media_draft = Media(event_id=event_a.id, uploaded_by=manager.id, title="Draft", media_type=MediaType.IMAGE, storage_key="draft", public_url="https://example.com/draft", is_published=False, sort_order=2)
    db_session.add_all([media_a, media_draft])
    stage = CompetitionStage(event_id=event_a.id, name="Vote", stage_type=StageType.PUBLIC_VOTE, order_index=1)
    db_session.add(stage)
    await db_session.flush()
    entry = Entry(event_id=event_a.id, registration_id=event_a.id, current_stage_id=stage.id, status=EntryStatus.ACTIVE)
    db_session.add(entry)
    await db_session.flush()

    assistance_items, assistance_total = await AssistanceService(db_session).page_requests(event_id=event_a.id, actor=manager, page=1, page_size=1)
    assert assistance_total == 1 and assistance_items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await AssistanceService(db_session).page_requests(event_id=event_a.id, actor=outsider)

    public_media, media_total = await MediaService(db_session).page_event_media(event_a.id, None, page=1, page_size=1)
    assert media_total == 1 and public_media[0].is_published is True
    managed_media, managed_total = await MediaService(db_session).page_event_media(event_a.id, manager, page=1, page_size=1)
    assert managed_total == 2 and len(managed_media) == 1

    entries = await list_entries(stage_id=str(stage.id), page=1, page_size=1, current_user=manager, db=db_session, service=__import__("app.modules.funnels.service", fromlist=["FunnelService"]).FunnelService(db_session))
    assert entries.total == 1 and entries.items[0].event_id == event_a.id
    with pytest.raises(PermissionDeniedError):
        await list_entries(stage_id=str(stage.id), page=1, page_size=1, current_user=outsider, db=db_session, service=__import__("app.modules.funnels.service", fromlist=["FunnelService"]).FunnelService(db_session))
