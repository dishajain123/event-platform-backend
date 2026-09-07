"""Provider interfaces for push and email delivery.

The application owns notification state and retries. Providers only deliver one
message and return a provider id, which keeps external vendor details out of
the notification module and makes development deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings, get_settings


class NotificationProviderError(RuntimeError):
    def __init__(self, message: str, *, invalid_recipient: bool = False):
        super().__init__(message)
        self.invalid_recipient = invalid_recipient


class PushProvider(Protocol):
    async def send(self, *, token: str, title: str, body: str, data: dict) -> str: ...


class EmailProvider(Protocol):
    async def send(self, *, recipient: str, subject: str, body: str) -> str: ...


@dataclass
class DevelopmentPushProvider:
    async def send(self, *, token: str, title: str, body: str, data: dict) -> str:
        return f"dev-push:{token[:12]}"


@dataclass
class DevelopmentEmailProvider:
    async def send(self, *, recipient: str, subject: str, body: str) -> str:
        return f"dev-email:{recipient}"


class HttpPushProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send(self, *, token: str, title: str, body: str, data: dict) -> str:
        if not self.settings.notification_push_api_url:
            raise NotificationProviderError("Push provider URL is not configured.")
        headers = {"Content-Type": "application/json"}
        if self.settings.notification_push_api_key:
            headers["Authorization"] = f"Bearer {self.settings.notification_push_api_key}"
        payload = {"token": token, "title": title, "body": body, "data": data}
        try:
            async with httpx.AsyncClient(timeout=self.settings.notification_provider_timeout_seconds) as client:
                response = await client.post(self.settings.notification_push_api_url, json=payload, headers=headers)
                if response.status_code in {400, 404, 410}:
                    raise NotificationProviderError("Push token was rejected.", invalid_recipient=True)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationProviderError(str(exc)) from exc
        try:
            result = response.json()
        except ValueError:
            result = None
        if isinstance(result, dict):
            message_id = result.get("message_id") or result.get("id")
            if message_id:
                return str(message_id)
        return response.text.strip() or f"push:{token[:12]}"


class HttpEmailProvider:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def send(self, *, recipient: str, subject: str, body: str) -> str:
        if not self.settings.notification_email_api_url:
            raise NotificationProviderError("Email provider URL is not configured.")
        headers = {"Content-Type": "application/json"}
        if self.settings.notification_email_api_key:
            headers["Authorization"] = f"Bearer {self.settings.notification_email_api_key}"
        payload = {
            "from": self.settings.notification_email_from,
            "to": recipient,
            "subject": subject,
            "body": body,
        }
        try:
            async with httpx.AsyncClient(timeout=self.settings.notification_provider_timeout_seconds) as client:
                response = await client.post(self.settings.notification_email_api_url, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise NotificationProviderError(str(exc)) from exc
        try:
            result = response.json()
        except ValueError:
            result = None
        if isinstance(result, dict):
            message_id = result.get("message_id") or result.get("id")
            if message_id:
                return str(message_id)
        return response.text.strip() or f"email:{recipient}"


def get_push_provider(settings: Settings | None = None) -> PushProvider:
    settings = settings or get_settings()
    if settings.notification_push_provider == "http":
        return HttpPushProvider(settings)
    return DevelopmentPushProvider()


def get_email_provider(settings: Settings | None = None) -> EmailProvider:
    settings = settings or get_settings()
    if settings.notification_email_provider == "http":
        return HttpEmailProvider(settings)
    return DevelopmentEmailProvider()
