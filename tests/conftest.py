"""
Shared test fixtures. Uses an in-memory SQLite database via aiosqlite —
fast for unit/integration tests — and a real Redis connection (assumed
running locally; see README for how to start one for tests).

Because app/core/base_model.py uses SQLAlchemy's dialect-agnostic Uuid
type, the exact same model code is exercised here as in production
against Postgres.
"""
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core import model_registry  # noqa: F401
from app.core.base_model import Base
from app.modules.rbac.models import SCOPED_ROLES, Role, RoleName


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        # Seed all built-in roles for every test — mirrors what
        # scripts/seed_super_admin.py does in a real deployment.
        for role_name in RoleName:
            session.add(Role(name=role_name, is_scoped=role_name in SCOPED_ROLES))
        await session.commit()
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def fake_redis():
    """A minimal in-memory fake of the Redis calls identity.service actually uses,
    so OTP tests don't require a real Redis server running in CI."""

    class FakeRedis:
        def __init__(self):
            self.store: dict[str, tuple[str, float | None]] = {}

        async def get(self, key):
            return self.store.get(key, (None, None))[0]

        async def set(self, key, value, ex=None):
            self.store[key] = (value, ex)

        async def delete(self, key):
            self.store.pop(key, None)

        async def ttl(self, key):
            return self.store.get(key, (None, 30))[1] or 30

        async def incr(self, key):
            current = int(self.store.get(key, ("0", None))[0])
            self.store[key] = (str(current + 1), None)
            return current + 1

        async def expire(self, key, seconds):
            pass

    return FakeRedis()
