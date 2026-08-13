import hashlib
import hmac
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"
PATH = "/smoke/docs"


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})


@pytest.fixture(autouse=True)
async def _clean_state() -> None:
    from bazaar_api.db.session import dispose_engine

    await dispose_engine()
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL bazaar.app_id = ''"))
        await conn.execute(text("DELETE FROM docs"))
    await engine.dispose()

    # Clear nonce entries between tests so a signature used in one test isn't
    # seen as a replay in the next.
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)


@pytest.fixture(autouse=True)
async def _close_redis_after() -> AsyncIterator[None]:
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(),
        canonical_request(method, path, query, timestamp, body),
        hashlib.sha256,
    ).hexdigest()


def _headers(
    timestamp: str | None = None,
    signature: str | None = None,
    key_id: str = KEY_ID,
    query: str = "",
) -> dict[str, str]:
    ts = timestamp or str(int(time.time()))
    sig = signature if signature is not None else _sign("GET", PATH, query, ts, b"")
    return {
        "X-Bazaar-Key": key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
    }


async def test_valid_signature_reaches_endpoint() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers())
    assert response.status_code == 200
    assert response.json() == {"docs": []}


async def test_missing_headers_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH)
    assert response.status_code == 401


async def test_unknown_key_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers(key_id="bzk_unknown"))
    assert response.status_code == 401


async def test_bad_signature_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers(signature="0" * 64))
    assert response.status_code == 401


async def test_stale_timestamp_rejected() -> None:
    stale = str(int(time.time()) - 400)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=_headers(timestamp=stale))
    assert response.status_code == 401


async def test_signature_is_bound_to_path() -> None:
    ts = str(int(time.time()))
    sig_for_other_path = _sign("GET", "/v1/listings", "", ts, b"")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            PATH, headers=_headers(timestamp=ts, signature=sig_for_other_path)
        )
    assert response.status_code == 401


async def test_signature_is_bound_to_query() -> None:
    # A signature computed for one query string must not validate another —
    # the pre-fix design signed body+timestamp only and was open to this.
    ts = str(int(time.time()))
    sig_for_query_a = _sign("GET", PATH, "category=a", ts, b"")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"{PATH}?category=b",
            headers=_headers(timestamp=ts, signature=sig_for_query_a),
        )
    assert response.status_code == 401


async def test_replay_rejected() -> None:
    # The same signed request sent twice: first succeeds, the identical replay
    # (same key, timestamp, signature) must be rejected as a replay.
    headers = _headers()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get(PATH, headers=headers)
        replay = await client.get(PATH, headers=headers)
    assert first.status_code == 200
    assert replay.status_code == 401


async def test_unauthenticated_replay_attempt_cannot_fill_nonce_store() -> None:
    # A bad signature must not consume a nonce entry — otherwise an attacker
    # could pre-fill Redis to DoS a legitimate signature.
    redis = get_redis()
    bad_headers = _headers(signature="0" * 64)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(PATH, headers=bad_headers)
    assert response.status_code == 401
    keys = [k async for k in redis.scan_iter("nonce:*")]
    assert keys == []
