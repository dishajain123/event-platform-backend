"""
Proves the event lifecycle state machine: valid transitions succeed,
invalid ones are rejected with a clear error, and each transition
writes an audit entry.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.exceptions import NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.exceptions import InvalidEventStatusTransitionError, ScheduleConflictError, VenueNotFoundError
from app.modules.events.models import EventStatus, ScheduleStatus
from app.modules.tickets.models import AccessPolicy, AccessZone
from app.modules.events.service import EventService
from app.modules.config_engine.service import ConfigEngineService
from app.modules.event_categories.service import EventCategoryService
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
async def test_event_persists_and_returns_selected_category_hierarchy(db_session):
    service = EventService(db_session)
    creator = User(mobile_number="+919000000099")
    db_session.add(creator)
    await db_session.flush()
    categories = EventCategoryService(db_session)
    main = await categories.create_main_category(creator.id, name="Arts", description=None, is_active=True)
    sub = await categories.create_sub_category(
        creator.id,
        main_category_id=main.id,
        name="Painting",
        description=None,
        is_active=True,
    )

    start = datetime.now(timezone.utc) + timedelta(days=5)
    event = await service.create_event(
        created_by=creator.id,
        name="Community Arts Event",
        description=None,
        category=None,
        main_category_id=main.id,
        sub_category_id=sub.id,
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )

    reloaded = await service.get_event_or_raise(event.id)
    assert reloaded.main_category_id == main.id
    assert reloaded.sub_category_id == sub.id
    assert reloaded.main_category.name == "Arts"
    assert reloaded.sub_category.name == "Painting"
    assert reloaded.category == "Painting"


@pytest.mark.asyncio
async def test_event_response_exposes_live_capacity_contract(db_session):
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service, mobile_suffix="8")
    deadline = datetime.now(timezone.utc) + timedelta(days=2)
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        registration_end_at=deadline,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    event = await service.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    event = await service.publish(event.id, creator.id)
    event = await service.transition_status(event.id, EventStatus.REGISTRATION_OPEN, creator.id)

    assert event.configuration is not None
    response = await service.to_response(event)
    assert response.configuration is not None
    assert response.configuration.capacity == 10
    assert response.configuration.registered_count == 0
    assert response.configuration.available_capacity == 10
    assert response.configuration.registration_status == "open"
    assert response.configuration.registration_end_at == deadline


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


@pytest.mark.asyncio
async def test_schedule_conflicts_and_lifecycle_are_server_enforced(db_session):
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service, mobile_suffix="7")
    venue = await service.add_venue(event.id, name="Main Hall", capacity=100)
    start = event.start_date + timedelta(hours=1)
    end = start + timedelta(hours=2)
    first = await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Opening", venue_id=venue.id, start_time=start, end_time=end, expected_capacity=50)

    with pytest.raises(ScheduleConflictError) as conflict:
        await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Overlap", venue_id=venue.id, start_time=start + timedelta(minutes=30), end_time=end + timedelta(minutes=30))
    assert conflict.value.details["reason_code"] == "VENUE_OVERLAP"

    moved = await service.update_schedule_item(event.id, first.id, actor_user_id=creator.id, start_time=end + timedelta(minutes=1), end_time=end + timedelta(hours=1))
    assert moved.start_time == end + timedelta(minutes=1)
    cancelled = await service.cancel_schedule_item(event.id, first.id, actor_user_id=creator.id)
    assert cancelled.status == ScheduleStatus.CANCELLED
    await service.delete_schedule_item(event.id, first.id, actor_user_id=creator.id)


@pytest.mark.asyncio
async def test_schedule_resource_availability_capacity_and_time_validation(db_session):
    service = EventService(db_session)
    event, creator = await _make_event(db_session, service, mobile_suffix="6")
    start = event.start_date + timedelta(hours=2)
    venue = await service.add_venue(event.id, name="Hall", capacity=20, availability=[{"start_time": (start + timedelta(hours=1)).isoformat(), "end_time": (start + timedelta(hours=3)).isoformat()}])
    with pytest.raises(ScheduleConflictError) as unavailable:
        await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Too early", venue_id=venue.id, start_time=start, end_time=start + timedelta(minutes=30))
    assert unavailable.value.details["reason_code"] == "VENUE_UNAVAILABLE"
    with pytest.raises(ScheduleConflictError) as capacity:
        await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Too large", venue_id=venue.id, start_time=start + timedelta(hours=1), end_time=start + timedelta(hours=2), expected_capacity=21)
    assert capacity.value.details["reason_code"] == "CAPACITY_EXCEEDED"
    with pytest.raises(ScheduleConflictError) as invalid:
        await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Invalid", venue_id=venue.id, start_time=start, end_time=start)
    assert invalid.value.details["reason_code"] == "INVALID_TIME_RANGE"

    resource_start = start + timedelta(hours=1)
    await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Resource A", resource_key="stage-a", start_time=resource_start, end_time=resource_start + timedelta(minutes=30))
    with pytest.raises(ScheduleConflictError) as resource:
        await service.add_schedule_item(event.id, actor_user_id=creator.id, title="Resource B", resource_key="stage-a", start_time=resource_start + timedelta(minutes=10), end_time=resource_start + timedelta(minutes=40))
    assert resource.value.details["reason_code"] == "RESOURCE_OVERLAP"


@pytest.mark.asyncio
async def test_template_duplication_copies_configuration_not_runtime_data(db_session):
    service, source, _creator, manager, outsider = await _make_event_with_users(db_session)
    await ConfigEngineService(db_session).upsert_configuration(
        source.id,
        participation_types=["individual", "team"],
        fee_amount=250,
        currency="INR",
        capacity=40,
        registration_end_at=source.start_date - timedelta(days=2),
        approval_required=True,
        rules={"min_age": 18},
        discount_rules={"codes": {"EARLY": {"type": "percentage", "value": 10}}},
    )
    await ConfigEngineService(db_session).upsert_field_schema(source.id, "individual", [{"key": "shirt", "label": "Shirt", "type": "select", "required": True, "options": ["S", "M"]}])
    venue = await service.add_venue(source.id, name="Source Hall", capacity=100)
    await service.add_schedule_item(source.id, actor_user_id=manager.id, title="Opening", venue_id=venue.id, resource_key="stage-a", start_time=source.start_date + timedelta(hours=1), end_time=source.start_date + timedelta(hours=2))
    zone = AccessZone(event_id=source.id, code="MAIN", name="Main Gate")
    db_session.add(zone)
    await db_session.flush()
    db_session.add(AccessPolicy(event_id=source.id, access_type="general", allowed_zone_ids=[str(zone.id)], allows_reentry=True, max_entries=2))
    await db_session.commit()

    template = await service.create_template(manager, name="Sports Template", description="Reusable setup", source_event_id=source.id)
    listed, total = await service.list_templates(manager, page=1, page_size=25)
    assert total == 1
    assert listed[0].id == template.id
    duplicate = await service.duplicate_event(manager, source.id, name="Copied Sports Day", start_date=source.start_date + timedelta(days=30), end_date=source.end_date + timedelta(days=30))

    assert duplicate.id != source.id
    assert duplicate.status == EventStatus.DRAFT
    assert duplicate.configuration.capacity == 40
    assert duplicate.configuration.participation_types == ["individual", "team"]
    copied_venues = await service.list_venues(duplicate.id)
    copied_schedule = await service.list_schedule(duplicate.id)
    assert len(copied_venues) == 1
    assert copied_venues[0].id != venue.id
    assert len(copied_schedule) == 1
    assert copied_schedule[0].event_id == duplicate.id
    assert copied_schedule[0].start_time == source.start_date + timedelta(days=30, hours=1)
    copied_zone = (await db_session.execute(select(AccessZone).where(AccessZone.event_id == duplicate.id))).scalar_one()
    copied_policy = (await db_session.execute(select(AccessPolicy).where(AccessPolicy.event_id == duplicate.id))).scalar_one()
    assert copied_zone.id != zone.id
    assert copied_policy.allowed_zone_ids == [str(copied_zone.id)]

    duplicate.name = "Changed Copy"
    await db_session.commit()
    source_again = await service.get_event_or_raise(source.id)
    assert source_again.name == "Sample Community Sports Day"
    assert (await service.list_schedule(source.id))[0].title == "Opening"
    with pytest.raises(PermissionDeniedError):
        await service.duplicate_event(outsider, source.id, name="Nope", start_date=source.start_date + timedelta(days=60), end_date=source.end_date + timedelta(days=60))


@pytest.mark.asyncio
async def test_template_lifecycle_and_rollback_on_invalid_dates(db_session):
    service, source, _creator, manager, _outsider = await _make_event_with_users(db_session)
    template = await service.create_template(manager, name="Template", description=None, source_event_id=source.id)
    with pytest.raises(ValidationError):
        await service.create_event_from_template(manager, template.id, name="Invalid", start_date=source.start_date, end_date=source.start_date)
    assert (await service.list_events(include_all_statuses=True))
    updated = await service.update_template(manager, template.id, name="Updated Template")
    assert updated.name == "Updated Template"
    archived = await service.archive_template(manager, template.id)
    assert archived.is_archived is True
    await service.delete_template(manager, template.id)
    with pytest.raises(NotFoundError):
        await service._get_visible_template(manager, template.id)


@pytest.mark.asyncio
async def test_schedule_cannot_use_another_event_private_venue(db_session):
    service = EventService(db_session)
    event_a, creator = await _make_event(db_session, service, mobile_suffix="4")
    event_b, _ = await _make_event(db_session, service, mobile_suffix="5")
    venue = await service.add_venue(event_a.id, name="Private Hall")
    with pytest.raises(VenueNotFoundError):
        await service.add_schedule_item(event_b.id, actor_user_id=creator.id, title="Cross event", venue_id=venue.id, start_time=event_b.start_date + timedelta(hours=1), end_time=event_b.start_date + timedelta(hours=2))
