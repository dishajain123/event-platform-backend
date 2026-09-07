import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from app.core.audit import write_audit_log
from app.core.pagination import Page
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.models import Event
from app.modules.interactions.models import EventPoll, EventQuestion, PollOption, PollResponse, PollStatus, PollVote, QuestionStatus, QuestionUpvote
from app.modules.notifications.service import NotificationService
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES, Registration
from app.modules.identity.models import User


class InteractionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def event(self, event_id):
        event = await self.db.get(Event, event_id)
        if event is None:
            raise NotFoundError("Event not found.")
        return event

    async def eligible(self, event_id, user_id):
        return await self.db.scalar(select(func.count(Registration.id)).where(
            Registration.event_id == event_id, Registration.user_id == user_id,
            Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)),
        )) > 0

    async def poll(self, poll_id, lock=False):
        stmt = select(EventPoll).where(EventPoll.id == poll_id)
        if lock:
            stmt = stmt.with_for_update()
        poll = await self.db.scalar(stmt)
        if poll is None:
            raise NotFoundError("Poll not found.")
        return poll

    async def refresh_poll(self, poll):
        now = datetime.now(timezone.utc)
        starts_at = poll.starts_at if poll.starts_at.tzinfo else poll.starts_at.replace(tzinfo=timezone.utc)
        ends_at = poll.ends_at if poll.ends_at.tzinfo else poll.ends_at.replace(tzinfo=timezone.utc)
        target = None
        if poll.status == PollStatus.SCHEDULED and now >= starts_at:
            target = PollStatus.LIVE
        if poll.status == PollStatus.LIVE and now >= ends_at:
            target = PollStatus.CLOSED
        if target:
            poll.status = target
            await self.db.flush()
        return poll

    async def poll_options(self, poll_id):
        return list((await self.db.scalars(select(PollOption).where(PollOption.poll_id == poll_id).order_by(PollOption.sort_order, PollOption.id))).all())

    async def poll_out(self, poll):
        await self.refresh_poll(poll)
        set_committed_value(poll, "options", await self.poll_options(poll.id))
        return poll

    async def create_poll(self, event_id, actor, payload):
        await self.event(event_id)
        if payload.ends_at <= payload.starts_at:
            raise ValidationError("Poll end must be after its start.")
        if payload.choice_mode.value == "multiple" and payload.max_selections is None:
            raise ValidationError("Multiple-choice polls require max_selections.")
        if payload.max_selections and payload.max_selections > len(payload.options):
            raise ValidationError("max_selections cannot exceed option count.")
        poll = EventPoll(event_id=event_id, created_by=actor.id, **payload.model_dump(exclude={"options"}))
        self.db.add(poll)
        await self.db.flush()
        for index, option in enumerate(payload.options):
            self.db.add(PollOption(poll_id=poll.id, label=option.label, sort_order=index))
        await write_audit_log(self.db, entity_type="event_poll", entity_id=poll.id, action="created", actor_user_id=actor.id, after_value={"event_id": str(event_id)})
        await self.db.commit()
        await self.db.refresh(poll)
        return await self.poll_out(poll)

    async def change_poll_status(self, poll_id, actor, target):
        poll = await self.poll(poll_id, lock=True)
        allowed = {
            PollStatus.DRAFT: {PollStatus.SCHEDULED, PollStatus.CLOSED},
            PollStatus.SCHEDULED: {PollStatus.LIVE, PollStatus.CLOSED},
            PollStatus.LIVE: {PollStatus.CLOSED},
            PollStatus.CLOSED: {PollStatus.ARCHIVED}, PollStatus.ARCHIVED: set(),
        }
        if target not in allowed[poll.status]:
            raise ValidationError("Invalid poll status transition.")
        poll.status = target
        await write_audit_log(self.db, entity_type="event_poll", entity_id=poll.id, action="status_changed", actor_user_id=actor.id, after_value={"status": target.value})
        await self.db.commit()
        await self._notify_poll_status(poll, target)
        return await self.poll_out(poll)

    async def _notify_poll_status(self, poll, target):
        if target not in {PollStatus.SCHEDULED, PollStatus.LIVE, PollStatus.CLOSED}:
            return
        try:
            user_ids = list((await self.db.scalars(select(Registration.user_id).where(Registration.event_id == poll.event_id, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES))))).all())
            notification_service = NotificationService(self.db)
            ids = []
            for user_id in set(user_ids):
                notification = await notification_service._queue_automated(
                    event_id=poll.event_id, user_id=user_id,
                    title="Event poll scheduled" if target == PollStatus.SCHEDULED else ("Event poll opened" if target == PollStatus.LIVE else "Poll results are available"),
                    body=f"The poll '{poll.title}' is now {target.value}.",
                    notification_type="event_interaction", dedupe_key=f"poll:{poll.id}:{target.value}:{user_id}",
                    target_metadata={"event_id": str(poll.event_id), "poll_id": str(poll.id), "notification": "poll_status"},
                )
                if notification: ids.append(notification.id)
            if ids:
                await self.db.commit()
        except Exception:
            await self.db.rollback()

    async def list_polls(self, event_id, page, page_size, public=False):
        filters = [EventPoll.event_id == event_id]
        if public:
            filters.append(EventPoll.status.in_([PollStatus.SCHEDULED, PollStatus.LIVE, PollStatus.CLOSED]))
        total = await self.db.scalar(select(func.count(EventPoll.id)).where(*filters)) or 0
        rows = list((await self.db.scalars(select(EventPoll).where(*filters).order_by(EventPoll.starts_at.desc(), EventPoll.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        for poll in rows:
            await self.poll_out(poll)
        return Page(items=rows, total=total, page=page, page_size=page_size)

    async def vote(self, poll_id, user, option_ids):
        poll = await self.poll(poll_id, lock=True)
        await self.refresh_poll(poll)
        if poll.status != PollStatus.LIVE:
            raise ValidationError("Poll is not live.")
        if not await self.eligible(poll.event_id, user.id):
            raise PermissionDeniedError("Only eligible event participants may vote.")
        selected = list(dict.fromkeys(option_ids))
        options = await self.poll_options(poll.id)
        valid = {option.id for option in options}
        if any(option_id not in valid for option_id in selected):
            raise ValidationError("Poll option does not belong to this poll.")
        if poll.choice_mode.value == "single" and len(selected) != 1:
            raise ValidationError("Select exactly one option.")
        if poll.max_selections and len(selected) > poll.max_selections:
            raise ValidationError("Too many options selected.")
        response = await self.db.scalar(select(PollResponse).where(PollResponse.poll_id == poll.id, PollResponse.user_id == user.id).with_for_update())
        if response and not poll.allow_vote_change:
            raise ConflictError("You have already voted in this poll.")
        now = datetime.now(timezone.utc)
        if response:
            await self.db.execute(delete(PollVote).where(PollVote.response_id == response.id))
            response.submitted_at = now
        else:
            response = PollResponse(poll_id=poll.id, user_id=user.id, submitted_at=now)
            self.db.add(response)
            await self.db.flush()
        for option_id in selected:
            self.db.add(PollVote(response_id=response.id, option_id=option_id))
        await write_audit_log(self.db, entity_type="event_poll", entity_id=poll.id, action="vote_submitted", actor_user_id=user.id)
        await self.db.commit()
        return response, selected

    async def vote_for(self, poll_id, user_id):
        response = await self.db.scalar(select(PollResponse).where(PollResponse.poll_id == poll_id, PollResponse.user_id == user_id))
        if not response:
            return None
        return list((await self.db.scalars(select(PollVote.option_id).where(PollVote.response_id == response.id))).all()), response.submitted_at

    async def results(self, poll_id, user, manager=False):
        poll = await self.poll(poll_id)
        await self.refresh_poll(poll)
        if not manager and not await self.eligible(poll.event_id, user.id):
            raise PermissionDeniedError("Only eligible event participants may view poll results.")
        own = await self.vote_for(poll.id, user.id)
        allowed = manager or poll.result_visibility.value == "always" or (poll.result_visibility.value == "after_voting" and own) or (poll.result_visibility.value == "after_close" and poll.status in {PollStatus.CLOSED, PollStatus.ARCHIVED})
        if not allowed:
            raise PermissionDeniedError("Poll results are not available yet.")
        counts = dict((option_id, count) for option_id, count in (await self.db.execute(select(PollVote.option_id, func.count(PollVote.id)).join(PollResponse, PollResponse.id == PollVote.response_id).where(PollResponse.poll_id == poll.id).group_by(PollVote.option_id))).all())
        total = sum(counts.values())
        return [{"option_id": option.id, "label": option.label, "votes": counts.get(option.id, 0), "percentage": round((counts.get(option.id, 0) / total * 100) if total else 0, 2)} for option in await self.poll_options(poll.id)]

    async def question(self, question_id, lock=False):
        stmt = select(EventQuestion).where(EventQuestion.id == question_id)
        if lock:
            stmt = stmt.with_for_update()
        question = await self.db.scalar(stmt)
        if question is None:
            raise NotFoundError("Question not found.")
        return question

    async def submit_question(self, event_id, user, payload):
        await self.event(event_id)
        if not await self.eligible(event_id, user.id):
            raise PermissionDeniedError("Only eligible event participants may ask questions.")
        question = EventQuestion(event_id=event_id, user_id=user.id, **payload.model_dump())
        self.db.add(question)
        await self.db.flush()
        await write_audit_log(self.db, entity_type="event_question", entity_id=question.id, action="submitted", actor_user_id=user.id)
        await self.db.commit(); await self.db.refresh(question)
        return question

    async def questions(self, event_id, page, page_size, status=None, search=None, public=False, user_id=None):
        filters = [EventQuestion.event_id == event_id]
        if public: filters.append(EventQuestion.status.in_([QuestionStatus.APPROVED, QuestionStatus.ANSWERED]))
        elif status: filters.append(EventQuestion.status == status)
        if search: filters.append(EventQuestion.question.ilike(f"%{search}%"))
        total = await self.db.scalar(select(func.count(EventQuestion.id)).where(*filters)) or 0
        rows = list((await self.db.scalars(select(EventQuestion).where(*filters).order_by(EventQuestion.created_at.desc(), EventQuestion.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        result = []
        for row in rows:
            item = {"id": row.id, "event_id": row.event_id, "question": row.question, "display_name": None if row.anonymous else row.display_name, "status": row.status, "answer_text": row.answer_text, "answered_at": row.answered_at, "created_at": row.created_at, "upvotes": await self.db.scalar(select(func.count(QuestionUpvote.id)).where(QuestionUpvote.question_id == row.id)) or 0, "user_upvoted": bool(user_id and await self.db.scalar(select(QuestionUpvote.id).where(QuestionUpvote.question_id == row.id, QuestionUpvote.user_id == user_id)))}
            result.append(item)
        return Page(items=result, total=total, page=page, page_size=page_size)

    async def moderate(self, question_id, actor, status):
        question = await self.question(question_id, lock=True)
        if status in {QuestionStatus.ANSWERED, QuestionStatus.ARCHIVED}:
            raise ValidationError("Use the answer or archive action for this transition.")
        question.status = status
        await write_audit_log(self.db, entity_type="event_question", entity_id=question.id, action="moderated", actor_user_id=actor.id, after_value={"status": status.value})
        await self.db.commit(); await self.db.refresh(question)
        if status == QuestionStatus.APPROVED:
            try:
                notification = await NotificationService(self.db)._queue_automated(event_id=question.event_id, user_id=question.user_id, title="Your event question was approved", body="Your question is now visible to event attendees.", notification_type="event_interaction", dedupe_key=f"question-approved:{question.id}", target_metadata={"event_id": str(question.event_id), "question_id": str(question.id), "notification": "question_approved"})
                if notification: await self.db.commit()
            except Exception: await self.db.rollback()
        return question

    async def answer(self, question_id, actor, answer_text):
        question = await self.question(question_id)
        if question.status != QuestionStatus.APPROVED:
            raise ValidationError("Only approved questions can be answered.")
        question.answer_text, question.answered_by, question.answered_at, question.status = answer_text, actor.id, datetime.now(timezone.utc), QuestionStatus.ANSWERED
        await write_audit_log(self.db, entity_type="event_question", entity_id=question.id, action="answered", actor_user_id=actor.id)
        await self.db.commit()
        await self.db.refresh(question)
        try:
            notification = await NotificationService(self.db)._queue_automated(event_id=question.event_id, user_id=question.user_id, title="Your event question was answered", body="Your question received an answer.", notification_type="event_interaction", dedupe_key=f"question-answered:{question.id}", target_metadata={"event_id": str(question.event_id), "question_id": str(question.id)})
            if notification: await self.db.commit()
        except Exception: await self.db.rollback()
        return question

    async def upvote(self, question_id, user):
        question = await self.question(question_id, lock=True)
        if question.status not in {QuestionStatus.APPROVED, QuestionStatus.ANSWERED}:
            raise ValidationError("Only approved questions can be upvoted.")
        if not await self.eligible(question.event_id, user.id):
            raise PermissionDeniedError("Only eligible event participants may upvote questions.")
        existing = await self.db.scalar(select(QuestionUpvote).where(QuestionUpvote.question_id == question.id, QuestionUpvote.user_id == user.id))
        if existing: await self.db.delete(existing)
        else: self.db.add(QuestionUpvote(question_id=question.id, user_id=user.id))
        await self.db.commit()
        return {"upvoted": existing is None}

    async def metrics(self, event_id):
        now = datetime.now(timezone.utc)
        active = await self.db.scalar(select(func.count(EventPoll.id)).where(EventPoll.event_id == event_id, EventPoll.status.in_([PollStatus.SCHEDULED, PollStatus.LIVE]))) or 0
        responses = await self.db.scalar(select(func.count(PollResponse.id)).join(EventPoll, EventPoll.id == PollResponse.poll_id).where(EventPoll.event_id == event_id)) or 0
        submitted = await self.db.scalar(select(func.count(EventQuestion.id)).where(EventQuestion.event_id == event_id)) or 0
        approved = await self.db.scalar(select(func.count(EventQuestion.id)).where(EventQuestion.event_id == event_id, EventQuestion.status.in_([QuestionStatus.APPROVED, QuestionStatus.ANSWERED]))) or 0
        answered = await self.db.scalar(select(func.count(EventQuestion.id)).where(EventQuestion.event_id == event_id, EventQuestion.status == QuestionStatus.ANSWERED)) or 0
        upvotes = await self.db.scalar(select(func.count(QuestionUpvote.id)).join(EventQuestion, EventQuestion.id == QuestionUpvote.question_id).where(EventQuestion.event_id == event_id)) or 0
        return {"active_polls": active, "poll_responses": responses, "questions_submitted": submitted, "questions_approved": approved, "questions_answered": answered, "question_upvotes": upvotes}
