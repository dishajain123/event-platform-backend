"""Data access for notifications."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification, NotificationTemplate


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Notification:
        notification = Notification(**kwargs)
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        return await self.db.get(Notification, notification_id)

    async def list_for_user(self, user_id: uuid.UUID) -> list[Notification]:
        result = await self.db.execute(
            select(Notification).where(Notification.recipient_user_id == user_id).order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Notification]:
        """
        Closes a real gap: there was previously no way to see a history
        of what's been sent for an event — only a recipient's own inbox
        (list_for_user). Used by the Console's Communication page to show
        recent sends. Returns one row per RECIPIENT (a targeted send fans
        out to many rows) — the caller groups these back into logical
        "sends" by (title, body, sent_at), since there's no separate
        batch/send-id concept on this model.
        """
        result = await self.db.execute(
            select(Notification).where(Notification.event_id == event_id).order_by(Notification.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_by_ids(self, notification_ids: list[uuid.UUID]) -> list[Notification]:
        result = await self.db.execute(select(Notification).where(Notification.id.in_(notification_ids)))
        return list(result.scalars().all())


class NotificationTemplateRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> NotificationTemplate:
        template = NotificationTemplate(**kwargs)
        self.db.add(template)
        await self.db.flush()
        return template

    async def list_all(self) -> list[NotificationTemplate]:
        result = await self.db.execute(select(NotificationTemplate).order_by(NotificationTemplate.code))
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> NotificationTemplate | None:
        result = await self.db.execute(
            select(NotificationTemplate).where(NotificationTemplate.code == code)
        )
        return result.scalar_one_or_none()