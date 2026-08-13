"""The error envelope: {error: {code, message, request_id}} on every failure."""

import hashlib
import hmac
import time
from collections.abc import AsyncIterator, Iterator, Sequence

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


def _headers(method: str, path: str, body: bytes = b"", ts_offset: int = 0) -> dict[str, str]:
    ts = str(int(time.time()) + ts_offset)
    sig = hmac.new(
        SECRET.encode(), canonical_request(method, path, "", ts, body), hashlib.sha256
    ).hexdigest()
    return {"X-Bazaar-Key": KEY_ID, "X-Bazaar-Timestamp": ts, "X-Bazaar-Signature": sig}


# A route that raises a bare exception, to exercise the 500 path. Registered on
# the shared app at import; inert unless hit, and only ever imported by tests.
@app.get("/__boom")
async def _boom() -> None:
    raise RuntimeError("boom")


@pytest.fixture(scope="module", autouse=True)
def _deregister_boom_route() -> Iterator[None]:
    yield
    # The crash route is this file's alone; leaving it registered leaks it
    # into later modules' view of the shared app — the drift guard's
    # current-tree tests enumerate app.routes and would flag it as unspec'd.
    app.routes[:] = [r for r in app.routes if getattr(r, "path", None) != "/__boom"]
    app.openapi_schema = None  # bust the cached schema so the removal shows


def _assert_envelope(body: dict[str, object], code: str) -> None:
    err = body["error"]
    assert isinstance(err, dict)
    assert err["code"] == code
    assert isinstance(err["message"], str) and err["message"]
    assert isinstance(err["request_id"], str) and err["request_id"].startswith("req_")


async def test_401_has_envelope_and_request_id_header() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings")
    assert response.status_code == 401
    _assert_envelope(response.json(), "missing_auth_headers")
    # The envelope's request_id must be the one on the response header.
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


async def test_404_outside_v1_has_envelope() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/nope")
    assert response.status_code == 404
    _assert_envelope(response.json(), "not_found")


async def test_501_catch_all_has_envelope() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/v1/listings", headers=_headers("GET", "/v1/listings"))
    assert response.status_code == 501
    _assert_envelope(response.json(), "not_implemented")


async def test_400_validation_error_has_envelope() -> None:
    # Signed POST with a body that fails validation (missing required field).
    # 400, not FastAPI's default 422 — the API never returns 422 (Error Code
    # Registry, Aug 5).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/smoke/echo",
            content=b"{}",
            headers={**_headers("POST", "/smoke/echo", b"{}"), "Content-Type": "application/json"},
        )
    assert response.status_code == 400
    _assert_envelope(response.json(), "validation_failed")


async def test_500_bare_exception_has_envelope_and_header() -> None:
    # The bare-Exception path is emitted by RequestIdMiddleware itself (a
    # registered handler would lose the ContextVar and the header — probe-
    # verified). Both the body request_id and the header must be present.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/__boom")
    assert response.status_code == 500
    _assert_envelope(response.json(), "internal_error")
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


async def test_429_envelope_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    # Rate-limit rejection must also be enveloped (dependency-raised, so it
    # carries request_id AND tenant context).
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    paths = ["/v1/listings", "/v1/reviews"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(paths[0], headers=_headers("GET", paths[0]))
        second = await client.get(paths[1], headers=_headers("GET", paths[1]))
    assert first.status_code == 501
    assert second.status_code == 429
    _assert_envelope(second.json(), "rate_limited")


async def test_429_carries_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fixed window: the correct wait is to the next boundary, and the client
    # must not have to guess it.
    monkeypatch.setattr(settings, "rate_limit_per_minute", 1)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/v1/listings", headers=_headers("GET", "/v1/listings"))
        over = await client.get("/v1/reviews", headers=_headers("GET", "/v1/reviews"))
    assert over.status_code == 429
    retry_after = int(over.headers["retry-after"])
    assert 1 <= retry_after <= 60


# --- Contract: every auth rejection carries its OWN stable code ---------------
# The code is the public contract integrators branch on. These pin each auth
# failure path to its code, so a refactor can't silently degrade them to a
# status fallback.


async def test_auth_rejection_codes() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # missing all headers
        r = await client.get("/smoke/docs")
        assert r.json()["error"]["code"] == "missing_auth_headers"

        # unknown key
        ts = str(int(time.time()))
        sig = hmac.new(
            SECRET.encode(), canonical_request("GET", "/smoke/docs", "", ts, b""), hashlib.sha256
        ).hexdigest()
        r = await client.get(
            "/smoke/docs",
            headers={
                "X-Bazaar-Key": "bzk_nope",
                "X-Bazaar-Timestamp": ts,
                "X-Bazaar-Signature": sig,
            },
        )
        assert r.json()["error"]["code"] == "unknown_key"

        # known key, missing signature/timestamp
        r = await client.get("/smoke/docs", headers={"X-Bazaar-Key": KEY_ID})
        assert r.json()["error"]["code"] == "missing_auth_headers"

        # malformed timestamp
        r = await client.get(
            "/smoke/docs",
            headers={
                "X-Bazaar-Key": KEY_ID,
                "X-Bazaar-Timestamp": "abc",
                "X-Bazaar-Signature": sig,
            },
        )
        assert r.json()["error"]["code"] == "malformed_timestamp"

        # stale timestamp
        stale = str(int(time.time()) - 400)
        stale_sig = hmac.new(
            SECRET.encode(),
            canonical_request("GET", "/smoke/docs", "", stale, b""),
            hashlib.sha256,
        ).hexdigest()
        r = await client.get(
            "/smoke/docs",
            headers={
                "X-Bazaar-Key": KEY_ID,
                "X-Bazaar-Timestamp": stale,
                "X-Bazaar-Signature": stale_sig,
            },
        )
        assert r.json()["error"]["code"] == "stale_timestamp"

        # bad signature
        r = await client.get(
            "/smoke/docs",
            headers={**_headers("GET", "/smoke/docs"), "X-Bazaar-Signature": "0" * 64},
        )
        assert r.json()["error"]["code"] == "invalid_signature"

        # replay: same signed request twice
        headers = _headers("GET", "/smoke/docs")
        first = await client.get("/smoke/docs", headers=headers)
        assert first.status_code == 200
        second = await client.get("/smoke/docs", headers=headers)
        assert second.json()["error"]["code"] == "replay_detected"


def test_every_routed_route_uses_idempotent_route() -> None:
    # Enforcement for the silent failure: a module router WITHOUT
    # route_class=IdempotentRoute still gets the guard dependency (router
    # dependencies propagate) but NOT the post-handler storage — the marker is
    # claimed, never stored, never freed, and every retry 409s for 300s then
    # re-executes non-idempotently. Walk the real route tree so a future
    # router that forgets fails loudly here.
    from fastapi.routing import APIRoute

    from bazaar_api.middleware.idempotency import IdempotentRoute

    def walk(routes: Sequence[object]) -> None:
        for r in routes:
            included = getattr(r, "original_router", None)
            if included is not None:
                # The router itself must carry the class for its FUTURE routes.
                assert getattr(included, "route_class", None) is IdempotentRoute, (
                    f"{getattr(included, 'prefix', '?')} router missing route_class=IdempotentRoute"
                )
                walk(included.routes)
            elif isinstance(r, APIRoute) and r.path not in ("/healthz", "/__boom"):
                # /healthz is auth-exempt and reads nothing tenant-scoped;
                # /__boom is this file's test-only crash route.
                assert isinstance(r, IdempotentRoute), f"{r.path} is not IdempotentRoute"

    walk(app.routes)
