"""
Proves the audit log is actually readable now — previously it could
only ever be written to (core/audit.py), never queried, because
repository.py/service.py/router.py were all empty and the router
wasn't wired into main.py.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.audit_log.exceptions import InvalidAuditLogFilterError
from app.modules.audit_log.service import AuditLogService
from app.modules.events.service import EventService
from app.modules.identity.models import User


@pytest.mark.asyncio
async def test_event_creation_writes_a_queryable_audit_entry(db_session):
    creator = User(mobile_number="+919800000001")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=30)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Audit Log Fixture Event",
        description=None,
        category=None,
        start_date=start,
        end_date=start + timedelta(hours=2),
        organization_id=None,
    )

    service = AuditLogService(db_session)
    page = await service.query(entity_type="event", entity_id=event.id)

    assert page.total >= 1
    matching = [item for item in page.items if item.action == "created"]
    assert len(matching) == 1
    assert matching[0].actor_user_id == creator.id
    assert matching[0].after_value["name"] == "Audit Log Fixture Event"


@pytest.mark.asyncio
async def test_entity_history_is_returned_in_chronological_order(db_session):
    from app.modules.events.models import EventStatus

    creator = User(mobile_number="+919800000002")
    db_session.add(creator)
    await db_session.flush()

    events_service = EventService(db_session)
    start = datetime.now(timezone.utc) + timedelta(days=30)
    event = await events_service.create_event(
        created_by=creator.id,
        name="Audit History Fixture Event",
        description=None,
        category=None,
        start_date=start,
        end_date=start + timedelta(hours=2),
        organization_id=None,
    )
    await events_service.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    await events_service.publish(event.id, creator.id)

    service = AuditLogService(db_session)
    history = await service.get_history_for_entity("event", event.id)

    assert len(history) >= 3
    actions_in_order = [entry.action for entry in history]
    assert actions_in_order.index("created") < actions_in_order.index("status_changed")


@pytest.mark.asyncio
async def test_invalid_filters_are_rejected(db_session):
    service = AuditLogService(db_session)

    with pytest.raises(InvalidAuditLogFilterError):
        await service.query(limit=0)

    with pytest.raises(InvalidAuditLogFilterError):
        await service.query(limit=500)

    with pytest.raises(InvalidAuditLogFilterError):
        await service.query(offset=-1)

    now = datetime.now(timezone.utc)
    with pytest.raises(InvalidAuditLogFilterError):
        await service.query(date_from=now, date_to=now - timedelta(days=1))


@pytest.mark.asyncio
async def test_pagination_limit_and_offset_are_respected(db_session):
    creator = User(mobile_number="+919800000003")
    db_session.add(creator)
    await db_session.flush()

    events_service = EventService(db_session)
    start = datetime.now(timezone.utc) + timedelta(days=30)
    for i in range(3):
        await events_service.create_event(
            created_by=creator.id,
            name=f"Pagination Fixture Event {i}",
            description=None,
            category=None,
            start_date=start,
            end_date=start + timedelta(hours=2),
            organization_id=None,
        )

    service = AuditLogService(db_session)
    page = await service.query(entity_type="event", action="created", limit=2, offset=0)
    assert len(page.items) == 2
    assert page.limit == 2
    assert page.offset == 0
    assert page.total >= 3