from datetime import datetime, timedelta, timezone

import pytest

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.workers.registration_tasks import synchronize_registration_states_once


@pytest.mark.asyncio
async def test_registration_state_task_closes_expired_open_event(db_session):
    creator = User(mobile_number="+919888888801")
    db_session.add(creator)
    await db_session.flush()
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Task deadline fixture",
        description=None,
        category="sample",
        start_date=datetime.now(timezone.utc) + timedelta(days=1),
        end_date=datetime.now(timezone.utc) + timedelta(days=2),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        registration_end_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    event.status = EventStatus.REGISTRATION_OPEN
    await db_session.commit()

    assert await synchronize_registration_states_once(db_session) == 1
    refreshed = await EventService(db_session).get_event_or_raise(event.id)
    assert refreshed.status == EventStatus.REGISTRATION_CLOSED
