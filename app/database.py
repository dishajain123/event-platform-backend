"""
SQLAlchemy async engine + session factory.

Every module's repository.py imports `get_db` from here via FastAPI's
dependency system — there is exactly one place that knows how to talk
to Postgres.
"""
from collections.abc import AsyncGenerator
import logging

from sqlalchemy.exc import DBAPIError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

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
    try:
        async with AsyncSessionLocal() as session:
            yield session
    except (ConnectionRefusedError, ConnectionResetError) as exc:
        logger.warning("Database connection unavailable; check PostgreSQL and DATABASE_URL")
        raise ServiceUnavailableError("Database temporarily unavailable. Please try again shortly.") from exc
    except DBAPIError as exc:
        if not exc.connection_invalidated:
            raise
        logger.warning("Database connection lost; retry after PostgreSQL recovers")
        raise ServiceUnavailableError("Database temporarily unavailable. Please try again shortly.") from exc
