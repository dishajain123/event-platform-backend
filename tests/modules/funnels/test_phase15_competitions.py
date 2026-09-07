"""Phase 15 competition lifecycle, pagination, and standings coverage."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.funnels.models import (
    CompetitionMatch,
    CompetitionStatus,
    MatchResultStatus,
    MatchStatus,
    StageType,
    EntryStatus,
)
from app.modules.funnels.service import FunnelService
from app.modules.identity.models import User
from app.modules.registrations.service import RegistrationService
from app.modules.notifications.models import Notification
from app.modules.notifications.service import NotificationService

from tests.modules.funnels.test_funnels import _make_event


async def _competition_fixture(db_session):
    event, actor = await _make_event(db_session)
    service = FunnelService(db_session)
    competition = await service.create_competition(
        event.id,
        actor,
        name="Open Championship",
        description="A competition fixture",
        competition_type="sport",
        participation_mode="individual",
        max_participants=16,
        registration_deadline=None,
    )
    stage = await service.create_stage(
        event.id,
        competition_id=competition.id,
        name="Group stage",
        stage_type=StageType.GROUP,
        order_index=1,
        threshold=None,
        stage_metadata={},
        advancement_rules={"points_to_advance": 3},
    )
    second_actor = User(mobile_number="+919400000002")
    db_session.add(second_actor)
    await db_session.flush()
    registrations = []
    for registration_actor in (actor, second_actor):
        registrations.append(await RegistrationService(db_session).create_registration(
            event_id=event.id,
            actor=registration_actor,
            participation_type="individual",
            date_of_birth=None,
            child_id=None,
            team_id=None,
            documents_provided=[],
            answers={},
            participants=[],
        ))
    entries = [await service.create_entry(event.id, registration.id, competition.id) for registration in registrations]
    return event, actor, service, competition, stage, entries


@pytest.mark.asyncio
async def test_competition_lifecycle_and_server_pagination(db_session):
    _, actor, service, competition, _, entries = await _competition_fixture(db_session)

    await service.change_competition_status(competition.id, actor, CompetitionStatus.OPEN)
    page, total = await service.funnels.page_entries_for_competition(competition.id, page=2, page_size=1)
    assert total == 2
    assert len(page) == 1
    assert page[0].id == entries[1].id

    with pytest.raises(Exception):
        await service.create_entry(entries[0].event_id, entries[0].registration_id, competition.id)

    await service._queue_competition_notifications(
        event_id=entries[0].event_id,
        notification_type="competition_fixture",
        dedupe_suffix="fixture:test:scheduled",
        recipient_ids=[actor.id],
        title="Fixture scheduled",
        body="Fixture scheduled",
        metadata={"competition_id": str(competition.id), "notification": "fixture_scheduled"},
    )
    await service._queue_competition_notifications(
        event_id=entries[0].event_id,
        notification_type="competition_fixture",
        dedupe_suffix="fixture:test:scheduled",
        recipient_ids=[actor.id],
        title="Fixture scheduled",
        body="Fixture scheduled",
        metadata={"competition_id": str(competition.id), "notification": "fixture_scheduled"},
    )
    notifications = list((await db_session.execute(select(Notification).where(Notification.dedupe_key == f"competition:fixture:test:scheduled:{actor.id}"))).scalars())
    assert len(notifications) == 1


@pytest.mark.asyncio
async def test_competition_result_updates_deterministic_standings(db_session, monkeypatch):
    event, actor, service, competition, stage, entries = await _competition_fixture(db_session)
    now = datetime.now(timezone.utc) + timedelta(days=2)
    match = CompetitionMatch(
        competition_id=competition.id,
        event_id=event.id,
        stage_id=stage.id,
        round_number=1,
        match_number=1,
        entry_a_id=entries[0].id,
        entry_b_id=entries[1].id,
        scheduled_start=now,
        scheduled_end=now + timedelta(hours=1),
        status=MatchStatus.SCHEDULED,
        result_status=MatchResultStatus.PENDING,
    )
    db_session.add(match)
    await db_session.commit()

    await service.record_result(
        match.id,
        actor,
        score_a=2,
        score_b=1,
        result_status=MatchResultStatus.WIN,
        winner_entry_id=entries[0].id,
    )
    standings = await service.standings(competition.id)
    assert standings[0]["entry_id"] == entries[0].id
    assert standings[0]["points"] == 3
    assert standings[1]["points"] == 0
    assert entries[0].status == EntryStatus.COMPLETED
    assert entries[1].status == EntryStatus.ELIMINATED
    notification_rows = list((await db_session.execute(select(Notification).where(Notification.event_id == event.id))).scalars())
    notification_types = {notification.notification_type for notification in notification_rows}
    assert {"competition_result", "competition_progression", "competition_elimination"}.issubset(notification_types)

    async def fail_queue(*args, **kwargs):
        raise RuntimeError("provider/outbox unavailable")

    monkeypatch.setattr(NotificationService, "_queue_automated", fail_queue)
    await service._queue_competition_notifications(
        event_id=event.id,
        notification_type="competition_result",
        dedupe_suffix=f"match:{match.id}:retry",
        recipient_ids=[actor.id],
        title="Result",
        body="Result",
        metadata={"match_id": str(match.id)},
    )
    await db_session.refresh(entries[0])
    assert entries[0].status == EntryStatus.COMPLETED
