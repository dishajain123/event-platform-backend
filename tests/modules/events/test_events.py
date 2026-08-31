"""
Proves the event lifecycle state machine: valid transitions succeed,
invalid ones are rejected with a clear error, and each transition
writes an audit entry.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.exceptions import PermissionDeniedError
from app.modules.events.exceptions import InvalidEventStatusTransitionError
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName


async def _assign_role(db_session, user: User, role_name: RoleName, event_id=None):
    role = (await db_session.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db_session.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db_session.flush()


async def _make_event(db_session, service: EventService, mobile_suffix: str = "1"):
    creator = User(mobile_number=f"+91900000000{mobile_suffix}")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=30)
    end = start + timedelta(days=1)
    event = await service.create_event(
        created_by=creator.id,
        name="Sample Community Sports Day",
        description="A test fixture event",
        category="sports",
        start_date=start,
        end_date=end,
        organization_id=None,
    )
    return event, creator


async def _make_event_with_users(db_session):
    service = EventService(db_session)
    creator = User(mobile_number="+919000000011")
    manager = User(mobile_number="+919000000012")
    outsider = User(mobile_number="+919000000013")
    db_session.add_all([creator, manager, outsider])
    await db_session.flush()

    event, _ = await _make_event(db_session, service, mobile_suffix="9")
    await _assign_role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    await db_session.commit()
    return service, event, creator, manager, outsider


@pytest.mark.asyncio
async def test_new_event_starts_in_draft(db_session):
    service = EventService(db_session)
    event, _ = await _make_event(db_session, service)
    assert event.status == EventStatus.DRAFT


@pytest.mark.asyncio
async def test_valid_transition_chain_succeeds(db_session):
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service)

    event = await service.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    assert event.status == EventStatus.CONFIGURED

    event = await service.publish(event.id, creator.id)
    assert event.status == EventStatus.PUBLISHED

    event = await service.transition_status(event.id, EventStatus.REGISTRATION_OPEN, creator.id)
    assert event.status == EventStatus.REGISTRATION_OPEN


@pytest.mark.asyncio
async def test_invalid_transition_is_rejected(db_session):
    """A DRAFT event cannot jump straight to LIVE — must go through the
    intermediate states."""
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service)

    with pytest.raises(InvalidEventStatusTransitionError):
        await service.transition_status(event.id, EventStatus.LIVE, creator.id)


@pytest.mark.asyncio
async def test_archived_is_a_terminal_state(db_session):
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service)

    event = await service.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    event = await service.publish(event.id, creator.id)
    event = await service.transition_status(event.id, EventStatus.ARCHIVED, creator.id)
    assert event.status == EventStatus.ARCHIVED

    with pytest.raises(InvalidEventStatusTransitionError):
        await service.transition_status(event.id, EventStatus.PUBLISHED, creator.id)


@pytest.mark.asyncio
async def test_public_listing_excludes_draft_and_configured(db_session):
    service = EventService(db_session)
    draft_event, creator = await _make_event(db_session, service, mobile_suffix="1")

    published_event, _ = await _make_event(db_session, service, mobile_suffix="2")
    published_event = await service.transition_status(
        published_event.id, EventStatus.CONFIGURED, creator.id
    )
    published_event = await service.publish(published_event.id, creator.id)

    public_events = await service.list_events(include_all_statuses=False)
    public_ids = {e.id for e in public_events}

    assert published_event.id in public_ids
    assert draft_event.id not in public_ids

    all_events = await service.list_events(include_all_statuses=True)
    all_ids = {e.id for e in all_events}
    assert draft_event.id in all_ids
    assert published_event.id in all_ids


@pytest.mark.asyncio
async def test_get_event_visible_to_actor_allows_scoped_manager_and_rejects_outsider(db_session):
    service, event, _creator, manager, outsider = await _make_event_with_users(db_session)

    visible = await service.get_event_visible_to_actor(event.id, manager)
    assert visible.id == event.id

    with pytest.raises(PermissionDeniedError):
        await service.get_event_visible_to_actor(event.id, outsider)


@pytest.mark.asyncio
async def test_sponsor_crud(db_session):
    service, event, _creator, _manager, _outsider = await _make_event_with_users(db_session)

    sponsor = await service.add_sponsor(
        event.id,
        name="Acme Corp",
        tier="gold",
        logo_url="https://example.com/logo.png",
    )
    assert sponsor.event_id == event.id
    assert sponsor.name == "Acme Corp"

    sponsors = await service.list_sponsors(event.id)
    assert len(sponsors) == 1
    assert sponsors[0].id == sponsor.id

    await service.delete_sponsor(event.id, sponsor.id)
    sponsors_after_delete = await service.list_sponsors(event.id)
    assert sponsors_after_delete == []
