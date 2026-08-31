"""
Phase 3 registration coverage.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.guardians.exceptions import GuardianAuthorizationError
from app.modules.guardians.service import GuardianService
from app.modules.identity.models import User
from app.modules.registrations.router import list_registrations
from app.modules.rbac.models import RoleAssignment, RoleName
from app.modules.registrations.exceptions import DuplicateRegistrationError
from app.modules.registrations.service import RegistrationService


async def _make_event(db_session, *, approval_required: bool = False):
    creator = User(mobile_number="+919100000001")
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
        capacity=10,
        approval_required=approval_required,
        rules={},
        discount_rules=None,
    )
    return event, creator


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

    assert reg.status.value == "approved"

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
    assert reg.status.value == "approved"


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
