"""
Proves the core permission engine: global roles work regardless of
event, scoped roles are correctly REJECTED for an event they weren't
assigned to, and Super Admin/Operations Admin can bypass scope checks
when explicitly allowed to.
"""
import uuid

import pytest
from sqlalchemy import select

from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.rbac.service import RBACService


async def _get_role(db, name: RoleName) -> Role:
    result = await db.execute(select(Role).where(Role.name == name))
    return result.scalar_one()


@pytest.mark.asyncio
async def test_global_role_grants_access_regardless_of_event(db_session):
    user = User(mobile_number="+911111111111")
    db_session.add(user)
    await db_session.flush()

    ops_admin_role = await _get_role(db_session, RoleName.OPERATIONS_ADMIN)
    db_session.add(RoleAssignment(user_id=user.id, role_id=ops_admin_role.id, event_id=None))
    await db_session.commit()

    has_access = await user_has_global_role(db_session, user.id, {RoleName.OPERATIONS_ADMIN})
    assert has_access is True


@pytest.mark.asyncio
async def test_scoped_role_is_rejected_for_a_different_event(db_session):
    """This is the core proof: an Event Manager assigned to event A must
    be rejected when the request is for event B."""
    user = User(mobile_number="+912222222222")
    db_session.add(user)
    await db_session.flush()

    event_manager_role = await _get_role(db_session, RoleName.EVENT_MANAGER)
    event_a = uuid.uuid4()
    event_b = uuid.uuid4()

    db_session.add(
        RoleAssignment(user_id=user.id, role_id=event_manager_role.id, event_id=event_a)
    )
    await db_session.commit()

    allowed_for_own_event = await user_has_scoped_role(
        db_session, user.id, {RoleName.EVENT_MANAGER}, event_id=event_a
    )
    allowed_for_other_event = await user_has_scoped_role(
        db_session, user.id, {RoleName.EVENT_MANAGER}, event_id=event_b
    )

    assert allowed_for_own_event is True
    assert allowed_for_other_event is False


@pytest.mark.asyncio
async def test_operations_admin_bypasses_scope_when_explicitly_allowed(db_session):
    user = User(mobile_number="+913333333333")
    db_session.add(user)
    await db_session.flush()

    ops_admin_role = await _get_role(db_session, RoleName.OPERATIONS_ADMIN)
    db_session.add(RoleAssignment(user_id=user.id, role_id=ops_admin_role.id, event_id=None))
    await db_session.commit()

    any_event = uuid.uuid4()
    has_access = await user_has_scoped_role(
        db_session,
        user.id,
        {RoleName.EVENT_MANAGER},
        event_id=any_event,
        allow_global_roles={RoleName.OPERATIONS_ADMIN},
    )
    assert has_access is True


@pytest.mark.asyncio
async def test_assigning_a_global_role_with_an_event_id_is_rejected(db_session):
    from app.modules.rbac.exceptions import ScopeNotAllowedError

    user = User(mobile_number="+914444444444")
    admin = User(mobile_number="+915555555555")
    db_session.add_all([user, admin])
    await db_session.flush()

    service = RBACService(db_session)
    with pytest.raises(ScopeNotAllowedError):
        await service.assign_role(
            target_user_id=user.id,
            role_name=RoleName.FINANCE_ADMIN,
            event_id=uuid.uuid4(),
            assigned_by=admin.id,
        )


@pytest.mark.asyncio
async def test_assigning_a_scoped_role_without_an_event_id_is_rejected(db_session):
    from app.modules.rbac.exceptions import ScopeRequiredError

    user = User(mobile_number="+916666666666")
    admin = User(mobile_number="+917777777777")
    db_session.add_all([user, admin])
    await db_session.flush()

    service = RBACService(db_session)
    with pytest.raises(ScopeRequiredError):
        await service.assign_role(
            target_user_id=user.id,
            role_name=RoleName.EVENT_MANAGER,
            event_id=None,
            assigned_by=admin.id,
        )