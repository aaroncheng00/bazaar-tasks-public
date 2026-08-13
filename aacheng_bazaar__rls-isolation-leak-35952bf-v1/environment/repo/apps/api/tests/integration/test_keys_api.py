"""Key rotation endpoints: create + revoke under /v1 auth."""

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
from bazaar_api.db.session import dispose_engine
from bazaar_api.keys import mint_key, revoke_key
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
async def _clean_state() -> AsyncIterator[None]:
    await dispose_engine()
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(text("DELETE FROM api_keys"))
    await owner.dispose()
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(), canonical_request(method, path, query, timestamp, body), hashlib.sha256
    ).hexdigest()


def _headers(method: str, path: str, query: str = "") -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": _sign(method, path, query, ts, b""),
    }


def _headers_for(key_id: str, secret: str, method: str, path: str) -> dict[str, str]:
    """Sign with an arbitrary (e.g. DB-minted) key rather than the env seed."""
    ts = str(int(time.time()))
    sig = hmac.new(
        secret.encode(), canonical_request(method, path, "", ts, b""), hashlib.sha256
    ).hexdigest()
    return {"X-Bazaar-Key": key_id, "X-Bazaar-Timestamp": ts, "X-Bazaar-Signature": sig}


async def _fetch_key_row(key_id: str) -> tuple[str, str, object]:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT app_id, pgp_sym_decrypt(secret_ciphertext, :master_key), revoked_at"
                    " FROM api_keys WHERE key_id = :key_id"
                ),
                {"master_key": settings.key_encryption_secret, "key_id": key_id},
            )
        ).one()
    await engine.dispose()
    return row[0], row[1], row[2]


async def test_create_key_returns_secret_once_and_stores_ciphertext() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/apps/{APP_ID}/keys", headers=_headers("POST", f"/v1/apps/{APP_ID}/keys")
        )

    assert response.status_code == 201
    body = response.json()
    assert body["key_id"].startswith("bzk_")
    assert body["secret"].startswith("bzs_")

    app_id, decrypted, revoked_at = await _fetch_key_row(body["key_id"])
    assert app_id == APP_ID
    assert decrypted == body["secret"]
    assert revoked_at is None


async def test_create_key_for_another_app_is_forbidden() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/apps/app-b/keys", headers=_headers("POST", "/v1/apps/app-b/keys")
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_revoke_retires_key() -> None:
    key_id, _secret = await mint_key(APP_ID)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/apps/{APP_ID}/keys/{key_id}/revoke",
            headers=_headers("POST", f"/v1/apps/{APP_ID}/keys/{key_id}/revoke"),
        )

    assert response.status_code == 200
    assert response.json()["key_id"] == key_id

    _app_id, _dec, revoked_at = await _fetch_key_row(key_id)
    assert revoked_at is not None


async def test_revoke_presented_key_is_rejected() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/apps/{APP_ID}/keys/{KEY_ID}/revoke",
            headers=_headers("POST", f"/v1/apps/{APP_ID}/keys/{KEY_ID}/revoke"),
        )
        assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_list_keys_returns_metadata_only() -> None:
    first_id, _ = await mint_key(APP_ID)
    second_id, _ = await mint_key(APP_ID)
    await mint_key("app-b")  # another tenant's key must not appear

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/v1/apps/{APP_ID}/keys", headers=_headers("GET", f"/v1/apps/{APP_ID}/keys")
        )

    assert response.status_code == 200
    keys = response.json()["keys"]
    assert [k["key_id"] for k in keys] == [second_id, first_id]  # newest first
    for k in keys:
        assert set(k) == {"key_id", "created_at", "revoked_at"}  # no secret material
        assert k["revoked_at"] is None


async def test_list_keys_for_another_app_is_forbidden() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/v1/apps/app-b/keys", headers=_headers("GET", "/v1/apps/app-b/keys")
        )
    assert response.status_code == 403


async def test_revoke_other_apps_key_is_not_found() -> None:
    other_key_id, _secret = await mint_key("app-b")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/apps/{APP_ID}/keys/{other_key_id}/revoke",
            headers=_headers("POST", f"/v1/apps/{APP_ID}/keys/{other_key_id}/revoke"),
        )
        assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_db_minted_key_authenticates() -> None:
    """The switchover's core path: a key that exists ONLY in api_keys must auth."""
    key_id, secret = await mint_key(APP_ID)
    path = f"/v1/apps/{APP_ID}/keys"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers=_headers_for(key_id, secret, "GET", path))

    assert response.status_code == 200
    assert any(k["key_id"] == key_id for k in response.json()["keys"])


async def test_revoked_db_key_is_rejected() -> None:
    """Revoke must be a real security control: dead key, dead authentication."""
    key_id, secret = await mint_key(APP_ID)
    await revoke_key(APP_ID, key_id)
    path = f"/v1/apps/{APP_ID}/keys"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(path, headers=_headers_for(key_id, secret, "GET", path))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unknown_key"
