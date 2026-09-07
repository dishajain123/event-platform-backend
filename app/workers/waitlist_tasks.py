import asyncio

from app.core.background_jobs import celery_app
from app.database import AsyncSessionLocal
from app.modules.waitlists.service import WaitlistService


@celery_app.task(name="waitlists.expire_promotions")
def expire_waitlist_promotions() -> int:
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            return await WaitlistService(db).expire_and_promote()

    return asyncio.run(_run())
