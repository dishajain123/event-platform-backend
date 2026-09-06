"""
Celery app instance, shared by every module's workers/*.py file.
No tasks are registered yet in Phase 1 — this exists so Phase 4/5/6/8
can add task modules without touching this file.
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
    },
)
