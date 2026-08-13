"""Per-tenant rate limiting, keyed on the verified app_id (T283279748)."""

import hashlib
import hmac
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    from bazaar_api.db.session import dispose_engine

    await dispose_engine()
    redis = get_redis()
    for pattern in ("nonce:*", "idem:*", "rl:*"):
        async for key in redis.scan_iter(pattern):
            await redis.delete(key)
    yield
    await close_redis()


def _headers(path: str) -> dict[str, str]:
    ts = str(int(time.time()))
    sig = hmac.new(
        SECRET.encode(), canonical_request("GET", path, "", ts, b""), hashlib.sha256
    ).hexdigest()
    return {"X-Bazaar-Key": KEY_ID, "X-Bazaar-Timestamp": ts, "X-Bazaar-Signature": sig}


async def test_over_limit_returns_429_with_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)
    # Distinct paths per request: identical method+path+query+body+timestamp
    # would produce identical signatures and trip the auth nonce as a replay.
    # Paths must be UNIMPLEMENTED surface (catch-all 501): a routed handler
    # that validates input (e.g. GET /v1/reviews requires subject_user_id)
    # would 422 before reaching the stub's 501.
    paths = ["/v1/offers", "/v1/offers/abc", "/v1/messages", "/v1/messages/xyz"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = [await client.get(p, headers=_headers(p)) for p in paths]
    assert [r.status_code for r in responses[:3]] == [501, 501, 501]
    over = responses[3]
    assert over.status_code == 429
    err = over.json()["error"]
    assert err["code"] == "rate_limited"
    assert err["request_id"] == over.headers["x-request-id"]


async def test_unauthenticated_requests_are_not_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The limiter is keyed on the VERIFIED app_id, so it runs after auth.
    # Unauthenticated requests 401 cheaply — they never reach the limiter.
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/v1/listings")
        second = await client.get("/v1/reviews")
    assert first.status_code == 401
    assert second.status_code == 401
