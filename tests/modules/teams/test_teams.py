"""
Phase 3 team flow coverage.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleAssignment, RoleName, Role
from app.modules.teams.models import TeamStatus
from app.modules.teams.service import TeamService


async def _make_event(db_session):
    creator = User(mobile_number="+919300000001")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=45)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 3 Team Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["team"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        approval_required=False,
        rules={"team_size": {"min": 2, "max": 3}},
        discount_rules=None,
    )
    return event


async def _assign_global_role(db_session, user: User, role_name: RoleName):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=None))
    await db_session.flush()


@pytest.mark.asyncio
async def test_team_invite_respond_submit_and_approve(db_session):
    event = await _make_event(db_session)
    captain = User(mobile_number="+919300000002")
    invitee = User(mobile_number="+919300000003")
    approver = User(mobile_number="+919300000004")
    db_session.add_all([captain, invitee, approver])
    await db_session.flush()

    await _assign_global_role(db_session, approver, RoleName.OPERATIONS_ADMIN)

    service = TeamService(db_session)
    team = await service.create_team(event.id, captain, "Team Alpha", date(2010, 1, 1))
    invitation = await service.invite_member(team.id, captain, invitee.mobile_number)
    await service.respond_to_invitation(team.id, invitation.id, invitee, True)

    team = await service.submit_team(team.id, captain)
    assert team.status == TeamStatus.SUBMITTED
    assert team.registration_id is not None  # the fix: submission creates a real Registration

    from app.modules.registrations.repository import RegistrationRepository
    from app.modules.registrations.models import RegistrationStatus

    registration = await RegistrationRepository(db_session).get_by_id(team.registration_id)
    assert registration is not None
    assert registration.team_id == team.id
    assert registration.participation_type == "team"
    # No fee configured and no approval required at submission time -> auto-approved immediately.
    assert registration.status == RegistrationStatus.APPROVED

    team = await service.approve_team(team.id, approver)
    assert team.status == TeamStatus.APPROVED


@pytest.mark.asyncio
async def test_team_registration_respects_approval_required_before_payment(db_session):
    """Proves the team->registration bridge correctly inherits the event's
    configured approval_required flag, exactly like individual registrations do."""
    creator = User(mobile_number="+919300000005")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=45)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 3 Team Event (approval required)",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["team"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        approval_required=True,
        rules={"team_size": {"min": 1, "max": 3}},
        discount_rules=None,
    )

    captain = User(mobile_number="+919300000006")
    approver = User(mobile_number="+919300000007")
    db_session.add_all([captain, approver])
    await db_session.flush()
    await _assign_global_role(db_session, approver, RoleName.OPERATIONS_ADMIN)

    service = TeamService(db_session)
    team = await service.create_team(event.id, captain, "Solo Entry Team", date(2010, 1, 1))
    team = await service.submit_team(team.id, captain)

    from app.modules.registrations.repository import RegistrationRepository
    from app.modules.registrations.models import RegistrationStatus

    registration = await RegistrationRepository(db_session).get_by_id(team.registration_id)
    assert registration.status == RegistrationStatus.PENDING_VERIFICATION

    # approve_team must forward the decision to the still-pending registration.
    team = await service.approve_team(team.id, approver)
    assert team.status == TeamStatus.APPROVED
    registration = await RegistrationRepository(db_session).get_by_id(team.registration_id)
    assert registration.status == RegistrationStatus.APPROVED