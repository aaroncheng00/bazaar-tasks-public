"""Tenant signup + provisioning-token bootstrap (the first-key flow)."""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.db.session import dispose_engine
from bazaar_api.main import app


@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    await dispose_engine()
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(text("DELETE FROM api_keys"))
        await conn.execute(text("DELETE FROM apps"))
    await owner.dispose()
    yield
    await close_redis()


async def _signup(client: AsyncClient, name: str = "WhatsApp Local Marketplace") -> dict[str, Any]:
    response = await client.post("/v1/apps", json={"name": name, "owner_email": "ops@example.com"})
    assert response.status_code == 201
    body: dict[str, Any] = response.json()
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_signup_returns_app_and_one_time_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = await _signup(client)

    assert body["app_id"]
    assert body["name"] == "WhatsApp Local Marketplace"
    assert body["provisioning_token"].startswith("bzp_")
    assert body["created_at"]


async def test_signup_stores_token_hash_not_plaintext() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = await _signup(client)

    owner = create_async_engine(settings.database_url)
    async with owner.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT provisioning_token_hash, provisioning_expires_at,"
                    " provisioning_used_at FROM apps WHERE app_id = :app_id"
                ),
                {"app_id": body["app_id"]},
            )
        ).one()
    await owner.dispose()

    assert row[0] == hashlib.sha256(body["provisioning_token"].encode()).hexdigest()
    assert body["provisioning_token"] not in row[0]
    assert row[1] > datetime.now(UTC)  # expires in the future
    assert row[2] is None  # unused


async def test_first_key_via_provisioning_token() -> None:
    """The bootstrap: signup, then mint key #1 with Bearer — no HMAC headers."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        response = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )

    assert response.status_code == 201
    assert response.json()["key_id"].startswith("bzk_")
    assert response.json()["secret"].startswith("bzs_")


async def test_provisioning_token_is_single_use() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        first = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
        assert first.status_code == 201

        second = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
    assert second.status_code == 401


async def test_provisioning_token_scoped_to_first_key_route() -> None:
    """The bearer token must not authenticate anything except the first mint."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        response = await client.get(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
    assert response.status_code == 401


async def test_provisioning_token_for_wrong_app() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        response = await client.post(
            "/v1/apps/00000000-0000-0000-0000-000000000000/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
    assert response.status_code == 401


async def test_retry_with_used_token_replays_stored_response() -> None:
    """The review trace: mint succeeds, response lost, retry must replay the
    stored 201 — not 401 on the burned token, and not mint a second key."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        headers = {
            **_bearer(app_body["provisioning_token"]),
            "Idempotency-Key": "idem-bootstrap-retry",
        }
        first = await client.post(f"/v1/apps/{app_body['app_id']}/keys", headers=headers)
        assert first.status_code == 201

        retry = await client.post(f"/v1/apps/{app_body['app_id']}/keys", headers=headers)

    assert retry.status_code == 201
    assert retry.json() == first.json()  # same key_id + secret
    assert retry.headers["x-idempotency-replay"] == "true"

    owner = create_async_engine(settings.database_url)
    async with owner.connect() as conn:
        count = (
            await conn.execute(
                text("SELECT count(*) FROM api_keys WHERE app_id = :app_id"),
                {"app_id": app_body["app_id"]},
            )
        ).scalar_one()
    await owner.dispose()
    assert count == 1  # replayed, not re-minted


async def test_used_token_without_idempotency_key_is_401() -> None:
    """Burned token + no Idempotency-Key → nothing to replay → 401."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        headers = _bearer(app_body["provisioning_token"])
        first = await client.post(f"/v1/apps/{app_body['app_id']}/keys", headers=headers)
        assert first.status_code == 201

        retry = await client.post(f"/v1/apps/{app_body['app_id']}/keys", headers=headers)
    assert retry.status_code == 401


async def test_used_token_with_key_but_no_stored_response_is_401() -> None:
    """First mint sent no Idempotency-Key → nothing stored → a retry naming a
    key still 401s. Replay only ever serves what was actually stored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)
        first = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
        assert first.status_code == 201

        retry = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers={
                **_bearer(app_body["provisioning_token"]),
                "Idempotency-Key": "idem-never-stored",
            },
        )
    assert retry.status_code == 401


async def test_expired_provisioning_token() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        app_body = await _signup(client)

    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text("UPDATE apps SET provisioning_expires_at = :past WHERE app_id = :app_id"),
            {
                "past": datetime.now(UTC) - timedelta(minutes=1),
                "app_id": app_body["app_id"],
            },
        )
    await owner.dispose()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/v1/apps/{app_body['app_id']}/keys",
            headers=_bearer(app_body["provisioning_token"]),
        )
    assert response.status_code == 401
