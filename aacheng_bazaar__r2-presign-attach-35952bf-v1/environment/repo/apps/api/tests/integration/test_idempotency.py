"""Idempotency: keyed on Idempotency-Key, never the signature."""

import hashlib
import hmac
import time
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient, Response

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
APP_ID = "app-a"
PATH = "/smoke/echo"
BODY = b'{"value":"hello"}'


@pytest.fixture(autouse=True)
def _configure_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings,
        "keys",
        {
            KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID),
            "bzk_other": ApiKey(secret="bzs_other", app_id="app-b"),
        },
    )


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


def _headers(body: bytes, key_id: str, secret: str, ts_offset: int) -> dict[str, str]:
    ts = str(int(time.time()) + ts_offset)
    sig = hmac.new(
        secret.encode(), canonical_request("POST", PATH, "", ts, body), hashlib.sha256
    ).hexdigest()
    return {
        "X-Bazaar-Key": key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Content-Type": "application/json",
    }


async def _post(
    client: AsyncClient,
    body: bytes,
    idem_key: str | None,
    key_id: str = KEY_ID,
    secret: str = SECRET,
    ts_offset: int = 0,
) -> Response:
    headers = _headers(body, key_id, secret, ts_offset)
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return await client.post(PATH, content=body, headers=headers)


async def test_first_request_executes() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post(client, BODY, "k-1")
    assert response.status_code == 201
    body = response.json()
    assert body["echo"] == "hello"
    assert "exec_id" in body
    assert "x-idempotency-replay" not in response.headers


async def test_replay_returns_stored_response_without_reexecuting() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, BODY, "k-2")
        # A retry RE-SIGNS with a fresh timestamp (ts_offset=1) — the signature
        # is single-use, so reusing it would 401 before reaching idempotency.
        replay = await _post(client, BODY, "k-2", ts_offset=1)
    assert replay.status_code == 201
    assert replay.headers["x-idempotency-replay"] == "true"
    # exec_id is minted per execution; identical on replay ⇒ the stored
    # response was returned, the handler did NOT run again.
    assert replay.json()["exec_id"] == first.json()["exec_id"]
    # Response headers survive replay (a real 201 would carry e.g. Location).
    assert first.headers["x-echo"] == "hello"
    assert replay.headers["x-echo"] == "hello"


async def test_same_key_different_body_is_409() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _post(client, BODY, "k-3")
        mismatch = await _post(client, b'{"value":"different"}', "k-3", ts_offset=1)
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "idempotency_mismatch"


async def test_in_flight_marker_gives_409() -> None:
    # Simulate a concurrent duplicate: the key is claimed mid-execution.
    redis = get_redis()
    body_hash = hashlib.sha256(BODY).hexdigest()
    await redis.set(f"idem:{APP_ID}:{PATH}:k-4", f"inflight:{body_hash}", ex=60)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post(client, BODY, "k-4")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "request_in_flight"


async def test_different_tenant_same_key_is_independent() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, BODY, "k-5")
        # app-b uses the same Idempotency-Key — must NOT replay app-a's record.
        other = await _post(
            client, BODY, "k-5", key_id="bzk_other", secret="bzs_other", ts_offset=1
        )
    assert other.status_code == 201
    assert "x-idempotency-replay" not in other.headers
    assert other.json()["exec_id"] != first.json()["exec_id"]


async def test_no_idempotency_key_means_no_idempotency() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post(client, BODY, None)
        second = await _post(client, BODY, None, ts_offset=1)
    assert first.json()["exec_id"] != second.json()["exec_id"]
