from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.modules.events.models import Event, EventStatus
from app.modules.identity.models import User
from app.modules.interactions.models import PollResultVisibility, PollStatus, QuestionStatus
from app.modules.interactions.schemas import PollCreateIn, PollOptionIn, QuestionCreateIn
from app.modules.interactions.service import InteractionService
from app.modules.registrations.models import Registration, RegistrationStatus


async def _fixture(db):
    user = User(mobile_number="+919900000001", name="Attendee")
    outsider = User(mobile_number="+919900000002")
    event = Event(name="Interaction Event", start_date=datetime.now(timezone.utc), end_date=datetime.now(timezone.utc) + timedelta(days=1), status=EventStatus.LIVE, created_by=user.id)
    db.add_all([user, outsider, event]); await db.flush()
    db.add(Registration(event_id=event.id, user_id=user.id, participation_type="viewer", status=RegistrationStatus.CONFIRMED))
    await db.commit()
    return event, user, outsider


def _poll_payload(start):
    return PollCreateIn(title="Audience choice", starts_at=start, ends_at=start + timedelta(hours=1), options=[PollOptionIn(label="One"), PollOptionIn(label="Two")])


@pytest.mark.asyncio
async def test_poll_vote_duplicate_change_and_results(db_session):
    event, user, _ = await _fixture(db_session)
    service = InteractionService(db_session)
    payload = _poll_payload(datetime.now(timezone.utc) - timedelta(minutes=1)); payload.result_visibility = PollResultVisibility.ALWAYS
    poll = await service.create_poll(event.id, user, payload)
    poll = await service.change_poll_status(poll.id, user, PollStatus.SCHEDULED)
    first = poll.options[0].id
    second = poll.options[1].id
    await service.vote(poll.id, user, [first])
    with pytest.raises(ConflictError):
        await service.vote(poll.id, user, [second])
    assert (await service.results(poll.id, user))[0]["votes"] == 1


@pytest.mark.asyncio
async def test_poll_rejects_ineligible_user_and_enforces_option_rules(db_session):
    event, _, outsider = await _fixture(db_session)
    service = InteractionService(db_session)
    poll = await service.create_poll(event.id, outsider, _poll_payload(datetime.now(timezone.utc) - timedelta(minutes=1)))
    await service.change_poll_status(poll.id, outsider, PollStatus.SCHEDULED)
    with pytest.raises(PermissionDeniedError):
        await service.vote(poll.id, outsider, [poll.options[0].id])


@pytest.mark.asyncio
async def test_questions_are_moderated_and_upvotes_are_toggleable(db_session):
    event, user, outsider = await _fixture(db_session)
    service = InteractionService(db_session)
    question = await service.submit_question(event.id, user, QuestionCreateIn(question="When does the next session start?"))
    assert question.status == QuestionStatus.PENDING
    question = await service.moderate(question.id, user, QuestionStatus.APPROVED)
    assert question.status == QuestionStatus.APPROVED
    with pytest.raises(PermissionDeniedError):
        await service.upvote(question.id, outsider)
    assert (await service.upvote(question.id, user))["upvoted"] is True
    assert (await service.upvote(question.id, user))["upvoted"] is False
    page = await service.questions(event.id, 1, 25, public=True, user_id=user.id)
    assert page.total == 1 and page.items[0]["upvotes"] == 0
