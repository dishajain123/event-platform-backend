"""
Phase 5 staff and operations coverage — including the RBAC-bridge fix:
accepting a staff invitation must actually grant real permissions, and
revoking/reassigning it must actually remove them.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.staff.exceptions import InvalidStaffRoleNameError
from app.modules.staff.models import StaffAssignmentStatus
from app.modules.staff.service import StaffService


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session):
    creator = User(mobile_number="+919400000001")
    manager_a = User(mobile_number="+919400000002", name="Manager A")
    manager_b = User(mobile_number="+919400000003", name="Manager B")
    staff_user = User(mobile_number="+919400000004", name="Staff User")
    db_session.add_all([creator, manager_a, manager_b, staff_user])
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=15)
    event_a = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 5 Event A",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    event_b = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 5 Event B",
        description="fixture",
        category="sample",
        start_date=start + timedelta(days=3),
        end_date=start + timedelta(days=4),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event_a.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=20,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event_b.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=20,
        approval_required=False,
        rules={},
        discount_rules=None,
    )

    await _assign_role(db_session, manager_a, RoleName.EVENT_MANAGER, event_a.id)
    await _assign_role(db_session, manager_b, RoleName.EVENT_MANAGER, event_b.id)

    return {
        "event_a": event_a,
        "event_b": event_b,
        "creator": creator,
        "manager_a": manager_a,
        "manager_b": manager_b,
        "staff_user": staff_user,
    }


@pytest.mark.asyncio
async def test_event_scoped_staff_management_and_history(db_session):
    context = await _make_event(db_session)
    service = StaffService(db_session)

    with pytest.raises(PermissionDeniedError):
        await service.create_assignment(
            event_id=context["event_a"].id,
            actor=context["manager_b"],
            invitee_mobile=context["staff_user"].mobile_number,
            role_name=RoleName.STAFF_MEMBER,
            role_label="marshal",
            full_name="Staff User",
        )

    assignment = await service.create_assignment(
        event_id=context["event_a"].id,
        actor=context["manager_a"],
        invitee_mobile=context["staff_user"].mobile_number,
        role_name=RoleName.STAFF_MEMBER,
        role_label="marshal",
        full_name="Staff User",
    )
    assert assignment.status == StaffAssignmentStatus.INVITED
    assert assignment.role_name == RoleName.STAFF_MEMBER

    reassigned = await service.reassign_assignment(
        assignment.id,
        context["manager_a"],
        invitee_mobile="+919400000005",
        role_name=RoleName.STAFF_LEAD,
        role_label="gate_lead",
        full_name="Gate Lead",
    )
    assert reassigned.status == StaffAssignmentStatus.INVITED
    assert reassigned.role_label == "gate_lead"
    assert reassigned.role_name == RoleName.STAFF_LEAD

    history = await service.list_history(
        event_id=context["event_a"].id,
        assignment_id=assignment.id,
        actor=context["manager_a"],
    )
    assert len(history) >= 2

    original = await service.assignments.get_by_id(assignment.id)
    assert original is not None
    assert original.status == StaffAssignmentStatus.REVOKED
    assert original.superseded_by_id == reassigned.id


@pytest.mark.asyncio
async def test_accepting_a_staff_invitation_grants_real_permissions(db_session):
    """The core RBAC-bridge fix: before acceptance the invitee has no
    scoped access at all; after acceptance, they do — scoped exactly to
    the event they were invited to, not any other event."""
    context = await _make_event(db_session)
    service = StaffService(db_session)

    assignment = await service.create_assignment(
        event_id=context["event_a"].id,
        actor=context["manager_a"],
        invitee_mobile=context["staff_user"].mobile_number,
        role_name=RoleName.STAFF_LEAD,
        role_label="Volunteer Head",
        full_name="Staff User",
    )

    has_access_before = await user_has_scoped_role(
        db_session, context["staff_user"].id, {RoleName.STAFF_LEAD}, context["event_a"].id
    )
    assert has_access_before is False

    accepted = await service.accept_assignment(assignment.id, context["staff_user"])
    assert accepted.status == StaffAssignmentStatus.ACTIVE
    assert accepted.user_id == context["staff_user"].id
    assert accepted.linked_role_assignment_id is not None

    has_access_after = await user_has_scoped_role(
        db_session, context["staff_user"].id, {RoleName.STAFF_LEAD}, context["event_a"].id
    )
    assert has_access_after is True

    # Scoped correctly — no bleed into event_b.
    has_access_other_event = await user_has_scoped_role(
        db_session, context["staff_user"].id, {RoleName.STAFF_LEAD}, context["event_b"].id
    )
    assert has_access_other_event is False


@pytest.mark.asyncio
async def test_revoking_a_staff_assignment_actually_removes_access(db_session):
    context = await _make_event(db_session)
    service = StaffService(db_session)

    assignment = await service.create_assignment(
        event_id=context["event_a"].id,
        actor=context["manager_a"],
        invitee_mobile=context["staff_user"].mobile_number,
        role_name=RoleName.STAFF_MEMBER,
        role_label="Volunteer",
        full_name="Staff User",
    )
    await service.accept_assignment(assignment.id, context["staff_user"])

    has_access_before_revoke = await user_has_scoped_role(
        db_session, context["staff_user"].id, {RoleName.STAFF_MEMBER}, context["event_a"].id
    )
    assert has_access_before_revoke is True

    await service.revoke_assignment(assignment.id, context["manager_a"], reason="No longer needed")

    has_access_after_revoke = await user_has_scoped_role(
        db_session, context["staff_user"].id, {RoleName.STAFF_MEMBER}, context["event_a"].id
    )
    assert has_access_after_revoke is False


@pytest.mark.asyncio
async def test_a_non_scoped_role_cannot_be_used_as_a_staff_role(db_session):
    """Only the four scoped roles (Event Manager, Event Coordinator, Staff
    Lead, Staff Member) are valid staff-invitation roles — a global role
    like Finance Admin must be rejected here."""
    context = await _make_event(db_session)
    service = StaffService(db_session)

    with pytest.raises(InvalidStaffRoleNameError):
        await service.create_assignment(
            event_id=context["event_a"].id,
            actor=context["manager_a"],
            invitee_mobile=context["staff_user"].mobile_number,
            role_name=RoleName.FINANCE_ADMIN,
            role_label="Should not work",
            full_name="Staff User",
        )   