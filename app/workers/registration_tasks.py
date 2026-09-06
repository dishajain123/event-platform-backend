"""Periodic synchronization for registration availability."""

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.background_jobs import celery_app
from app.core.concurrency import acquire_event_capacity_lock
from app.database import AsyncSessionLocal
from app.modules.config_engine.registration_state import (
    RegistrationAvailability,
    calculate_registration_availability,
    parse_registration_end_at,
)
from app.modules.events.models import Event, EventStatus
from app.modules.registrations.repository import RegistrationRepository


async def synchronize_registration_states_once(db: AsyncSession) -> int:
    result = await db.execute(
        select(Event)
        .options(selectinload(Event.configuration))
        .where(Event.status == EventStatus.REGISTRATION_OPEN)
        .execution_options(populate_existing=True)
    )
    events = list(result.scalars().all())
    registrations = RegistrationRepository(db)
    closed_count = 0

    for event in events:
        config = event.configuration
        if config is None:
            continue
        await acquire_event_capacity_lock(db, event.id)
        registered_count = await registrations.count_active_for_event(event.id)
        availability = calculate_registration_availability(
            event_status=event.status,
            capacity=config.capacity,
            registered_count=registered_count,
            registration_end_at=parse_registration_end_at(config.details),
        )
        if availability in {
            RegistrationAvailability.CLOSED,
            RegistrationAvailability.FULL,
        }:
            event.status = EventStatus.REGISTRATION_CLOSED
            closed_count += 1

    if closed_count:
        await db.commit()
    return closed_count


@celery_app.task(name="registrations.synchronize_registration_states")
def synchronize_registration_states() -> int:
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            return await synchronize_registration_states_once(db)

    return asyncio.run(_run())
