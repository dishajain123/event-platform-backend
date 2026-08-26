"""
Email provider adapter used by notifications.

Phase 6 ships a stub implementation so the notification flow can be
tested end-to-end without a third-party email account. Later phases
can replace this function with a real provider integration.
"""
import logging

logger = logging.getLogger("email_provider")


async def send_notification_email(recipient_email: str, subject: str, body: str) -> str:
    logger.info("STUB EMAIL to %s: %s", recipient_email, subject)
    return f"email:{recipient_email}"
