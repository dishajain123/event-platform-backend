"""SMS provider adapter used by identity, staff, and notifications.

The adapter is intentionally generic: if an SMS HTTP endpoint is
configured, messages are sent there with the API key and sender ID from
settings. If no endpoint is configured, we fall back to logging so local
development and tests keep working without external credentials.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("sms_provider")


def _settings():
    return get_settings()


async def _send_sms(mobile_number: str, body: str, *, purpose: str) -> str:
    settings = _settings()
    payload: dict[str, Any] = {
        "to": mobile_number,
        "message": body,
        "sender_id": settings.sms_provider_sender_id,
        "purpose": purpose,
    }

    if not settings.sms_provider_api_url:
        logger.info("SMS disabled; would send to %s: %s", mobile_number, body)
        return f"sms:{mobile_number}"

    headers = {"Content-Type": "application/json"}
    if settings.sms_provider_api_key:
        headers["Authorization"] = f"Bearer {settings.sms_provider_api_key}"

    timeout = httpx.Timeout(settings.sms_provider_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(settings.sms_provider_api_url, json=payload, headers=headers)
        response.raise_for_status()

    message_id = None
    try:
        data = response.json()
    except ValueError:
        data = None

    if isinstance(data, dict):
        message_id = (
            data.get("message_id")
            or data.get("id")
            or data.get("sms_id")
            or data.get("data", {}).get("message_id")
            if isinstance(data.get("data"), dict)
            else None
        )
    if message_id is None:
        message_id = response.text.strip() or f"sms:{mobile_number}"
    return str(message_id)


async def send_otp_sms(mobile_number: str, otp: str) -> str:
    return await _send_sms(
        mobile_number,
        f"Your OTP for Event Platform is {otp}. It expires in a few minutes.",
        purpose="otp",
    )


async def send_staff_invite_sms(mobile_number: str, role_label: str) -> str:
    return await _send_sms(
        mobile_number,
        f"You've been added as {role_label}. Download the app to get started.",
        purpose="staff_invite",
    )


async def send_notification_sms(mobile_number: str, body: str) -> str:
    return await _send_sms(mobile_number, body, purpose="notification")
