"""
Phase 6 communication coverage.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.notifications.models import NotificationChannel, NotificationDeliveryStatus
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
