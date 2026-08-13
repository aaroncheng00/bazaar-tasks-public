"""K3 patch security tests — idempotency validation, keys leak, review no-leak, request_id."""

import hashlib
import hmac
import time
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.db.session import dispose_engine
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"


@pytest.fixture(autouse=True)
def _keys_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})
    monkeypatch.setattr(settings, "dev_skip_hmac", False)
    monkeypatch.setattr(settings, "env", "dev")


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncGenerator[None, None]:
    await dispose_engine()
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("idem:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("rl:*"):
        await redis.delete(key)
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(text("DELETE FROM api_keys"))
        await conn.execute(text("DELETE FROM reviews"))
        await conn.execute(text("DELETE FROM listings"))
    await owner.dispose()
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(), canonical_request(method, path, query, timestamp, body), hashlib.sha256
    ).hexdigest()


def _headers(method: str, path: str, query: str = "", body: bytes = b"") -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": _sign(method, path, query, ts, body),
    }


@pytest.mark.asyncio
async def test_idempotency_key_too_long_rejected() -> None:
    path = f"/v1/apps/{APP_ID}/keys"
    long_key = "a" * 65
    ts = str(int(time.time()))
    sig = _sign("POST", path, "", ts, b"")
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Idempotency-Key": long_key,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(path, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_idempotency_key_invalid_charset_rejected() -> None:
    path = f"/v1/apps/{APP_ID}/keys"
    bad_key = "has space"
    ts = str(int(time.time()))
    sig = _sign("POST", path, "", ts, b"")
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Idempotency-Key": bad_key,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(path, headers=headers)
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_keys_list_limited_and_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    import bazaar_api.modules.keys as keys_module
    from bazaar_api.keys import mint_key

    monkeypatch.setattr(keys_module, "MAX_LIST_KEYS", 3)

    minted: list[str] = []
    for _ in range(5):
        kid, _ = await mint_key(APP_ID)
        minted.append(kid)

    path = f"/v1/apps/{APP_ID}/keys"
    headers = _headers("GET", path)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert len(data["keys"]) == 3
    assert data["keys"][0]["key_id"] == minted[-1]
    for k in data["keys"]:
        assert "secret" not in k
        assert "secret_ciphertext" not in k
        assert set(k.keys()) == {"key_id", "created_at", "revoked_at"}

    monkeypatch.setattr(keys_module, "MAX_LIST_KEYS", 100)
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.get(path, headers=_headers("GET", path))
    assert resp2.status_code == 200
    assert len(resp2.json()["keys"]) == 5


@pytest.mark.asyncio
async def test_review_no_existence_leak_uniform_403() -> None:
    """Malformed, missing, cross-tenant all map to same 403 per spec."""
    path = "/v1/reviews"
    body_cases = [
        {"listing_id": "bad-id", "author_user_id": "user-a", "rating": 5},
        {
            "listing_id": "lst_00000000-0000-0000-0000-000000000000",
            "author_user_id": "user-a",
            "rating": 5,
        },
        {
            "listing_id": "lst_ffffffff-ffff-ffff-ffff-ffffffffffff",
            "author_user_id": "user-a",
            "rating": 5,
        },
    ]
    for payload in body_cases:
        import json

        payload_bytes = json.dumps(payload).encode()
        ts = str(int(time.time()))
        sig = _sign("POST", path, "", ts, payload_bytes)
        headers = {
            "X-Bazaar-Key": KEY_ID,
            "X-Bazaar-Timestamp": ts,
            "X-Bazaar-Signature": sig,
            "Content-Type": "application/json",
        }
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(path, headers=headers, content=payload_bytes)
        assert resp.status_code == 403, f"payload {payload} got {resp.status_code}"
        assert resp.json()["error"]["code"] == "review_not_eligible"


@pytest.mark.asyncio
async def test_auth_key_id_length_validation() -> None:
    path = "/v1/apps/app-a/keys"
    long_key_id = "bzk_" + "a" * 61  # 65 total >64
    ts = str(int(time.time()))
    sig = hmac.new(
        SECRET.encode(), canonical_request("GET", path, "", ts, b""), hashlib.sha256
    ).hexdigest()
    headers = {
        "X-Bazaar-Key": long_key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path, headers=headers)
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unknown_key"


@pytest.mark.asyncio
async def test_request_id_injection_minted() -> None:
    path = "/v1/apps/app-a/keys"
    ts = str(int(time.time()))
    sig = _sign("GET", path, "", ts, b"")
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "X-Request-Id": "bad\nid",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path, headers=headers)
    assert resp.status_code == 200
    returned_id = resp.headers.get("x-request-id")
    assert returned_id is not None
    assert "\n" not in returned_id
    assert returned_id.startswith("req_")
