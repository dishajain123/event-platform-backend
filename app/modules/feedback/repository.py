"""Database queries for feedback. Scope is always supplied by the service."""
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.feedback.models import EventFeedback, FeedbackCategory


class FeedbackRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, feedback_id: uuid.UUID) -> EventFeedback | None:
        result = await self.db.execute(
            select(EventFeedback)
            .options(selectinload(EventFeedback.event), selectinload(EventFeedback.user))
            .where(EventFeedback.id == feedback_id)
        )
        return result.scalar_one_or_none()

    async def get_for_user_category(
        self, event_id: uuid.UUID, user_id: uuid.UUID, category: FeedbackCategory
    ) -> EventFeedback | None:
        result = await self.db.execute(
            select(EventFeedback).where(
                EventFeedback.event_id == event_id,
                EventFeedback.user_id == user_id,
                EventFeedback.category == category,
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self, user_id: uuid.UUID, event_id: uuid.UUID | None = None
    ) -> list[EventFeedback]:
        statement = (
            select(EventFeedback)
            .options(selectinload(EventFeedback.event))
            .where(EventFeedback.user_id == user_id)
            .order_by(EventFeedback.created_at.desc())
        )
        if event_id is not None:
            statement = statement.where(EventFeedback.event_id == event_id)
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def list_for_scope(
        self,
        event_ids: set[uuid.UUID] | None,
        event_id: uuid.UUID | None = None,
        category: FeedbackCategory | None = None,
        rating: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EventFeedback]:
        statement = (
            select(EventFeedback)
            .options(selectinload(EventFeedback.event), selectinload(EventFeedback.user))
            .order_by(EventFeedback.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if event_id is not None:
            statement = statement.where(EventFeedback.event_id == event_id)
        elif event_ids is not None:
            statement = statement.where(EventFeedback.event_id.in_(event_ids))
        if category is not None:
            statement = statement.where(EventFeedback.category == category)
        if rating is not None:
            statement = statement.where(EventFeedback.rating == rating)
        if date_from is not None:
            statement = statement.where(EventFeedback.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(EventFeedback.created_at <= date_to)
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def list_for_summary(
        self,
        event_ids: set[uuid.UUID] | None,
        event_id: uuid.UUID | None = None,
        category: FeedbackCategory | None = None,
        rating: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[EventFeedback]:
        statement = select(EventFeedback)
        if event_id is not None:
            statement = statement.where(EventFeedback.event_id == event_id)
        elif event_ids is not None:
            statement = statement.where(EventFeedback.event_id.in_(event_ids))
        if category is not None:
            statement = statement.where(EventFeedback.category == category)
        if rating is not None:
            statement = statement.where(EventFeedback.rating == rating)
        if date_from is not None:
            statement = statement.where(EventFeedback.created_at >= date_from)
        if date_to is not None:
            statement = statement.where(EventFeedback.created_at <= date_to)
        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def create(self, **values) -> EventFeedback:
        feedback = EventFeedback(**values)
        self.db.add(feedback)
        await self.db.commit()
        return await self.get_by_id(feedback.id)
