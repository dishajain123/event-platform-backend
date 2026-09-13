from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI

from app import lifespan as startup


@pytest.mark.asyncio
async def test_api_does_not_accept_requests_without_database(monkeypatch):
    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(
        side_effect=ConnectionRefusedError("sensitive driver details")
    )
    engine.dispose = AsyncMock()
    monkeypatch.setattr(startup, "engine", engine)
    with pytest.raises(RuntimeError, match="bash scripts/start-local.sh") as failure:
        async with startup.lifespan(FastAPI()):
            pytest.fail("Unavailable database must prevent startup")
    assert "sensitive driver details" not in str(failure.value)
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_api_starts_after_database_recovers_and_disposes_on_shutdown(monkeypatch):
    connection = AsyncMock()
    engine = MagicMock()
    engine.connect.return_value.__aenter__ = AsyncMock(return_value=connection)
    engine.connect.return_value.__aexit__ = AsyncMock(return_value=False)
    engine.dispose = AsyncMock()
    monkeypatch.setattr(startup, "engine", engine)
    async with startup.lifespan(FastAPI()):
        connection.execute.assert_awaited_once()
        engine.dispose.assert_not_awaited()
    engine.dispose.assert_awaited_once()
