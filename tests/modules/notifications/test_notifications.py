"""
Phase 6 communication coverage.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.notifications.models import (
    DeviceTokenPlatform,
    NotificationChannel,
    NotificationDeliveryStatus,
)
from app.modules.notifications.service import NotificationService
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.service import RegistrationService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session):
    creator = User(mobile_number="+919500000001")
    coordinator = User(mobile_number="+919500000002", name="Coordinator")
    recipient_a = User(mobile_number="+919500000003", name="Recipient A")
    recipient_b = User(mobile_number="+919500000004", name="Recipient B")
    db_session.add_all([creator, coordinator, recipient_a, recipient_b])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=10)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 6 Communication Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual", "viewer"],
        fee_amount=None,
        currency="INR",
        capacity=20,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    await _assign_role(db_session, coordinator, RoleName.EVENT_COORDINATOR, event.id)
    return event, coordinator, recipient_a, recipient_b


@pytest.mark.asyncio
async def test_targeted_send_fans_out_and_marks_delivery_status(db_session):
    event, coordinator, recipient_a, recipient_b = await _make_event(db_session)
    service = NotificationService(db_session)

    reg_a = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=recipient_a,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    reg_b = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=recipient_b,
        participation_type="viewer",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    reg_b.status = RegistrationStatus.CONFIRMED
    await db_session.commit()

    notifications = await service.send_notifications(
        actor=coordinator,
        title="Quick announcement",
        body="Venue change, please check in at Gate B.",
        channels=[NotificationChannel.SMS, NotificationChannel.PUSH],
        event_id=event.id,
        participation_types=["viewer"],
        registration_statuses=[RegistrationStatus.CONFIRMED],
        recipient_user_ids=[],
    )

    assert len(notifications) == 2
    assert {notification.recipient_user_id for notification in notifications} == {recipient_b.id}
    assert all(notification.delivery_status == NotificationDeliveryStatus.SENT for notification in notifications)
    assert all(notification.provider_message_id for notification in notifications)

    mine = await service.list_my_notifications(recipient_b)
    assert len(mine) == 2
    assert {notification.channel for notification in mine} == {
        NotificationChannel.SMS,
        NotificationChannel.PUSH,
    }

    templates = await service.list_templates()
    assert templates == []


@pytest.mark.asyncio
async def test_recipient_can_mark_their_own_notification_read(db_session):
    """
    Regression test for a real gap found while building the mobile app's
    notification inbox: mark_read() was already correctly implemented
    and permission-checked in the service layer, but was never actually
    exposed through any router endpoint — there was no way whatsoever to
    change a notification's read_at through the API.
    """
    from app.exceptions import PermissionDeniedError

    event, coordinator, recipient_a, recipient_b = await _make_event(db_session)
    service = NotificationService(db_session)

    await RegistrationService(db_session).create_registration(
        event_id=event.id, actor=recipient_a, participation_type="individual",
        date_of_birth=None, child_id=None, team_id=None,
        documents_provided=[], answers={}, participants=[],
    )
    sent = await service.send_notifications(
        actor=coordinator, title="Reminder", body="Doors open at 9am.",
        channels=[NotificationChannel.PUSH], event_id=event.id,
        participation_types=["individual"], registration_statuses=[], recipient_user_ids=[],
    )
    notification = sent[0]
    assert notification.read_at is None

    updated = await service.mark_read(notification.id, recipient_a)
    assert updated.read_at is not None

    # Someone else can't mark another person's notification read.
    with pytest.raises(PermissionDeniedError):
        await service.mark_read(notification.id, recipient_b)


@pytest.mark.asyncio
async def test_device_tokens_are_owned_and_support_multiple_devices(db_session):
    event, coordinator, recipient_a, _ = await _make_event(db_session)
    service = NotificationService(db_session)
    first = await service.register_device(recipient_a, "token-a", DeviceTokenPlatform.ANDROID)
    second = await service.register_device(recipient_a, "token-b", DeviceTokenPlatform.IOS)
    assert first.id != second.id

    updated = await service.register_device(recipient_a, "token-a", DeviceTokenPlatform.WEB)
    assert updated.id == first.id
    assert updated.platform == DeviceTokenPlatform.WEB

    from app.exceptions import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await service.remove_device(coordinator, first.id)


@pytest.mark.asyncio
async def test_preferences_and_automated_confirmation_are_idempotent(db_session):
    event, coordinator, recipient_a, _ = await _make_event(db_session)
    service = NotificationService(db_session)
    registration = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=recipient_a,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    registration.status = RegistrationStatus.CONFIRMED
    await db_session.commit()

    await service.update_preferences(recipient_a, {"registration_updates": False})
    assert not await service._preference_enabled(recipient_a.id, "registration_confirmation")
    assert await service.queue_automated_notifications() == []

    await service.update_preferences(recipient_a, {"registration_updates": True})
    first = await service.queue_automated_notifications()
    second = await service.queue_automated_notifications()
    assert len(first) == 1
    assert second == []


@pytest.mark.asyncio
async def test_manual_recipient_ids_are_limited_to_event_registrants(db_session):
    event, coordinator, recipient_a, recipient_b = await _make_event(db_session)
    service = NotificationService(db_session)
    await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=recipient_a,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    from app.modules.notifications.exceptions import InvalidNotificationTargetError

    with pytest.raises(InvalidNotificationTargetError):
        await service.send_notifications(
            actor=coordinator,
            title="Scoped",
            body="Only event participants",
            channels=[NotificationChannel.PUSH],
            event_id=event.id,
            participation_types=[],
            registration_statuses=[],
            recipient_user_ids=[recipient_b.id],
        )


@pytest.mark.asyncio
async def test_invalid_push_token_is_deactivated_and_delivery_is_failed(monkeypatch, db_session):
    event, coordinator, recipient_a, _ = await _make_event(db_session)
    service = NotificationService(db_session)
    await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=recipient_a,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    device = await service.register_device(recipient_a, "expired-token", DeviceTokenPlatform.ANDROID)

    from app.integrations.notification_providers import NotificationProviderError
    from app.modules.notifications.exceptions import NotificationDispatchError

    class InvalidProvider:
        async def send(self, **_kwargs):
            raise NotificationProviderError("expired", invalid_recipient=True)

    monkeypatch.setattr(
        "app.modules.notifications.service.get_push_provider", lambda _settings: InvalidProvider()
    )
    with pytest.raises(NotificationDispatchError):
        await service.send_notifications(
            actor=coordinator,
            title="Expired token",
            body="This should fail safely.",
            channels=[NotificationChannel.PUSH],
            event_id=event.id,
            participation_types=["individual"],
            registration_statuses=[],
            recipient_user_ids=[],
        )
    await db_session.refresh(device)
    assert device.is_active is False
    notifications = await service.list_my_notifications(recipient_a)
    assert notifications[0].delivery_status == NotificationDeliveryStatus.FAILED


def test_notification_read_endpoint_is_registered():
    from app.main import app

    routes = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("POST", "/api/v1/notifications/{notification_id}/read") in routes


@pytest.mark.asyncio
async def test_repository_create_survives_a_concurrent_dedupe_key_collision(db_session):
    """
    Regression test for a bug found in audit: NotificationRepository.create()
    only guarded against a duplicate dedupe_key with a check-then-insert —
    fine for the common single-caller case, but several callers (e.g.
    NotificationService.queue_automated_notifications) create many
    notifications in one Python loop sharing a single transaction before
    one final commit. A genuine race (two overlapping runs of the same
    scheduled task both passing the pre-check before either flushes) would
    raise an unhandled IntegrityError on the DB's unique constraint — and
    without a SAVEPOINT isolating just that one insert, recovering from it
    would roll back the whole transaction, silently losing every other
    notification already queued earlier in the same batch, not just the
    one genuine duplicate.

    Real concurrency can't be simulated against a single in-process SQLite
    connection, so the race is forced deterministically instead: an
    "existing" row is inserted directly (standing in for a concurrent
    caller's already-committed insert), then get_by_dedupe_key is
    monkeypatched to miss it exactly once (standing in for the exact race
    window: our pre-check ran before the concurrent insert became
    visible). create() must then recover from the flush's IntegrityError
    by returning the real existing row — and an unrelated notification
    added earlier in the same uncommitted transaction must still be
    present afterward, proving the SAVEPOINT confined the rollback to
    just the one colliding insert.
    """
    from app.modules.notifications.models import Notification
    from app.modules.notifications.repository import NotificationRepository

    creator = User(mobile_number="+919500000099")
    recipient = User(mobile_number="+919500000098")
    db_session.add_all([creator, recipient])
    await db_session.flush()
    start = datetime.now(timezone.utc) + timedelta(days=10)
    event = await EventService(db_session).create_event(
        created_by=creator.id, name="Notification Race Fixture", description=None,
        category="test", start_date=start, end_date=start + timedelta(days=1), organization_id=None,
    )

    repo = NotificationRepository(db_session)

    # Stands in for an earlier notification queued in the same batch
    # transaction, not yet committed — must survive the collision below.
    unrelated = await repo.create(
        event_id=event.id, recipient_user_id=recipient.id, channel=NotificationChannel.PUSH,
        title="Earlier queued notification", body="From earlier in the same batch run.",
        target_metadata={}, delivery_status=NotificationDeliveryStatus.QUEUED,
        notification_type="event_reminder", dedupe_key="race-test:unrelated-earlier",
    )

    # Stands in for a concurrent run's insert that's already real in the
    # database by the time our create() call below reaches its flush.
    existing_row = Notification(
        event_id=event.id, recipient_user_id=recipient.id, channel=NotificationChannel.PUSH,
        title="Inserted by a concurrent run", body="Won the race.", target_metadata={},
        delivery_status=NotificationDeliveryStatus.QUEUED, notification_type="event_reminder",
        dedupe_key="race-test:collision",
    )
    db_session.add(existing_row)
    await db_session.flush()

    # Force our pre-check to miss the row that's already there exactly
    # once — this is the actual race window: two callers' pre-checks both
    # ran before either's insert was visible to the other.
    real_lookup = repo.get_by_dedupe_key
    call_count = {"n": 0}

    async def _pre_check_misses_once(key):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return None
        return await real_lookup(key)

    repo.get_by_dedupe_key = _pre_check_misses_once

    recovered = await repo.create(
        event_id=event.id, recipient_user_id=recipient.id, channel=NotificationChannel.PUSH,
        title="Should be discarded in favor of the existing row", body="...",
        target_metadata={}, delivery_status=NotificationDeliveryStatus.QUEUED,
        notification_type="event_reminder", dedupe_key="race-test:collision",
    )

    # Recovered the real, already-existing row rather than raising or
    # creating a second row for the same dedupe_key.
    assert recovered.id == existing_row.id
    assert recovered.title == "Inserted by a concurrent run"

    # The notification queued earlier in the same uncommitted transaction
    # must still be present — proving the SAVEPOINT confined the rollback
    # to just the colliding insert, not the whole session.
    still_there = await db_session.get(Notification, unrelated.id)
    assert still_there is not None
    assert still_there.title == "Earlier queued notification"

    # And there is still exactly one row for the collided dedupe_key, not two.
    result = await db_session.execute(
        select(Notification).where(Notification.dedupe_key == "race-test:collision")
    )
    assert len(result.scalars().all()) == 1