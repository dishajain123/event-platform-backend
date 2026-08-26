"""
Celery tasks for payment reconciliation and refund follow-up.
"""
import asyncio

from app.core.background_jobs import celery_app
from app.database import AsyncSessionLocal
from app.modules.payments.service import PaymentService


@celery_app.task(name="payments.reconcile_payment")
def reconcile_payment(gateway_order_id: str, gateway_payment_id: str, gateway_signature: str) -> str:
    async def _run() -> str:
        async with AsyncSessionLocal() as db:
            await PaymentService(db).handle_webhook(
                gateway_order_id, gateway_payment_id, gateway_signature
            )
        return "ok"

    return asyncio.run(_run())
