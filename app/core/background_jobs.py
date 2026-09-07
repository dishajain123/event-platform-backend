"""
Celery app instance, shared by every module's workers/*.py file.
    Notification delivery and automated reminder tasks share this one Celery
    application so workers and Beat use the same registration/configuration.
"""
from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "event_platform",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    broker_connection_max_retries=10,
    task_time_limit=300,
    task_soft_time_limit=240,
    include=[
        "app.workers.notification_tasks",
        "app.workers.payment_tasks",
        "app.workers.referral_tasks",
        "app.workers.ticket_tasks",
        "app.workers.registration_tasks",
    ],
    beat_schedule={
        "registrations.synchronize_registration_states": {
            "task": "registrations.synchronize_registration_states",
            "schedule": 60.0,
        },
        "notifications.run_automated_notifications": {
            "task": "notifications.run_automated_notifications",
            "schedule": 60.0,
        },
        "payments.reconcile_stale_payments": {
            "task": "payments.reconcile_stale_payments",
            "schedule": 300.0,
        },
        "payments.reconcile_stale_refunds": {
            "task": "payments.reconcile_stale_refunds",
            "schedule": 300.0,
        },
        "payments.retry_failed_webhooks": {
            "task": "payments.retry_failed_webhooks",
            "schedule": 300.0,
        },
    },
)
