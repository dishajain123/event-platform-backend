"""
Phase 3 guardian coverage.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.modules.guardians.exceptions import GuardianAuthorizationError
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
