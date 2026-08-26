"""
Push notification adapter used by notifications.
"""
import logging

logger = logging.getLogger("push_notifications")


async def send_push_notification(recipient_user_id: str, title: str, body: str) -> str:
    logger.info("STUB PUSH to %s: %s", recipient_user_id, title)
    return f"push:{recipient_user_id}"
