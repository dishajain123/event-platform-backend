import pytest
from sqlalchemy import select, func, text
from app.core.base_model import Base
from app.modules.identity.models import User
from app.modules.events.models import Event
from app.modules.notifications.models import Notification, NotificationChannel
from scripts.seed_platform import build_dataset
from scripts.seed.ownership import reset_owned, seed_id
from scripts.seed.go360_data import EVENTS

async def counts(db):
    return {t.name: await db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.tables.values()}

@pytest.mark.asyncio
async def test_seed_add_reset_idempotence_and_protected_dependencies(db_session):
    db = db_session
    await db.execute(text('PRAGMA foreign_keys=ON'))
    await build_dataset(db, 'small', refresh=True)
    await db.commit()
    first = await counts(db)
    assert first['events'] == 16
    assert first['registrations'] == 99
    await build_dataset(db, 'small')
    await db.commit()
    assert await counts(db) == first
    outsider = User(name='Existing customer', email='real@example.test')
    db.add(outsider)
    await db.flush()
    outsider_id = outsider.id
    event_id = seed_id('events', EVENTS[0][0])
    notice = Notification(event_id=event_id, recipient_user_id=outsider.id,
        channel=NotificationChannel.PUSH, title='Real record', body='Must survive reset')
    db.add(notice)
    await db.commit()
    notice_id = notice.id
    preserved = await reset_owned(db)
    assert preserved['events'] >= 1
    await build_dataset(db, 'small', refresh=True)
    await db.commit()
    assert await db.get(User, outsider_id) is not None
    assert (await db.get(Notification, notice_id)).body == 'Must survive reset'
    assert await db.scalar(select(func.count()).select_from(Event)) == 16

@pytest.mark.asyncio
async def test_reset_recreates_same_counts_without_external_records(db_session):
    db = db_session
    await db.execute(text('PRAGMA foreign_keys=ON'))
    await build_dataset(db, 'medium', refresh=True)
    await db.commit()
    before = await counts(db)
    await reset_owned(db)
    await build_dataset(db, 'medium', refresh=True)
    await db.commit()
    assert await counts(db) == before

@pytest.mark.asyncio
async def test_add_restores_missing_fixture_and_preserves_edits(db_session):
    from scripts.seed.ownership import snapshot_unowned, assert_preserved
    db = db_session
    await build_dataset(db, 'small')
    await db.commit()
    identity = seed_id('notifications', 'cricket/0')
    missing = await db.get(Notification, identity)
    await db.delete(missing)
    existing = await db.get(User, seed_id('users', '6'))
    existing.name = 'User-edited fixture name'
    outsider = User(name='Unrelated account', email='unrelated@example.test')
    db.add(outsider)
    await db.commit()
    baseline = await snapshot_unowned(db)
    await build_dataset(db, 'small')
    await assert_preserved(db, baseline)
    await db.commit()
    assert (await db.get(User, seed_id('users', '6'))).name == 'User-edited fixture name'
    assert await db.get(Notification, identity) is not None

@pytest.mark.asyncio
async def test_seed_is_queryable_by_both_clients(db_session):
    from app.modules.events.service import EventService
    from app.modules.event_categories.service import EventCategoryService
    db = db_session
    await build_dataset(db, 'small')
    await db.commit()
    categories = await EventCategoryService(db).list_main_categories()
    service = EventService(db)
    for _, main, topic, title, *_ in EVENTS:
        root = next(row for row in categories if row.name == main)
        topics = await EventCategoryService(db).list_sub_categories(root.id)
        sub = next(row for row in topics if row.name == topic)
        mobile = await service.list_events(include_all_statuses=False, main_category_id=root.id, sub_category_id=sub.id)
        assert title in {row.name for row in mobile}
        console, _ = await service.page_events(include_all_statuses=True, main_category_id=root.id, sub_category_id=sub.id, page=1, page_size=100)
        assert {row.id for row in mobile} == {row['id'] if isinstance(row, dict) else row.id for row in console}
