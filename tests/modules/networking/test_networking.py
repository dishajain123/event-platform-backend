from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select
from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.modules.events.models import Event, EventStatus
from app.modules.identity.models import User
from app.modules.networking.models import ConnectionStatus, EventNetworkingConfig, NetworkingVisibility
from app.modules.networking.schemas import ProfileIn
from app.modules.networking.service import NetworkingService
from app.modules.registrations.models import Registration, RegistrationStatus

async def fixture(db):
    users = [User(mobile_number=f"+91980000000{i}", name=f"User {i}") for i in range(1, 4)]
    event = Event(name="Networking", start_date=datetime.now(timezone.utc), end_date=datetime.now(timezone.utc) + timedelta(days=1), status=EventStatus.LIVE)
    db.add_all([*users, event]); await db.flush()
    db.add(EventNetworkingConfig(event_id=event.id, enabled=True, matchmaking_enabled=True))
    for user in users[:2]: db.add(Registration(event_id=event.id, user_id=user.id, participation_type="participant", status=RegistrationStatus.CONFIRMED))
    await db.commit()
    return event, users

@pytest.mark.asyncio
async def test_opt_in_discovery_privacy_and_event_eligibility(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    await service.save_profile(event.id, users[0], ProfileIn(display_name="A", organization="Org", interests=["sport"], visibility=NetworkingVisibility.VISIBLE))
    await service.save_profile(event.id, users[1], ProfileIn(display_name="B", organization="Org", interests=["sport"], visibility=NetworkingVisibility.VISIBLE))
    page = await service.discover(event.id, users[0].id, page=1, page_size=25, recommended=True)
    assert page.total == 1 and page.items[0]["score"] == 6
    assert page.items[0]["explanation"] == ["1 shared interests", "same organization", "same participation type"]
    assert "mobile_number" not in page.items[0]
    with pytest.raises(PermissionDeniedError): await service.discover(event.id, users[2].id, page=1, page_size=25)

@pytest.mark.asyncio
async def test_connection_direction_duplicate_lifecycle_and_blocking(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    for user in users[:2]: await service.save_profile(event.id, user, ProfileIn(display_name=user.name, visibility=NetworkingVisibility.VISIBLE))
    connection = await service.send_request(event.id, users[0], users[1].id, "connect")
    with pytest.raises(ConflictError): await service.send_request(event.id, users[1], users[0].id, "discuss")
    with pytest.raises(PermissionDeniedError): await service.transition(connection.id, users[0], ConnectionStatus.ACCEPTED)
    await service.transition(connection.id, users[1], ConnectionStatus.ACCEPTED)
    await service.transition(connection.id, users[0], ConnectionStatus.BLOCKED)
    with pytest.raises(ConflictError): await service.send_request(event.id, users[1], users[0].id, "connect")
    await service.unblock_participant(event.id, users[0], users[1].id)
    reopened = await service.send_request(event.id, users[1], users[0].id, "connect")
    assert reopened.status == ConnectionStatus.PENDING

@pytest.mark.asyncio
async def test_duplicate_active_reports_are_rejected(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    await service.report(event.id, users[0], users[1].id, "Inappropriate message")
    with pytest.raises(ConflictError):
        await service.report(event.id, users[0], users[1].id, "Repeated report")

@pytest.mark.asyncio
async def test_self_connection_is_rejected(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    with pytest.raises(ValidationError): await service.send_request(event.id, users[0], users[0].id, "connect")

@pytest.mark.asyncio
async def test_recommendation_dismissal_is_idempotent_and_persistent(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    for user in users[:2]: await service.save_profile(event.id, user, ProfileIn(display_name=user.name, visibility=NetworkingVisibility.VISIBLE))
    assert (await service.discover(event.id, users[0].id, page=1, page_size=25, recommended=True)).total == 1
    await service.dismiss(event.id, users[0].id, users[1].id)
    await service.dismiss(event.id, users[0].id, users[1].id)
    page = await service.discover(event.id, users[0].id, page=1, page_size=25, recommended=True)
    assert page.total == 0
    manual = await service.discover(event.id, users[0].id, page=1, page_size=25, recommended=False)
    assert manual.total == 1

@pytest.mark.asyncio
async def test_blocked_participant_is_not_visible_or_connectable(db_session):
    event, users = await fixture(db_session); service = NetworkingService(db_session)
    for user in users[:2]: await service.save_profile(event.id, user, ProfileIn(display_name=user.name, visibility=NetworkingVisibility.VISIBLE))
    await service.block_participant(event.id, users[0], users[1].id)
    assert (await service.discover(event.id, users[0].id, page=1, page_size=25)).total == 0
    with pytest.raises(ConflictError):
        await service.send_request(event.id, users[1], users[0].id, "connect")
