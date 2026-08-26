"""
SMS provider adapter — isolated behind this one file so swapping providers
(MSG91, Twilio, etc.) never touches business logic in modules/identity or
modules/staff.

Phase 1 ships a stub that logs instead of sending — replace send_otp_sms's
body with a real provider call in Phase 6 (Communication), and nothing
calling this function needs to change.
"""
import logging

logger = logging.getLogger("sms_provider")


async def send_otp_sms(mobile_number: str, otp: str) -> None:
    # TODO (Phase 6): replace with a real provider call, e.g.:
    #   await httpx.AsyncClient().post(PROVIDER_URL, json={...})
    logger.info("STUB SMS to %s: your OTP is %s", mobile_number, otp)


async def send_staff_invite_sms(mobile_number: str, role_label: str) -> None:
    # TODO (Phase 5): real provider call for staff account invitations.
    logger.info("STUB SMS to %s: you've been added as %s. Download the app to get started.",
                mobile_number, role_label)


async def send_notification_sms(mobile_number: str, body: str) -> str:
    logger.info("STUB SMS to %s: %s", mobile_number, body)
    return f"sms:{mobile_number}"
