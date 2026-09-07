"""
Phase 3 registration coverage.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.events.models import EventStatus
from app.modules.notifications.models import Notification
from app.modules.guardians.exceptions import GuardianAuthorizationError
from app.modules.guardians.service import GuardianService
from app.modules.identity.models import User
from app.modules.registrations.router import list_registrations
from app.modules.rbac.models import RoleAssignment, RoleName
from app.modules.registrations.exceptions import (
    DuplicateRegistrationError,
    InvalidRegistrationStateError,
    RegistrationCapacityExceededError,
    RegistrationScopeError,
)
from app.modules.registrations.service import RegistrationService


async def _make_event(
    db_session,
    *,
    approval_required: bool = False,
    creator_mobile: str = "+919100000001",
    capacity: int | None = 10,
    registration_end_at: datetime | None = None,
    cancellation_deadline_at: datetime | None = None,
):
    creator = User(mobile_number=creator_mobile)
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=30)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 3 Registration Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=capacity,
        approval_required=approval_required,
        registration_end_at=registration_end_at,
        details=(
            {"cancellation_deadline_at": cancellation_deadline_at.isoformat()}
            if cancellation_deadline_at is not None
            else {}
        ),
        rules={},
        discount_rules=None,
    )
    return event, creator


@pytest.mark.asyncio
async def test_capacity_closes_event_and_blocks_next_registration(db_session):
    event, first_actor = await _make_event(db_session, capacity=1)
    second_actor = User(mobile_number="+919100000099")
    db_session.add(second_actor)
    await db_session.flush()
    service = RegistrationService(db_session)

    await service.create_registration(
        event_id=event.id,
        actor=first_actor,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    refreshed = await EventService(db_session).get_event_or_raise(event.id)
    assert refreshed.status == EventStatus.REGISTRATION_CLOSED
    with pytest.raises((RegistrationCapacityExceededError, InvalidRegistrationStateError)):
        await service.create_registration(
            event_id=event.id,
            actor=second_actor,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        )


@pytest.mark.asyncio
async def test_expired_registration_deadline_closes_open_event(db_session):
    event, actor = await _make_event(
        db_session,
        registration_end_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    event.status = EventStatus.REGISTRATION_OPEN
    await db_session.commit()

    with pytest.raises(InvalidRegistrationStateError):
        await RegistrationService(db_session).create_registration(
            event_id=event.id,
            actor=actor,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        )

    refreshed = await EventService(db_session).get_event_or_raise(event.id)
    assert refreshed.status == EventStatus.REGISTRATION_CLOSED


@pytest.mark.asyncio
async def test_capacity_warning_is_queued_once_at_eighty_percent(db_session):
    event, first_actor = await _make_event(db_session, capacity=5)
    actors = [first_actor]
    for index in range(3):
        actor = User(mobile_number=f"+9191000010{index}")
        db_session.add(actor)
        actors.append(actor)
    await db_session.flush()

    service = RegistrationService(db_session)
    for actor in actors:
        await service.create_registration(
            event_id=event.id,
            actor=actor,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        )

    warnings = (
        await db_session.execute(
            select(Notification).where(Notification.event_id == event.id)
        )
    ).scalars().all()
    assert len(warnings) == 4
    assert all(notification.target_metadata["capacity_warning"] for notification in warnings)
    assert all(notification.body == "Limited seats available — Register now!" for notification in warnings)


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    from app.modules.rbac.models import Role

    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


@pytest.mark.asyncio
async def test_registration_duplicate_guard_and_auto_approval(db_session):
    event, actor = await _make_event(db_session)
    service = RegistrationService(db_session)

    reg = await service.create_registration(
        event_id=event.id,
        actor=actor,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    assert reg.status.value == "confirmed"  # ticket issued immediately for this free, no-approval event

    with pytest.raises(DuplicateRegistrationError):
        await service.create_registration(
            event_id=event.id,
            actor=actor,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        )


@pytest.mark.asyncio
async def test_guardian_authorization_blocks_non_guardian_registration(db_session):
    event, guardian = await _make_event(db_session)
    other_user = User(mobile_number="+919100000002")
    db_session.add(other_user)
    await db_session.flush()

    child = await GuardianService(db_session).create_child(
        guardian.id, "Kid Example", date(2012, 1, 1), "guardian"
    )

    service = RegistrationService(db_session)
    with pytest.raises(GuardianAuthorizationError):
        await service.create_registration(
            event_id=event.id,
            actor=other_user,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=child.id,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        )


@pytest.mark.asyncio
async def test_event_manager_can_approve_pending_registration(db_session):
    event, actor = await _make_event(db_session, approval_required=True)
    requester = User(mobile_number="+919100000003")
    approver = User(mobile_number="+919100000004")
    db_session.add_all([requester, approver])
    await db_session.flush()

    await _assign_role(db_session, approver, RoleName.EVENT_MANAGER, event.id)

    service = RegistrationService(db_session)
    reg = await service.create_registration(
        event_id=event.id,
        actor=requester,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    assert reg.status.value == "pending_verification"

    reg = await service.decide_registration(reg.id, approver, True)
    assert reg.status.value == "confirmed"  # free event -> ticket issued immediately on approval


@pytest.mark.asyncio
async def test_registration_list_route_requires_event_scope_for_non_global_users(db_session):
    event, _actor = await _make_event(db_session)
    manager = User(mobile_number="+919100000005")
    outsider = User(mobile_number="+919100000006")
    db_session.add_all([manager, outsider])
    await db_session.flush()
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event.id)

    service = RegistrationService(db_session)
    allowed = await list_registrations(
        event_id=event.id,
        current_user=manager,
        db=db_session,
        service=service,
    )
    assert allowed == []

    from app.exceptions import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await list_registrations(
            event_id=event.id,
            current_user=outsider,
            db=db_session,
            service=service,
        )


@pytest.mark.asyncio
async def test_owner_can_cancel_free_registration_and_release_capacity(db_session):
    event, actor = await _make_event(db_session, capacity=1)
    service = RegistrationService(db_session)
    registration = await service.create_registration(
        event_id=event.id,
        actor=actor,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    cancelled = await service.cancel_registration(registration.id, actor, "Plans changed")
    assert cancelled.status.value == "cancelled"
    assert cancelled.payment_status is None
    assert await service.registrations.count_active_for_event(event.id) == 0

    replacement = User(mobile_number="+919100009999")
    db_session.add(replacement)
    await db_session.flush()
    replacement_registration = await service.create_registration(
        event_id=event.id,
        actor=replacement,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    assert replacement_registration.status.value == "confirmed"


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_cancel_registration(db_session):
    event, owner = await _make_event(db_session)
    outsider = User(mobile_number="+919100009998")
    db_session.add(outsider)
    await db_session.flush()
    registration = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=owner,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    with pytest.raises(RegistrationScopeError):
        await RegistrationService(db_session).cancel_registration(registration.id, outsider)


@pytest.mark.asyncio
async def test_cancellation_deadline_is_enforced_server_side(db_session):
    event, actor = await _make_event(
        db_session,
        cancellation_deadline_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    registration = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=actor,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    with pytest.raises(InvalidRegistrationStateError, match="deadline"):
        await RegistrationService(db_session).cancel_registration(registration.id, actor)


@pytest.mark.asyncio
async def test_registration_list_scopes_managers_and_supports_operations_all_events(db_session):
    event_a, _ = await _make_event(db_session)
    event_b, _ = await _make_event(db_session, creator_mobile="+919100000012")
    event_c, _ = await _make_event(db_session, creator_mobile="+919100000013")
    manager = User(mobile_number="+919100000007")
    operations = User(mobile_number="+919100000008")
    participant = User(mobile_number="+919100000009")
    db_session.add_all([manager, operations, participant])
    await db_session.flush()
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event_b.id)
    await _assign_role(db_session, operations, RoleName.OPERATIONS_ADMIN)

    service = RegistrationService(db_session)
    registrations = []
    for event in (event_a, event_b, event_c):
        registrations.append(
            await service.create_registration(
                event_id=event.id,
                actor=participant,
                participation_type="individual",
                date_of_birth=date(2012, 1, 1),
                child_id=None,
                team_id=None,
                documents_provided=[],
                answers={},
                participants=[],
            )
        )

    assigned = await list_registrations(
        event_id=None,
        current_user=manager,
        db=db_session,
        service=service,
    )
    assert {registration.event_id for registration in assigned} == {event_a.id, event_b.id}

    from app.exceptions import PermissionDeniedError

    with pytest.raises(PermissionDeniedError):
        await list_registrations(
            event_id=event_c.id,
            current_user=manager,
            db=db_session,
            service=service,
        )

    all_for_operations = await list_registrations(
        event_id=None,
        current_user=operations,
        db=db_session,
        service=service,
    )
    assert {registration.id for registration in all_for_operations} == {
        registration.id for registration in registrations
    }

    only_event_c = await list_registrations(
        event_id=event_c.id,
        current_user=operations,
        db=db_session,
        service=service,
    )
    assert [registration.id for registration in only_event_c] == [registrations[2].id]


@pytest.mark.asyncio
async def test_registration_list_without_scope_remains_user_scoped_for_mobile_users(db_session):
    event, _ = await _make_event(db_session)
    owner = User(mobile_number="+919100000010")
    other_owner = User(mobile_number="+919100000011")
    db_session.add_all([owner, other_owner])
    await db_session.flush()
    service = RegistrationService(db_session)

    own = await service.create_registration(
        event_id=event.id,
        actor=owner,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )
    await service.create_registration(
        event_id=event.id,
        actor=other_owner,
        participation_type="individual",
        date_of_birth=date(2012, 1, 1),
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    visible = await list_registrations(
        event_id=None,
        current_user=owner,
        db=db_session,
        service=service,
    )
    assert [registration.id for registration in visible] == [own.id]


@pytest.mark.asyncio
async def test_scoped_registration_pagination_filters_in_sql(db_session):
    event, _ = await _make_event(db_session)
    manager = User(mobile_number="+919100000014")
    participants = [User(mobile_number=f"+91910000001{value}") for value in (5, 6, 7)]
    db_session.add(manager)
    db_session.add_all(participants)
    await db_session.flush()
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    service = RegistrationService(db_session)
    for participant, name in zip(participants, ("Alpha Runner", "Beta Runner", "Gamma Viewer")):
        await service.create_registration(
            event_id=event.id,
            actor=participant,
            participation_type="individual",
            date_of_birth=date(2012, 1, 1),
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[{"full_name": name}],
        )
    page = await list_registrations(
        event_id=event.id,
        page=1,
        page_size=1,
        search="Beta",
        current_user=manager,
        db=db_session,
        service=service,
    )
    assert page.total == 1
    assert page.page_size == 1
    assert page.items[0].participants[0].full_name == "Beta Runner"
