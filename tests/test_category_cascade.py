from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.event_categories.models import MainCategory, SubCategory
from app.modules.event_categories.service import EventCategoryService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.models import Event, EventStatus
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.registrations.models import Registration
from app.modules.registrations.service import RegistrationService


@pytest.mark.asyncio
@pytest.mark.parametrize("delete_main", [True, False])
async def test_delete_category_cascades_and_preserves_history(db_session, delete_main):
    db = db_session
    user = User(mobile_number="+919876540001")
    main = MainCategory(name="Parent")
    other = MainCategory(name="Unrelated")
    db.add_all([user, main, other])
    await db.flush()
    sub = SubCategory(name="Child", main_category_id=main.id)
    sibling = SubCategory(name="Sibling", main_category_id=main.id)
    db.add_all([sub, sibling])
    await db.flush()
    def event(name, parent_id, sub_id):
        return Event(name=name, main_category_id=parent_id, sub_category_id=sub_id,
                     start_date=datetime.now(timezone.utc),
                     end_date=datetime.now(timezone.utc) + timedelta(days=1),
                     status=EventStatus.REGISTRATION_OPEN)
    affected = event("Child event", main.id, sub.id)
    sibling_event = event("Sibling event", main.id, sibling.id)
    unrelated = event("Other event", other.id, None)
    direct = event("Direct parent event", main.id, None)
    db.add_all([affected, sibling_event, unrelated, direct])
    await db.flush()
    registration = Registration(event_id=affected.id, user_id=user.id, participation_type="individual")
    db.add(registration)
    await db.commit()
    service = EventCategoryService(db)
    if delete_main:
        await service.delete_main_category(main.id, user.id)
    else:
        await service.delete_sub_category(sub.id, user.id)

    events = EventRepository(db)
    assert await events.get_by_id(affected.id) is None
    assert await db.get(Event, affected.id) is affected
    await db.refresh(affected)
    assert affected.deleted_at is not None
    assert affected.status == EventStatus.ARCHIVED
    assert await db.get(Registration, registration.id) is registration
    assert (await events.get_by_id(sibling_event.id) is None) == delete_main
    assert (await events.get_by_id(direct.id) is None) == delete_main
    assert await events.get_by_id(unrelated.id) is not None
    assert affected.id not in {item.id for item in await events.list_public()}
    assert affected.id not in {item.id for item in await events.list_all()}
    items, total = await events.page_all(include_all_statuses=True)
    assert total == len(items) == (1 if delete_main else 3)
    categories = await service.list_main_categories(include_inactive=True)
    assert all(child.id != sub.id for parent in categories for child in parent.sub_categories)
    assert (main.id not in {item.id for item in categories}) == delete_main
    with pytest.raises(EventNotFoundError):
        await RegistrationService(db)._get_event_or_raise(affected.id)
    if delete_main:
        recreated = await service.create_main_category(user.id, name="Parent")
        assert recreated.id != main.id
    else:
        recreated = await service.create_sub_category(user.id, name="Child", main_category_id=main.id)
        assert recreated.id != sub.id


@pytest.mark.asyncio
async def test_public_category_read_does_not_delete_inactive_children(db_session):
    main = MainCategory(name="Parent")
    db_session.add(main)
    await db_session.flush()
    child = SubCategory(name="Hidden", main_category_id=main.id, is_active=False)
    db_session.add(child)
    await db_session.commit()
    service = EventCategoryService(db_session)
    assert (await service.list_main_categories())[0].sub_categories == []
    await db_session.commit()
    assert (await db_session.execute(select(SubCategory).where(SubCategory.id == child.id))).scalar_one() is child
    assert len((await service.list_main_categories(include_inactive=True))[0].sub_categories) == 1


@pytest.mark.asyncio
async def test_home_taxonomy_is_ordered_and_reflects_console_edits(db_session):
    db = db_session
    user = User(mobile_number="+919876540002")
    main = MainCategory(name="Home", description="Fallback")
    db.add_all([user, main])
    await db.flush()
    db.add_all([SubCategory(name=name, main_category_id=main.id)
                for name in ["Youth", "Business", "Sports", "Culture"]])
    await db.commit()
    service = EventCategoryService(db)
    taxonomy = await service.list_main_categories()
    assert [s.name for s in taxonomy[0].sub_categories] == ["Business", "Culture", "Sports", "Youth"]
    sports = next(s for s in taxonomy[0].sub_categories if s.name == "Sports")
    await service.update_sub_category(sports.id, user.id, name="Arts")
    taxonomy = await service.list_main_categories()
    assert [s.name for s in taxonomy[0].sub_categories] == ["Arts", "Business", "Culture", "Youth"]
    await service.update_sub_category(sports.id, user.id, is_active=False)
    taxonomy = await service.list_main_categories()
    assert [s.name for s in taxonomy[0].sub_categories] == ["Business", "Culture", "Youth"]
    await service.update_main_category(main.id, user.id, description="Updated fallback")
    assert (await service.list_main_categories())[0].description == "Updated fallback"
    await service.update_main_category(main.id, user.id, is_active=False)
    assert await service.list_main_categories() == []
