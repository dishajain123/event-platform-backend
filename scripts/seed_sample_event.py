"""
Seed a generic phase-2 fixture event and its configuration.

This is intentionally branding-free: it creates a sample event with an
age limit, team-size rule, required document, and dynamic field schema
so local developers can exercise the configuration engine without using
real production data.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core import model_registry  # noqa: F401
from app.database import AsyncSessionLocal
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.models import Event
from app.modules.events.service import EventService
from app.modules.identity.models import User


SAMPLE_EVENT_NAME = "Sample Under-16 Category"
SAMPLE_EVENT_CATEGORY = "sample"
SAMPLE_CREATOR_MOBILE = "+919100000000"


async def get_or_create_user(db, mobile_number: str) -> User:
    result = await db.execute(select(User).where(User.mobile_number == mobile_number))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(mobile_number=mobile_number)
        db.add(user)
        await db.flush()
    return user


async def get_or_create_sample_event(db):
    result = await db.execute(
        select(Event)
        .where(Event.name == SAMPLE_EVENT_NAME, Event.category == SAMPLE_EVENT_CATEGORY)
        .order_by(Event.created_at.desc())
    )
    event = result.scalar_one_or_none()
    if event is not None:
        return event

    creator = await get_or_create_user(db, SAMPLE_CREATOR_MOBILE)
    service = EventService(db)
    start = datetime.now(timezone.utc) + timedelta(days=60)
    return await service.create_event(
        created_by=creator.id,
        name=SAMPLE_EVENT_NAME,
        description="Generic fixture event for config-engine smoke testing",
        category=SAMPLE_EVENT_CATEGORY,
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )


async def seed_sample_event(db) -> None:
    event = await get_or_create_sample_event(db)
    config = ConfigEngineService(db)

    await config.upsert_configuration(
        event.id,
        participation_types=["team"],
        fee_amount=1000.0,
        currency="INR",
        capacity=100,
        approval_required=False,
        rules={
            "min_age": None,
            "max_age": 15,
            "team_size": {"min": 5, "max": 11},
            "required_documents": ["aadhaar"],
        },
        discount_rules=None,
    )

    await config.upsert_field_schema(
        event.id,
        "team",
        [
            {
                "key": "tshirt_size",
                "label": "T-Shirt Size",
                "type": "select",
                "required": True,
                "options": ["S", "M", "L", "XL"],
            },
            {
                "key": "emergency_contact",
                "label": "Emergency Contact",
                "type": "text",
                "required": True,
                "options": None,
            },
        ],
    )

    await db.commit()
    print(f"Sample event ready: event_id={event.id}")


async def main() -> None:
    async with AsyncSessionLocal() as db:
        await seed_sample_event(db)


if __name__ == "__main__":
    asyncio.run(main())
