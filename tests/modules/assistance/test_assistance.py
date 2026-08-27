"""
Phase 8 assistance coverage.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.modules.assistance.models import AssistanceRequestStatus
from app.modules.assistance.service import AssistanceService
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.registrations.service import RegistrationService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


@pytest.mark.asyncio
async def test_reviewer_fallback_finds_event_manager_granted_directly_via_rbac(db_session):
    """
    The fix: an Event Manager assigned straight through the RBAC endpoint
    (POST /users/{id}/role-assignments, bypassing the Staff module
    entirely) must still be found as a fallback reviewer, even though no
    StaffAssignment row exists for them.
    """
    creator = User(mobile_number="+919600000010")
    requester = User(mobile_number="+919600000011")
    direct_manager = User(mobile_number="+919600000012")
    db_session.add_all([creator, requester, direct_manager])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=22)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Direct RBAC Manager Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=Decimal("500.00"),
        currency="INR",
        capacity=10,
        approval_required=False,
        rules={},
        discount_rules=None,
    )

    await _assign_role(db_session, direct_manager, RoleName.EVENT_MANAGER, event.id)

    registration = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=requester,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    service = AssistanceService(db_session)
    request = await service.create_request(
        event_id=event.id,
        actor=requester,
        registration_id=registration.id,
        reason="Need help with the fee",
        requested_fee_waiver_amount=Decimal("100.00"),
    )

    assert request.reviewer_user_id == direct_manager.id

    decided = await service.decide_request(
        request.id,
        direct_manager,
        approve=True,
        decision_reason="Approved directly",
    )
    assert decided.status == AssistanceRequestStatus.APPROVED
