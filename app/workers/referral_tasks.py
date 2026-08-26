"""
Celery tasks for referral qualification evaluation.
"""
import asyncio
from uuid import UUID

from app.core.background_jobs import celery_app
from app.database import AsyncSessionLocal
from app.modules.referrals.service import ReferralService


@celery_app.task(name="referrals.evaluate_referral_qualification")
def evaluate_referral_qualification(registration_id: str) -> str:
    async def _run() -> str:
        async with AsyncSessionLocal() as db:
            await ReferralService(db).evaluate_referral_qualification(UUID(registration_id))
        return "ok"

    return asyncio.run(_run())
