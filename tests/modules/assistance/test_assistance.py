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
from app.modules.payments.models import DiscountType
from app.modules.rbac.models import RoleAssignment, RoleName, Role
from app.modules.staff.models import StaffAssignmentStatus
from app.modules.staff.service import StaffService
from app.modules.registrations.service import RegistrationService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session):
    creator = User(mobile_number="+919600000001")
    requester = User(mobile_number="+919600000002")
    reviewer = User(mobile_number="+919600000003")
    reviewer_admin = User(mobile_number="+919600000004")
    db_session.add_all([creator, requester, reviewer, reviewer_admin])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=22)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 8 Assistance Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=Decimal("1500.00"),
        currency="INR",
        capacity=30,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    await _assign_role(db_session, reviewer_admin, RoleName.OPERATIONS_ADMIN)
    await _assign_role(db_session, reviewer, RoleName.EVENT_MANAGER, event.id)

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

    staff_service = StaffService(db_session)
    await staff_service.create_assignment(
        event_id=event.id,
        actor=reviewer_admin,
        invitee_mobile=reviewer.mobile_number,
        role_label="reviewer",
        full_name=reviewer.name or "Reviewer",
    )
    assignment = (await staff_service.assignments.list_for_event(event.id))[0]
    assignment = await staff_service.accept_assignment(assignment.id, reviewer)
    assert assignment.status == StaffAssignmentStatus.ACTIVE

    return event, requester, reviewer, reviewer_admin, registration


@pytest.mark.asyncio
async def test_assistance_request_routes_to_reviewer_and_creates_discount_code(db_session):
    event, requester, reviewer, reviewer_admin, registration = await _make_event(db_session)
    service = AssistanceService(db_session)

    request = await service.create_request(
        event_id=event.id,
        actor=requester,
        registration_id=registration.id,
        reason="Fee waiver needed",
        requested_fee_waiver_amount=Decimal("250.00"),
    )
    assert request.status == AssistanceRequestStatus.ASSIGNED
    assert request.reviewer_user_id == reviewer.id

    decided = await service.decide_request(
        request.id,
        reviewer_admin,
        approve=True,
        decision_reason="Approved",
        requested_fee_waiver_amount=Decimal("250.00"),
    )
    assert decided.status == AssistanceRequestStatus.APPROVED
    assert decided.applied_discount_code is not None

    discount = await service.discount_codes.get_by_code(decided.applied_discount_code, event.id)
    assert discount is not None
    assert discount.discount_type == DiscountType.FIXED
