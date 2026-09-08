"""
Phase 3 guardian coverage.
"""
from datetime import date

import pytest

from app.modules.guardians.exceptions import DuplicateGuardianRelationshipError, GuardianAuthorizationError
from app.modules.guardians.service import GuardianService
from app.modules.identity.models import User


@pytest.mark.asyncio
async def test_guardian_can_create_and_list_children(db_session):
    guardian = User(mobile_number="+919200000001")
    db_session.add(guardian)
    await db_session.flush()

    service = GuardianService(db_session)
    child = await service.create_child(guardian.id, "Young Artist", date(2012, 5, 1), "guardian")

    children = await service.list_children(guardian.id)
    assert child.id in {item.id for item in children}


@pytest.mark.asyncio
async def test_guardian_authorization_is_event_date_agnostic_but_required(db_session):
    guardian = User(mobile_number="+919200000002")
    other = User(mobile_number="+919200000003")
    db_session.add_all([guardian, other])
    await db_session.flush()

    service = GuardianService(db_session)
    child = await service.create_child(guardian.id, "Young Performer", date(2011, 1, 1), "guardian")

    with pytest.raises(GuardianAuthorizationError):
        await service.ensure_guardian_can_register_for_child(other.id, child.id)


@pytest.mark.asyncio
async def test_creating_the_same_child_twice_is_rejected_as_duplicate(db_session):
    """
    Regression test for a bug found in audit: create_child() used to
    create the new ChildProfile row FIRST, then check whether the
    guardian already had a relationship to that same (just-created)
    child.id — which can never be true, since the id didn't exist a
    moment earlier. DuplicateGuardianRelationshipError could never
    actually fire, so nothing stopped a guardian from creating unlimited
    duplicate profiles for the same real child (e.g. a double-tap
    submit), fragmenting that child's history across separate profiles.
    """
    guardian = User(mobile_number="+919200000004")
    db_session.add(guardian)
    await db_session.flush()

    service = GuardianService(db_session)
    first = await service.create_child(guardian.id, "Repeat Child", date(2013, 3, 3), "guardian")

    with pytest.raises(DuplicateGuardianRelationshipError):
        await service.create_child(guardian.id, "Repeat Child", date(2013, 3, 3), "guardian")

    # A guardian legitimately having two DIFFERENT children must still work.
    second = await service.create_child(guardian.id, "Second Child", date(2015, 6, 6), "guardian")
    assert second.id != first.id

    children = await service.list_children(guardian.id)
    assert {child.id for child in children} == {first.id, second.id}