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


async def send_verification_email(recipient_email: str, code: str) -> str:
    """Send the account verification code through the configured email adapter."""
    return await send_notification_email(
        recipient_email,
        "Your Event Platform verification code",
        f"Your verification code is {code}. It expires in a few minutes.",
    )


async def send_password_reset_email(recipient_email: str, code: str) -> str:
    return await send_notification_email(
        recipient_email,
        "Reset your Event Platform password",
        f"Your password reset code is {code}. It expires in a few minutes.",
    )
