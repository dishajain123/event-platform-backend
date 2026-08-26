"""
Celery tasks for notification fan-out.
"""
import asyncio
from uuid import UUID

from app.core.background_jobs import celery_app
from app.database import AsyncSessionLocal
from app.modules.notifications.service import NotificationService


async def execute_locally(notification_ids: list[UUID]) -> list[str]:
    sent: list[str] = []
    async with AsyncSessionLocal() as db:
        service = NotificationService(db)
        for notification_id in notification_ids:
            notification = await service.deliver_notification(notification_id)
            sent.append(str(notification.id))
    return sent


@celery_app.task(name="notifications.deliver_notification_batch")
def deliver_notification_batch(notification_ids: list[str]) -> list[str]:
    async def _run() -> list[str]:
        return await execute_locally([UUID(notification_id) for notification_id in notification_ids])

    return asyncio.run(_run())
