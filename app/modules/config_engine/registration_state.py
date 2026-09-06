"""Shared registration capacity/deadline state calculation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum

from app.modules.events.models import EventStatus


class RegistrationAvailability(StrEnum):
    OPEN = "open"
    LIMITED = "limited"
    FULL = "full"
    CLOSED = "closed"


def parse_registration_end_at(details: dict | None) -> datetime | None:
    raw_value = (details or {}).get("registration_end_at")
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        parsed = raw_value
    else:
        try:
            parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def calculate_registration_availability(
    *,
    event_status: EventStatus,
    capacity: int | None,
    registered_count: int,
    registration_end_at: datetime | None,
    now: datetime | None = None,
) -> RegistrationAvailability:
    """Return the one server-owned registration state used by all clients."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    if event_status != EventStatus.REGISTRATION_OPEN:
        return RegistrationAvailability.CLOSED
    if registration_end_at is not None and current_time >= registration_end_at:
        return RegistrationAvailability.CLOSED
    if capacity is not None and registered_count >= capacity:
        return RegistrationAvailability.FULL
    if capacity is not None and capacity > 0 and registered_count / capacity >= 0.8:
        return RegistrationAvailability.LIMITED
    return RegistrationAvailability.OPEN
