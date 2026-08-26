"""
SQLAlchemy async engine + session factory.

Every module's repository.py imports `get_db` from here via FastAPI's
dependency system — there is exactly one place that knows how to talk
to Postgres.
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — yields one session per request, always closed after."""
    async with AsyncSessionLocal() as session:
        yield session