from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.exceptions import PermissionDeniedError
from app.modules.config_engine.models import EventConfiguration
from app.modules.events.models import Event, EventStatus
from app.modules.identity.models import User
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.notifications.models import Notification
from app.modules.waitlists.exceptions import WaitlistConflictError, WaitlistValidationError
from app.modules.waitlists.models import WaitlistEntry, WaitlistStatus
from app.modules.waitlists.service import WaitlistService
from app.modules.registrations.service import RegistrationService


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _full_event(db):
    owner = User(mobile_number="+919910000001")
    first = User(mobile_number="+919910000002")
    second = User(mobile_number="+919910000003")
    manager = User(mobile_number="+919910000004")
    outsider = User(mobile_number="+919910000005")
    db.add_all([owner, first, second, manager, outsider])
    await db.flush()
    start = datetime.now(timezone.utc) + timedelta(days=5)
    event = Event(name="Waitlist Event", description=None, category="test", start_date=start, end_date=start + timedelta(days=1), status=EventStatus.REGISTRATION_OPEN, created_by=owner.id)
    db.add(event)
    await db.flush()
    db.add(EventConfiguration(event_id=event.id, participation_types=["individual"], capacity=1, details={"registration_end_at": (start + timedelta(days=2)).isoformat()}))
    db.add(Registration(event_id=event.id, user_id=first.id, participation_type="individual", status=RegistrationStatus.CONFIRMED))
    await db.flush()
    await _role(db, manager, RoleName.EVENT_MANAGER, event.id)
    return event, first, second, manager, outsider


@pytest.mark.asyncio
async def test_waitlist_fifo_duplicate_join_leave_and_position(db_session):
    event, _first, second, _manager, _outsider = await _full_event(db_session)
    third = User(mobile_number="+919910000006")
    db_session.add(third)
    await db_session.flush()
    service = WaitlistService(db_session)
    first_entry = await service.join(second, event.id, "individual")
    second_entry = await service.join(third, event.id, "individual")
    assert first_entry.position == 1
    assert second_entry.position == 2
    with pytest.raises(WaitlistConflictError):
        await service.join(second, event.id, "individual")
    left = await service.leave(second, first_entry.id)
    assert left.status == WaitlistStatus.LEFT
    remaining = await service.page_manageable(_manager, event_id=event.id, status=WaitlistStatus.WAITING, page=1, page_size=10)
    assert remaining[1] == 1 and remaining[0][0].id == second_entry.id


@pytest.mark.asyncio
async def test_waitlist_promotion_is_fifo_and_does_not_create_registration(db_session):
    event, _first, second, _manager, _outsider = await _full_event(db_session)
    third = User(mobile_number="+919910000007")
    db_session.add(third)
    await db_session.flush()
    service = WaitlistService(db_session)
    first_entry = await service.join(second, event.id, "individual")
    await service.join(third, event.id, "individual")
    # Release the only seat, then promote exactly the first FIFO entry.
    active = (await db_session.execute(select(Registration).where(Registration.event_id == event.id, Registration.status == RegistrationStatus.CONFIRMED))).scalar_one()
    active.status = RegistrationStatus.CANCELLED
    promoted = await service.promote_next(event.id, "individual")
    assert promoted is not None and promoted.id == first_entry.id
    assert promoted.status == WaitlistStatus.PROMOTED
    await service._notify(promoted, "promoted")
    notification_count = await db_session.scalar(select(func.count(Notification.id)).where(
        Notification.dedupe_key == f"waitlist:{promoted.id}:promoted"
    ))
    assert notification_count == 1
    assert await db_session.scalar(select(Registration).where(Registration.user_id == second.id, Registration.event_id == event.id)) is None


@pytest.mark.asyncio
async def test_waitlist_scope_and_capacity_rules(db_session):
    event, _first, second, manager, outsider = await _full_event(db_session)
    service = WaitlistService(db_session)
    with pytest.raises(PermissionDeniedError):
        await service.page_manageable(outsider, event_id=event.id)
    await service.join(second, event.id, "individual")
    event.status = EventStatus.REGISTRATION_OPEN
    active = (await db_session.execute(select(Registration).where(Registration.event_id == event.id, Registration.status == RegistrationStatus.CONFIRMED))).scalar_one()
    active.status = RegistrationStatus.CANCELLED
    promoted = await service.promote_next(event.id, "individual")
    assert promoted is not None
    # The same promotion is idempotent while the seat is still available only
    # because the first offer is no longer WAITING.
    assert await service.promote_next(event.id, "individual") is None


@pytest.mark.asyncio
async def test_waitlist_rejects_join_before_full(db_session):
    owner = User(mobile_number="+919910000010")
    db_session.add(owner)
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=5)
    event = Event(name="Open Event", description=None, category="test", start_date=start, end_date=start + timedelta(days=1), status=EventStatus.REGISTRATION_OPEN, created_by=owner.id)
    db_session.add(event)
    await db_session.flush()
    db_session.add(EventConfiguration(event_id=event.id, participation_types=["individual"], capacity=10, details={}))
    await db_session.commit()
    with pytest.raises(WaitlistValidationError):
        await WaitlistService(db_session).join(owner, event.id, "individual")


@pytest.mark.asyncio
async def test_free_cancellation_releases_capacity_and_promotes_waitlist(db_session):
    event, first, second, _manager, _outsider = await _full_event(db_session)
    service = WaitlistService(db_session)
    entry = await service.join(second, event.id, "individual")
    registration = (await db_session.execute(select(Registration).where(
        Registration.event_id == event.id,
        Registration.user_id == first.id,
    ))).scalar_one()

    cancelled = await RegistrationService(db_session).cancel_registration(registration.id, first)

    assert cancelled.status == RegistrationStatus.CANCELLED
    promoted = await db_session.get(WaitlistEntry, entry.id)
    assert promoted is not None and promoted.status == WaitlistStatus.PROMOTED


@pytest.mark.asyncio
async def test_deadline_closes_waiting_entries(db_session):
    event, _first, second, _manager, _outsider = await _full_event(db_session)
    config = (await db_session.execute(select(EventConfiguration).where(EventConfiguration.event_id == event.id))).scalar_one()
    entry = WaitlistEntry(
        event_id=event.id, user_id=second.id, participation_type="individual",
        status=WaitlistStatus.WAITING, joined_at=datetime.now(timezone.utc),
    )
    config.details = {"registration_end_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}
    db_session.add(entry)
    await db_session.flush()
    await WaitlistService(db_session).expire_and_promote()
    assert (await db_session.get(WaitlistEntry, entry.id)).status == WaitlistStatus.CLOSED
