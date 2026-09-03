"""
Phase 3 funnel coverage.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.service import EventService
from app.modules.funnels.models import EntryStatus, StageType
from app.modules.funnels.service import FunnelService
from app.modules.identity.models import User
from app.modules.registrations.service import RegistrationService


async def _make_event(db_session):
    creator = User(mobile_number="+919400000001")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=60)
    event = await EventService(db_session).create_event(
        created_by=creator.id,
        name="Phase 3 Funnel Event",
        description="fixture",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )
    await ConfigEngineService(db_session).upsert_configuration(
        event.id,
        participation_types=["individual"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    return event, creator


@pytest.mark.asyncio
async def test_funnel_stage_vote_and_advance(db_session):
    event, actor = await _make_event(db_session)
    reg = await RegistrationService(db_session).create_registration(
        event_id=event.id,
        actor=actor,
        participation_type="individual",
        date_of_birth=None,
        child_id=None,
        team_id=None,
        documents_provided=[],
        answers={},
        participants=[],
    )

    service = FunnelService(db_session)
    stage_one = await service.create_stage(
        event.id, name="Public Vote", stage_type=StageType.PUBLIC_VOTE, order_index=1, threshold=1, stage_metadata={}
    )
    stage_two = await service.create_stage(
        event.id, name="Final Review", stage_type=StageType.MANUAL_REVIEW, order_index=2, threshold=None, stage_metadata={}
    )

    entry = await service.create_entry(event.id, reg.id)
    assert entry.current_stage_id == stage_one.id

    entry = await service.vote_entry(entry.id, actor)
    assert entry.current_stage_id == stage_two.id
    assert entry.status == EntryStatus.ADVANCED

    entry = await service.advance_entry(entry.id, actor, "advance")
    assert entry.status == EntryStatus.COMPLETED


@pytest.mark.asyncio
async def test_public_can_discover_entries_only_for_a_public_vote_stage(db_session):
    """
    Regression test for a real gap found while building the mobile app's
    public voting screen: GET /entries is Event-Manager-only, so a plain
    participant had no way whatsoever to discover which entries exist to
    vote for during an active public_vote stage.
    """
    from app.exceptions import PermissionDeniedError

    event, actor = await _make_event(db_session)
    reg = await RegistrationService(db_session).create_registration(
        event_id=event.id, actor=actor, participation_type="individual",
        date_of_birth=None, child_id=None, team_id=None,
        documents_provided=[], answers={}, participants=[],
    )

    service = FunnelService(db_session)
    public_stage = await service.create_stage(
        event.id, name="Public Vote", stage_type=StageType.PUBLIC_VOTE, order_index=1, threshold=1, stage_metadata={}
    )
    jury_stage = await service.create_stage(
        event.id, name="Jury Review", stage_type=StageType.JURY_REVIEW, order_index=2, threshold=None, stage_metadata={}
    )
    entry = await service.create_entry(event.id, reg.id)

    # A public_vote stage's entries are discoverable by anyone.
    entries = await service.list_public_vote_entries(public_stage.id)
    assert len(entries) == 1
    assert entries[0].id == entry.id

    # A jury/manual-review stage is NOT exposed through this path, even
    # though the general-purpose list_entries (Event-Manager-only) can
    # still see it — this endpoint is deliberately narrower.
    with pytest.raises(PermissionDeniedError):
        await service.list_public_vote_entries(jury_stage.id)