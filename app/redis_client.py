"""
Shared Redis connection pool.

Used for: OTP storage (short-lived, hashed codes), resend/rate-limit
counters, idempotency keys, and — from later phases — live vote/ticket
counters and Celery's broker.
"""
from redis.asyncio import ConnectionPool, Redis

from app.config import get_settings

settings = get_settings()

_pool = ConnectionPool.from_url(settings.redis_url, decode_responses=True)


def get_redis() -> Redis:
    """FastAPI dependency — returns a Redis client backed by the shared pool."""
    return Redis(connection_pool=_pool)