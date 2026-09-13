"""Check the configured services, not just the default Docker port mappings."""
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.database import engine
from app.redis_client import get_redis


async def check_dependencies():
    # SQL echo is useful during development but unnecessary for this probe.
    engine.echo = False
    target = make_url(str(engine.url))
    try:
        async with asyncio.timeout(10):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
    except Exception:
        raise SystemExit(
            f"PostgreSQL unavailable at {target.host}:{target.port or 5432}. "
            "Check DATABASE_URL. Host Python with this Compose stack uses localhost:5433; "
            "container Python uses postgres:5432."
        ) from None
    finally:
        await engine.dispose()
    redis = get_redis()
    try:
        async with asyncio.timeout(10):
            await redis.ping()
    except Exception:
        raise SystemExit("Redis unavailable. Check Docker and REDIS_URL.") from None
    finally:
        await redis.aclose()
        await redis.connection_pool.disconnect()
    print("PostgreSQL and Redis are ready.")


if __name__ == "__main__":
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    asyncio.run(check_dependencies())
