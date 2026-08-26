"""
Idempotency-key helper for POST endpoints where a retried request must
never create a duplicate side effect (registrations, payments). Not
yet wired into any router — Phase 3/4 endpoints will depend on this —
but it's part of core infra from Phase 1 so nothing has to be
restructured to add it later.
"""
import json
from typing import Any

from redis.asyncio import Redis

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


async def get_cached_response(redis: Redis, idempotency_key: str) -> dict[str, Any] | None:
    cached = await redis.get(f"idempotency:{idempotency_key}")
    return json.loads(cached) if cached else None


async def cache_response(redis: Redis, idempotency_key: str, response_body: dict[str, Any]) -> None:
    await redis.set(
        f"idempotency:{idempotency_key}", json.dumps(response_body), ex=IDEMPOTENCY_TTL_SECONDS
    )