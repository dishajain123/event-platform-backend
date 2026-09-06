"""Feedback lifecycle and scope regression coverage."""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.core.permissions import user_scoped_event_ids
from app.exceptions import PermissionDeniedError
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.feedback.exceptions import FeedbackEventUnavailableError
from app.modules.feedback.models import FeedbackCategory
from app.modules.feedback.service import FeedbackService
from app.modules.feedback.schemas import FeedbackCreateIn
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.feedback.router import _scope_for_actor


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _event(db_session, name: str) -> object:
    creator = User(mobile_number=f"+9198{abs(hash(name)) % 100000000:08d}")
    db_session.add(creator)
    await db_session.flush()
    start = datetime.now(timezone.utc) - timedelta(days=1)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name=name,
        description="feedback fixture",
        category="fixture",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    event.status = EventStatus.LIVE
    await db_session.commit()
    return event


@pytest.mark.asyncio
async def test_feedback_upserts_by_user_event_category_and_self_scope(db_session):
    event = await _event(db_session, "Feedback Event")
    user = User(mobile_number="+919700000001", name="Participant")
    other = User(mobile_number="+919700000002", name="Other")
    db_session.add_all([user, other])
    await db_session.commit()
    service = FeedbackService(db_session)

    first = await service.submit(user, event.id, FeedbackCategory.EVENT_EXPERIENCE, 3, "Good")
    second = await service.submit(user, event.id, FeedbackCategory.EVENT_EXPERIENCE, 5, "Excellent")

    assert first.id == second.id
    mine = await service.list_mine(user, event.id)
    assert len(mine) == 1
    assert mine[0].rating == 5
    with pytest.raises(PermissionDeniedError):
        await service.get_for_actor(first.id, other, can_view_event=False)


@pytest.mark.asyncio
async def test_feedback_rejects_unavailable_event_and_invalid_event(db_session):
    event = await _event(db_session, "Unavailable Feedback Event")
    user = User(mobile_number="+919700000003")
    db_session.add(user)
    await db_session.commit()
    service = FeedbackService(db_session)

    event.status = EventStatus.REGISTRATION_OPEN
    await db_session.commit()
    with pytest.raises(FeedbackEventUnavailableError):
        await service.submit(user, event.id, FeedbackCategory.OTHER, 4, None)

    with pytest.raises(Exception):
        await service.submit(user, __import__("uuid").uuid4(), FeedbackCategory.OTHER, 4, None)


def test_feedback_schema_validates_rating_and_category():
    with pytest.raises(ValidationError):
        FeedbackCreateIn(event_id="00000000-0000-0000-0000-000000000001", category="other", rating=6)
    with pytest.raises(ValidationError):
        FeedbackCreateIn(
            event_id="00000000-0000-0000-0000-000000000001",
            category="not_a_feedback_category",
            rating=4,
        )


@pytest.mark.asyncio
async def test_event_manager_scope_is_server_side_and_operations_are_global(db_session):
    event_a = await _event(db_session, "Scoped Event A")
    event_b = await _event(db_session, "Scoped Event B")
    manager = User(mobile_number="+919700000004")
    operations = User(mobile_number="+919700000005")
    db_session.add_all([manager, operations])
    await db_session.commit()
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event_a.id)
    await _assign_role(db_session, operations, RoleName.OPERATIONS_ADMIN)

    ids, selected = await _scope_for_actor(manager, db_session, None)
    assert ids == {event_a.id}
    assert selected is None
    with pytest.raises(PermissionDeniedError):
        await _scope_for_actor(manager, db_session, event_b.id)

    ids, selected = await _scope_for_actor(operations, db_session, None)
    assert ids is None
    assert selected is None
    assert await user_scoped_event_ids(db_session, manager.id, {RoleName.EVENT_MANAGER}) == {event_a.id}
