"""
Postgres advisory-lock helper for serializing "check a limit, then act"
operations against concurrent requests — e.g. checking an event hasn't
hit capacity, then creating a registration. A plain SELECT COUNT()
followed later by an INSERT has a race window: two requests arriving
at the same instant can both pass the COUNT check before either has
inserted, together exceeding the limit.

pg_advisory_xact_lock is scoped to the current transaction and releases
automatically on commit or rollback — no explicit unlock call, no new
table, no schema change. Concurrent callers for the SAME key block and
queue; callers for different keys never contend with each other, so
locking one event's capacity check never slows down registrations for
any other event.
"""
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_advisory_lock(db: AsyncSession, key: str) -> None:
    """
    Blocks until an exclusive, transaction-scoped advisory lock for
    `key` is acquired. No-ops outside PostgreSQL (e.g. the SQLite engine
    used by the test suite) — advisory locks are Postgres-specific, and
    the test suite runs sequentially, so the race this guards against
    can't occur there regardless.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": key})


async def acquire_event_capacity_lock(db: AsyncSession, event_id: uuid.UUID) -> None:
    """Convenience wrapper for the specific, recurring case of
    serializing registration-capacity checks per event."""
    await acquire_advisory_lock(db, f"registration_capacity:{event_id}")