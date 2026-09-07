"""Data access for notifications."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import (
    DeviceToken,
    Notification,
    NotificationPreference,
    NotificationTemplate,
)


class NotificationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Notification:
        dedupe_key = kwargs.get("dedupe_key")
        if dedupe_key:
            existing = await self.get_by_dedupe_key(dedupe_key)
            if existing is not None:
                return existing
        notification = Notification(**kwargs)
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def get_by_id(self, notification_id: uuid.UUID) -> Notification | None:
        return await self.db.get(Notification, notification_id)

    async def get_by_dedupe_key(self, dedupe_key: str) -> Notification | None:
        result = await self.db.execute(
            select(Notification).where(Notification.dedupe_key == dedupe_key)
        )
        return result.scalar_one_or_none()

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

    async def page_for_event(self, event_id: uuid.UUID, *, page: int, page_size: int):
        filters = [Notification.event_id == event_id]
        total = await self.db.scalar(select(func.count(Notification.id)).where(*filters)) or 0
        result = await self.db.execute(
            select(Notification).where(*filters)
            .order_by(Notification.created_at.desc(), Notification.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total

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


class DeviceTokenRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_token(self, token: str) -> DeviceToken | None:
        result = await self.db.execute(select(DeviceToken).where(DeviceToken.token == token))
        return result.scalar_one_or_none()

    async def get_active_for_user(self, user_id: uuid.UUID) -> list[DeviceToken]:
        result = await self.db.execute(
            select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_by_id(self, token_id: uuid.UUID) -> DeviceToken | None:
        return await self.db.get(DeviceToken, token_id)


class NotificationPreferenceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_for_user(self, user_id: uuid.UUID) -> NotificationPreference | None:
        result = await self.db.execute(
            select(NotificationPreference).where(NotificationPreference.user_id == user_id)
        )
        return result.scalar_one_or_none()
