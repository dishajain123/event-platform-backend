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


@celery_app.task(
    name="payments.reconcile_stale_payments",
    autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3},
)
def reconcile_stale_payments() -> int:
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            return await PaymentService(db).reconcile_stale_payments_once()

    return asyncio.run(_run())


@celery_app.task(
    name="payments.reconcile_stale_refunds",
    autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3},
)
def reconcile_stale_refunds() -> int:
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            return await PaymentService(db).reconcile_stale_refunds_once()

    return asyncio.run(_run())


@celery_app.task(
    name="payments.retry_failed_webhooks",
    autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3},
)
def retry_failed_webhooks() -> int:
    async def _run() -> int:
        async with AsyncSessionLocal() as db:
            return await PaymentService(db).retry_failed_webhooks_once()

    return asyncio.run(_run())
