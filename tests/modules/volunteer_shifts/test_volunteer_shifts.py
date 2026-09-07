from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.volunteers.models import VolunteerApplicationStatus
from app.modules.volunteers.service import VolunteerService
from app.modules.volunteer_shifts.models import VolunteerAssignmentStatus, VolunteerAttendanceStatus, VolunteerShiftStatus
from app.modules.volunteer_shifts.schemas import ShiftCreateIn, ShiftUpdateIn
from app.modules.volunteer_shifts.service import VolunteerShiftService
from app.modules.notifications.service import NotificationService


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _event_and_application(db):
    creator = User(mobile_number="+919700000001")
    volunteer = User(mobile_number="+919700000002")
    manager = User(mobile_number="+919700000003")
    outsider = User(mobile_number="+919700000004")
    db.add_all([creator, volunteer, manager, outsider]); await db.flush()
    events = EventService(db)
    event = await events.create_event(created_by=creator.id, name="Shift Event", description=None, category="sport",
                                      start_date=datetime.now(timezone.utc) - timedelta(hours=1),
                                      end_date=datetime.now(timezone.utc) + timedelta(hours=4), organization_id=None)
    await ConfigEngineService(db).upsert_configuration(event.id, participation_types=["viewer"], fee_amount=None,
                                                        currency="INR", capacity=20, approval_required=False, rules={}, discount_rules=None)
    event = await events.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    event = await events.publish(event.id, creator.id)
    await _role(db, manager, RoleName.EVENT_MANAGER, event.id)
    application = await VolunteerService(db).create_application(volunteer, {
        "event_id": event.id, "full_name": "Approved Volunteer", "phone": volunteer.mobile_number,
        "skills_experience": "first aid", "preferred_responsibility": "gate",
    })
    await VolunteerService(db).update_status(manager, application.id, VolunteerApplicationStatus.APPROVED)
    return event, creator, volunteer, manager, outsider


@pytest.mark.asyncio
async def test_shift_assignment_capacity_overlap_and_scoping(db_session):
    event, _, volunteer, manager, outsider = await _event_and_application(db_session)
    service = VolunteerShiftService(db_session)
    now = datetime.now(timezone.utc)
    shift = await service.create_shift(manager, event.id, ShiftCreateIn(title="Gate", starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), required_count=1, status=VolunteerShiftStatus.OPEN))
    eligible, eligible_total = await service.eligible_volunteers(manager, shift.id)
    assert eligible_total == 1 and eligible[0].user_id == volunteer.id
    assignment = await service.assign_shift(manager, shift.id, volunteer.id)
    assert assignment.status == VolunteerAssignmentStatus.APPROVED
    with pytest.raises(ConflictError):
        await service.assign_shift(manager, shift.id, volunteer.id)
    assert (await service.get_visible_shift(manager, shift.id)).assigned_count == 1
    eligible, eligible_total = await service.eligible_volunteers(manager, shift.id)
    assert eligible == [] and eligible_total == 0
    with pytest.raises(PermissionDeniedError):
        await service.get_visible_shift(outsider, shift.id)
    assert (await service.get_visible_shift(manager, shift.id)).status == VolunteerShiftStatus.FULL


@pytest.mark.asyncio
async def test_shift_attendance_lifecycle_and_duplicate_protection(db_session):
    event, _, volunteer, manager, _ = await _event_and_application(db_session)
    service = VolunteerShiftService(db_session)
    now = datetime.now(timezone.utc)
    shift = await service.create_shift(manager, event.id, ShiftCreateIn(title="Welcome desk", starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), required_count=2, status=VolunteerShiftStatus.OPEN))
    assignment = await service.assign_shift(manager, shift.id, volunteer.id)
    attendance = await service.check_in(volunteer, assignment.id)
    assert attendance.status == VolunteerAttendanceStatus.CHECKED_IN
    with pytest.raises(ConflictError):
        await service.check_in(volunteer, assignment.id)
    completed = await service.check_out(volunteer, assignment.id)
    assert completed.status == VolunteerAttendanceStatus.CHECKED_OUT
    with pytest.raises(ValidationError):
        await service.check_out(volunteer, assignment.id)
    with pytest.raises(ValidationError):
        await service.update_assignment(manager, assignment.id, VolunteerAssignmentStatus.APPROVED)


@pytest.mark.asyncio
async def test_self_request_requires_organizer_approval_and_rejection_is_terminal(db_session):
    event, _, volunteer, manager, _ = await _event_and_application(db_session)
    service = VolunteerShiftService(db_session)
    now = datetime.now(timezone.utc)
    shift = await service.create_shift(manager, event.id, ShiftCreateIn(title="Help desk", starts_at=now + timedelta(minutes=1), ends_at=now + timedelta(hours=1), required_count=2, status=VolunteerShiftStatus.OPEN))
    requested = await service.request_shift(volunteer, shift.id)
    assert requested.status == VolunteerAssignmentStatus.REQUESTED
    rejected = await service.update_assignment(manager, requested.id, VolunteerAssignmentStatus.REJECTED)
    assert rejected.status == VolunteerAssignmentStatus.REJECTED
    with pytest.raises(ValidationError):
        await service.update_assignment(manager, requested.id, VolunteerAssignmentStatus.APPROVED)


@pytest.mark.asyncio
async def test_shift_status_is_server_authoritative_and_notification_failure_isolated(db_session, monkeypatch):
    event, _, volunteer, manager, _ = await _event_and_application(db_session)
    service = VolunteerShiftService(db_session)
    now = datetime.now(timezone.utc)
    shift = await service.create_shift(manager, event.id, ShiftCreateIn(title="Ops", starts_at=now - timedelta(minutes=1), ends_at=now + timedelta(hours=1), required_count=1, status=VolunteerShiftStatus.OPEN))
    with pytest.raises(ValidationError):
        await service.update_shift(manager, shift.id, ShiftUpdateIn(status=VolunteerShiftStatus.COMPLETED))

    async def fail_notification(*args, **kwargs):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(NotificationService, "_queue_automated", fail_notification)
    assignment = await service.assign_shift(manager, shift.id, volunteer.id)
    assert assignment.status == VolunteerAssignmentStatus.APPROVED
    assert await service.repo.assignment(assignment.id) is not None
