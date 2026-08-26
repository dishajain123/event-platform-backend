"""
This is the Phase 2 "Done means" proof: a generic fixture event (no
real branding — could be any organizer's under-16 sports category) is
configured with an age rule, a team-size rule, a required document,
and one dynamic form field. The rule engine must correctly accept a
valid submission and reject each individual way a submission can be
invalid — proving the engine generalizes rather than being written
for one specific event.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.modules.config_engine.exceptions import ConfigurationNotFoundError
from app.modules.config_engine.service import ConfigEngineService, calculate_age
from app.modules.events.service import EventService
from app.modules.identity.models import User


async def _make_configured_event(db_session):
    """Builds one generic fixture event with a full set of rules and a
    dynamic field — the same shape any real event's Sports/Talent/whatever
    category could take, but with placeholder names only."""
    events = EventService(db_session)
    config = ConfigEngineService(db_session)

    creator = User(mobile_number="+919111111111")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=60)
    event = await events.create_event(
        created_by=creator.id,
        name="Sample Under-16 Category",
        description="Fixture event for rule-engine tests",
        category="sample",
        start_date=start,
        end_date=start + timedelta(days=1),
        organization_id=None,
    )

    await config.upsert_configuration(
        event.id,
        participation_types=["team"],
        fee_amount=1000.0,
        currency="INR",
        capacity=100,
        approval_required=False,
        rules={
            "min_age": None,
            "max_age": 15,  # "under 16" as of the event date
            "team_size": {"min": 5, "max": 11},
            "required_documents": ["aadhaar"],
        },
        discount_rules=None,
    )

    await config.upsert_field_schema(
        event.id,
        "team",
        [
            {"key": "tshirt_size", "label": "T-Shirt Size", "type": "select",
             "required": True, "options": ["S", "M", "L", "XL"]},
            {"key": "emergency_contact", "label": "Emergency Contact", "type": "text",
             "required": True, "options": None},
        ],
    )

    return event, config


@pytest.mark.asyncio
async def test_calculate_age_handles_birthday_not_yet_reached():
    dob = date(2010, 12, 1)
    event_date = date(2026, 11, 1)
    assert calculate_age(dob, event_date) == 15


@pytest.mark.asyncio
async def test_valid_submission_is_accepted(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=7,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is True
    assert errors == []


@pytest.mark.asyncio
async def test_over_age_participant_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2005, 1, 1),
        team_member_count=7,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "date_of_birth" for e in errors)


@pytest.mark.asyncio
async def test_missing_date_of_birth_is_rejected_when_age_rule_exists(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=None,
        team_member_count=7,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "date_of_birth" for e in errors)


@pytest.mark.asyncio
async def test_team_below_minimum_size_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=3,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "team_member_count" for e in errors)


@pytest.mark.asyncio
async def test_team_above_maximum_size_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=15,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "team_member_count" for e in errors)


@pytest.mark.asyncio
async def test_missing_required_document_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=7,
        documents_provided=[],
        answers={"tshirt_size": "M", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "documents" for e in errors)


@pytest.mark.asyncio
async def test_missing_required_dynamic_field_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=7,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "M"},
    )

    assert is_eligible is False
    assert any(e.field == "emergency_contact" for e in errors)


@pytest.mark.asyncio
async def test_invalid_select_option_is_rejected(db_session):
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2013, 6, 15),
        team_member_count=7,
        documents_provided=["aadhaar"],
        answers={"tshirt_size": "XXXL", "emergency_contact": "+919876500000"},
    )

    assert is_eligible is False
    assert any(e.field == "tshirt_size" for e in errors)


@pytest.mark.asyncio
async def test_multiple_violations_are_all_reported_together(db_session):
    """A single submission that's wrong in three ways should surface all
    three errors at once, not just the first one found."""
    event, config = await _make_configured_event(db_session)

    is_eligible, errors = await config.validate_registration(
        event.id,
        participation_type="team",
        date_of_birth=date(2000, 1, 1),
        team_member_count=2,
        documents_provided=[],
        answers={},
    )

    assert is_eligible is False
    error_fields = {e.field for e in errors}
    assert "date_of_birth" in error_fields
    assert "team_member_count" in error_fields
    assert "documents" in error_fields
    assert "tshirt_size" in error_fields
    assert "emergency_contact" in error_fields


@pytest.mark.asyncio
async def test_validating_against_an_unconfigured_event_raises(db_session):
    events = EventService(db_session)
    config = ConfigEngineService(db_session)

    creator = User(mobile_number="+919222222222")
    db_session.add(creator)
    await db_session.flush()

    start = datetime.now(timezone.utc) + timedelta(days=10)
    event = await events.create_event(
        created_by=creator.id,
        name="Unconfigured Event",
        description=None,
        category=None,
        start_date=start,
        end_date=start + timedelta(hours=2),
        organization_id=None,
    )

    with pytest.raises(ConfigurationNotFoundError):
        await config.validate_registration(
            event.id, "individual", None, None, [], {}
        )