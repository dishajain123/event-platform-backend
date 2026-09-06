"""Feedback business rules and response shaping."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import PermissionDeniedError
from app.modules.events.models import Event, EventStatus
from app.modules.feedback.exceptions import FeedbackEventUnavailableError, FeedbackNotFoundError
from app.modules.feedback.models import EventFeedback, FeedbackCategory
from app.modules.feedback.repository import FeedbackRepository
from app.modules.feedback.schemas import (
    FeedbackCategoryOut,
    FeedbackCategorySummary,
    FeedbackSummaryOut,
)
from app.modules.identity.models import User


FEEDBACK_EVENT_STATUSES = {EventStatus.LIVE, EventStatus.COMPLETED, EventStatus.ARCHIVED}


class FeedbackService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.feedback = FeedbackRepository(db)

    async def _get_event(self, event_id: uuid.UUID) -> Event:
        event = await self.db.get(Event, event_id)
        if event is None:
            raise FeedbackNotFoundError("Event not found.")
        return event

    async def _ensure_event_accepts_feedback(self, event_id: uuid.UUID) -> Event:
        event = await self._get_event(event_id)
        if event.status not in FEEDBACK_EVENT_STATUSES:
            raise FeedbackEventUnavailableError(
                "Feedback is available while the event is live or after it has ended."
            )
        return event

    @staticmethod
    def categories() -> list[FeedbackCategoryOut]:
        return [FeedbackCategoryOut(code=category, label=category.label) for category in FeedbackCategory]

    async def list_mine(self, actor: User, event_id: uuid.UUID | None = None) -> list[EventFeedback]:
        return await self.feedback.list_for_user(actor.id, event_id)

    async def submit(
        self, actor: User, event_id: uuid.UUID, category: FeedbackCategory, rating: int, comment: str | None
    ) -> EventFeedback:
        await self._ensure_event_accepts_feedback(event_id)
        existing = await self.feedback.get_for_user_category(event_id, actor.id, category)
        if existing is None:
            return await self.feedback.create(
                event_id=event_id, user_id=actor.id, category=category, rating=rating, comment=comment
            )
        existing.rating = rating
        existing.comment = comment
        await self.db.commit()
        return await self.feedback.get_by_id(existing.id)

    async def get_for_actor(self, feedback_id: uuid.UUID, actor: User, can_view_event: bool) -> EventFeedback:
        feedback = await self.feedback.get_by_id(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError("Feedback not found.")
        if feedback.user_id != actor.id and not can_view_event:
            raise PermissionDeniedError("You cannot access another user's feedback.")
        return feedback

    async def update_mine(
        self,
        feedback_id: uuid.UUID,
        actor: User,
        category: FeedbackCategory | None,
        rating: int | None,
        comment: str | None,
    ) -> EventFeedback:
        feedback = await self.feedback.get_by_id(feedback_id)
        if feedback is None:
            raise FeedbackNotFoundError("Feedback not found.")
        if feedback.user_id != actor.id:
            raise PermissionDeniedError("You can update only your own feedback.")
        if category is not None and category != feedback.category:
            duplicate = await self.feedback.get_for_user_category(feedback.event_id, actor.id, category)
            if duplicate is not None and duplicate.id != feedback.id:
                raise FeedbackEventUnavailableError("You already submitted feedback for that category.")
            feedback.category = category
        if rating is not None:
            feedback.rating = rating
        feedback.comment = comment
        await self.db.commit()
        return await self.feedback.get_by_id(feedback.id)

    async def list_scoped(self, **filters) -> list[EventFeedback]:
        return await self.feedback.list_for_scope(**filters)

    async def summary_scoped(self, **filters) -> FeedbackSummaryOut:
        rows = await self.feedback.list_for_summary(**filters)
        distribution = {rating: 0 for rating in range(1, 6)}
        category_rows: dict[FeedbackCategory, list[int]] = {}
        for row in rows:
            distribution[row.rating] += 1
            category_rows.setdefault(row.category, []).append(row.rating)
        return FeedbackSummaryOut(
            response_count=len(rows),
            overall_rating=round(sum(row.rating for row in rows) / len(rows), 2) if rows else None,
            category_summaries=[
                FeedbackCategorySummary(
                    category=category,
                    response_count=len(ratings),
                    average_rating=round(sum(ratings) / len(ratings), 2),
                )
                for category, ratings in sorted(category_rows.items(), key=lambda item: item[0].value)
            ],
            rating_distribution=distribution,
        )
