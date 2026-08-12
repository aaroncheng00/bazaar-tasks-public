"""Pin the /v1 pipeline contract: fail-closed auth + tenant session on the
whole tree, and the frozen middleware order."""

import hashlib
import hmac
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.db.session import dispose_engine
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"


@pytest.fixture(autouse=True)
def _reset_dev_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})
    monkeypatch.setattr(settings, "dev_skip_hmac", False)
    monkeypatch.setattr(settings, "env", "dev")


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    # Dispose pooled asyncpg connections from prior tests' event loops — the
    # shared engine otherwise hands a connection bound to a closed loop.
    await dispose_engine()
    # Clear nonce entries between tests so a signature used in one test isn't
    # seen as a replay in the next.
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(),
        canonical_request(method, path, query, timestamp, body),
        hashlib.sha256,
    ).hexdigest()


def _headers(method: str, path: str, query: str = "", key_id: str = KEY_ID) -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        "X-Bazaar-Key": key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": _sign(method, path, query, ts, b""),
    }


async def test_v1_is_fail_closed_without_auth() -> None:
    # No X-Bazaar-* headers → rejected before any handler, even on an
    # unimplemented path.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings")
    assert response.status_code == 401


async def test_v1_auth_runs_before_routing() -> None:
    # Unknown key on an unimplemented /v1 path → 401 (auth precedes routing).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/does-not-exist",
            headers={
                "X-Bazaar-Key": "bzk_unknown",
                "X-Bazaar-Timestamp": "0",
                "X-Bazaar-Signature": "0",
            },
        )
    assert response.status_code == 401


async def test_authenticated_reaches_unimplemented_surface() -> None:
    # Validly signed request to unimplemented /v1 surface → authenticated,
    # tenant-scoped, and routed to the 501 catch-all (not a bare 404).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings", headers=_headers("GET", "/v1/listings"))
    assert response.status_code == 501


async def test_dev_skip_hmac_bypasses_signature_but_not_tenancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Flag on + env=dev → no signature/timestamp needed for a known key.
    monkeypatch.setattr(settings, "dev_skip_hmac", True)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings", headers={"X-Bazaar-Key": KEY_ID})
    assert response.status_code == 501


async def test_dev_skip_hmac_ignored_outside_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    # The flag must be inert in any other env — fail-closed still applies.
    monkeypatch.setattr(settings, "dev_skip_hmac", True)
    monkeypatch.setattr(settings, "env", "prod")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings", headers={"X-Bazaar-Key": KEY_ID})
    assert response.status_code == 401


def test_dev_skip_hmac_outside_dev_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    # Boot-time guard: the flag must be impossible to enable outside dev.
    monkeypatch.setattr(settings, "dev_skip_hmac", True)
    monkeypatch.setattr(settings, "env", "prod")
    from bazaar_api.main import validate_dev_flags

    with pytest.raises(RuntimeError, match="refusing to boot"):
        validate_dev_flags()


def test_middleware_order_is_frozen() -> None:
    # RequestId must be outermost so even a 401/429 carries a request id.
    # Assert against the BUILT stack (outermost first), not user_middleware
    # storage — the two are in opposite orders and confusing them is what
    # caused the original inversion bug.
    built = app.build_middleware_stack()
    names = []
    node = built
    while hasattr(node, "app"):
        names.append(type(node).__name__)
        node = node.app
    assert names.index("RequestIdMiddleware") < names.index("RateLimitMiddleware")


def test_healthz_not_under_v1() -> None:
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/healthz" in paths
    assert "/v1/healthz" not in paths
    assert "/health" not in paths
