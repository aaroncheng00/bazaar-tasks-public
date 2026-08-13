from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from bazaar_api.db.redis import close_redis
from bazaar_api.db.session import dispose_engine
from bazaar_api.main import app


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    # Dispose pooled asyncpg connections from prior tests' event loops — the
    # shared engine otherwise hands a connection bound to a closed loop.
    await dispose_engine()
    yield
    await close_redis()


async def test_healthz() -> None:
    # No X-Bazaar-* headers: the probe is outside /v1 and auth-exempt by design.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "redis": "ok"}
