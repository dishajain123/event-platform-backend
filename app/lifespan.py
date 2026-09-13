"""Verify database availability before accepting requests, including direct Uvicorn starts."""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        try:
            async with asyncio.timeout(10):
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
        except Exception:
            # Do not expose credentials or driver connection parameters in startup errors.
            raise RuntimeError(
                "PostgreSQL is unavailable. For local development run "
                "'bash scripts/start-local.sh' to start Docker and the database. "
                "Otherwise check PostgreSQL and DATABASE_URL before restarting the API."
            ) from None
        yield
    finally:
        await engine.dispose()
