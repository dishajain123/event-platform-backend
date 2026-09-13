"""Database outages are temporary API failures, not successful empty responses."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import database
from app.exceptions import register_exception_handlers


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    ConnectionRefusedError(61, "Connection refused"),
    ConnectionResetError(54, "Connection reset"),
    DBAPIError(None, None, Exception("lost connection"), connection_invalidated=True),
])
async def test_outage_returns_503_and_next_request_recovers(monkeypatch, failure):
    session = AsyncMock()
    session.execute.side_effect = [failure, MagicMock()]
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=session)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: context)
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/probe")
    async def probe(db=Depends(database.get_db)):
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/probe")
        assert response.status_code == 503
        assert response.json()["error_code"] == "service_unavailable"
        assert response.headers["retry-after"] == "5"
        assert "Connection refused" not in response.text
        assert (await client.get("/probe")).status_code == 200
    assert context.__aexit__.await_count == 2


@pytest.mark.asyncio
async def test_constraint_error_is_not_disguised_as_outage(monkeypatch):
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=AsyncMock())
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: context)
    dependency = database.get_db()
    await anext(dependency)
    failure = IntegrityError(None, None, Exception("duplicate"))
    with pytest.raises(IntegrityError):
        await dependency.athrow(failure)
