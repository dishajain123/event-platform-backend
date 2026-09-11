from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import discovery_updates as updates


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path,status,expected", [
    ("POST", "/event-categories/main", 201, True),
    ("PATCH", "/event-categories/sub/id", 200, True),
    ("DELETE", "/event-categories/main/id", 204, True),
    ("PATCH", "/events/id", 200, True),
    ("POST", "/events/id/publish", 200, True),
    ("POST", "/users/id/event-manager", 200, True),
    ("PATCH", "/users/id/status", 200, True),
    ("POST", "/users/id/role-assignments", 200, True),
    ("GET", "/events", 200, False),
    ("PATCH", "/events/id", 403, False),
    ("DELETE", "/event-categories/main/id", 409, False),
    ("POST", "/auth/login", 200, False),
])
async def test_only_successful_discovery_writes_notify(monkeypatch, method, path, status, expected):
    redis = MagicMock(publish=AsyncMock())
    monkeypatch.setattr(updates, "get_redis", lambda: redis)
    await updates.notify_discovery_change(method, updates.get_settings().api_v1_prefix + path, status)
    assert redis.publish.await_count == int(expected)


@pytest.mark.asyncio
async def test_notification_outage_does_not_fail_committed_save(monkeypatch):
    redis = MagicMock(publish=AsyncMock(side_effect=ConnectionError("offline")))
    monkeypatch.setattr(updates, "get_redis", lambda: redis)
    await updates.notify_discovery_change("PATCH", updates.get_settings().api_v1_prefix + "/events/id", 200)


@pytest.mark.asyncio
async def test_stream_sends_initial_refresh_and_changes_and_closes():
    subscription = MagicMock()
    subscription.subscribe = AsyncMock()
    subscription.get_message = AsyncMock(return_value={"type": "message", "data": "changed"})
    subscription.__aenter__ = AsyncMock(return_value=subscription)
    subscription.__aexit__ = AsyncMock()
    redis = MagicMock(pubsub=MagicMock(return_value=subscription))
    stream = updates.discovery_events(redis)
    assert "event: changed" in await anext(stream)
    subscription.subscribe.assert_awaited_once_with(updates.CHANNEL)
    assert "event: changed" in await anext(stream)
    subscription.get_message.return_value = None
    assert "heartbeat" in await anext(stream)
    await stream.aclose()
    subscription.__aexit__.assert_awaited_once()
