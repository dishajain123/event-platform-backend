"""
Celery tasks for ticket reconciliation and offline check-in sync.
"""
import asyncio
from uuid import UUID

from app.core.background_jobs import celery_app
from app.database import AsyncSessionLocal
from app.modules.identity.models import User
from app.modules.tickets.schemas import OfflineCheckInIn
from app.modules.tickets.service import TicketService


@celery_app.task(name="tickets.sync_offline_checkins")
def sync_offline_checkins(scans: list[dict], actor_user_id: str) -> str:
    async def _run() -> str:
        async with AsyncSessionLocal() as db:
            actor = await db.get(User, UUID(actor_user_id))
            if actor is None:
                return "missing_actor"
            typed_scans = [OfflineCheckInIn.model_validate(scan) for scan in scans]
            await TicketService(db).sync_offline_checkins(actor, typed_scans)
        return "ok"

    return asyncio.run(_run())
