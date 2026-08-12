"""R2 presigned upload + attach-verify + orphan reaper tests (S1 image pipeline)."""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator

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
SELLER = "usr_seller_1"


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
    async for key in redis.scan_iter("pending_image:*"):
        await redis.delete(key)
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(text("DELETE FROM listings"))
        await conn.execute(text("DELETE FROM api_keys"))
    await owner.dispose()
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(), canonical_request(method, path, query, timestamp, body), hashlib.sha256
    ).hexdigest()


def _headers(method: str, path: str, body: bytes = b"", query: str = "") -> dict[str, str]:
    ts = str(int(time.time()))
    return {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": _sign(method, path, query, ts, body),
        "Content-Type": "application/json",
    }


async def _insert_listing(seller: str = SELLER) -> str:
    listing_uuid = uuid.uuid4()
    listing_id = f"lst_{listing_uuid}"
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO listings (id, app_id, seller_user_id, title, description, price_cents, currency, category, condition, lat, lng, geohash, status, image_keys) "
                "VALUES (:id, :app_id, :seller, 'Test Item', 'desc', 1000, 'USD', 'furniture', 'new', 37.7749, -122.4194, '9q8yyk', 'active', '[]'::jsonb)"
            ),
            {"id": str(listing_uuid), "app_id": APP_ID, "seller": seller},
        )
    await owner.dispose()
    return listing_id


def _body_json(data: dict) -> bytes:
    return json.dumps(data).encode()


@pytest.mark.asyncio
async def test_presign_returns_url_with_app_prefix():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(path, content=body_bytes, headers=headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["image_key"].startswith(f"{APP_ID}/listings/{listing_id}/")
    assert data["upload_url"]
    assert data["method"] == "PUT"
    assert data["expires_in"] == 900


@pytest.mark.asyncio
async def test_attach_verify_rejects_wrong_content_type():
    listing_id = await _insert_listing()
    # Presign with jpeg
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign = await client.post(path, content=body_bytes, headers=headers)
    assert presign.status_code == 200
    image_key = presign.json()["image_key"]

    # Simulate actual upload having different type by injecting into Redis pending
    redis = get_redis()
    raw = await redis.get(f"pending_image:{APP_ID}:{image_key}")
    assert raw is not None
    meta = json.loads(raw)
    meta["actual_content_type"] = "application/octet-stream"
    await redis.set(f"pending_image:{APP_ID}:{image_key}", json.dumps(meta), ex=86400)

    attach_body = {"acting_user_id": SELLER, "image_key": image_key}
    attach_bytes = _body_json(attach_body)
    attach_path = f"/v1/listings/{listing_id}/images/attach"
    attach_headers = _headers("POST", attach_path, attach_bytes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(attach_path, content=attach_bytes, headers=attach_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"]["code"] == "validation_failed"


@pytest.mark.asyncio
async def test_attach_appends_not_overwrites():
    listing_id = await _insert_listing()

    async def _presign_and_attach():
        body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
        body_bytes = _body_json(body)
        path = f"/v1/listings/{listing_id}/images"
        headers = _headers("POST", path, body_bytes)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            presign = await client.post(path, content=body_bytes, headers=headers)
        assert presign.status_code == 200
        image_key = presign.json()["image_key"]
        attach_body = {"acting_user_id": SELLER, "image_key": image_key}
        attach_bytes = _body_json(attach_body)
        attach_path = f"/v1/listings/{listing_id}/images/attach"
        attach_headers = _headers("POST", attach_path, attach_bytes)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(attach_path, content=attach_bytes, headers=attach_headers)
        assert resp.status_code == 200, resp.text
        return resp.json()["image_keys"]

    keys1 = await _presign_and_attach()
    assert len(keys1) == 1
    keys2 = await _presign_and_attach()
    assert len(keys2) == 2
    assert keys1[0] in keys2


@pytest.mark.asyncio
async def test_cross_tenant_presign_forbidden():
    listing_id = await _insert_listing()
    # Other tenant tries to presign for app-a listing
    other_key_id = "bzk_other"
    other_secret = "bzs_other"
    other_app = "app-b"

    def _sign_other(method: str, path: str, body: bytes) -> str:
        ts = str(int(time.time()))
        sig = hmac.new(
            other_secret.encode(),
            canonical_request(method, path, "", ts, body),
            hashlib.sha256,
        ).hexdigest()
        return ts, sig

    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"

    # Monkeypatch keys to include other tenant
    from bazaar_api.config import settings as _settings

    _settings.keys = {
        KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID),
        other_key_id: ApiKey(secret=other_secret, app_id=other_app),
    }

    ts, sig = _sign_other("POST", path, body_bytes)
    headers = {
        "X-Bazaar-Key": other_key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Content-Type": "application/json",
    }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(path, content=body_bytes, headers=headers)

    # RLS + 404 - no leak
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_seller_only_via_acting_user_id():
    listing_id = await _insert_listing(seller="owner_seller")
    body = {"acting_user_id": "attacker", "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(path, content=body_bytes, headers=headers)

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "seller_only"


@pytest.mark.asyncio
async def test_idempotency_replay_returns_original():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    idem_key = str(uuid.uuid4())

    def _headers_with_idem():
        ts = str(int(time.time()))
        sig = _sign("POST", path, "", ts, body_bytes)
        return {
            "X-Bazaar-Key": KEY_ID,
            "X-Bazaar-Timestamp": ts,
            "X-Bazaar-Signature": sig,
            "Content-Type": "application/json",
            "Idempotency-Key": idem_key,
        }

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(path, content=body_bytes, headers=_headers_with_idem())
        r2 = await client.post(path, content=body_bytes, headers=_headers_with_idem())

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["image_key"] == r2.json()["image_key"]


@pytest.mark.asyncio
async def test_orphan_reaper_deletes_only_unattached():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign1 = await client.post(path, content=body_bytes, headers=headers)
        presign2 = await client.post(path, content=body_bytes, headers=headers)

    assert presign1.status_code == 200
    assert presign2.status_code == 200
    key1 = presign1.json()["image_key"]
    key2 = presign2.json()["image_key"]

    # Attach only key1
    attach_body = {"acting_user_id": SELLER, "image_key": key1}
    attach_bytes = _body_json(attach_body)
    attach_path = f"/v1/listings/{listing_id}/images/attach"
    attach_headers = _headers("POST", attach_path, attach_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(attach_path, content=attach_bytes, headers=attach_headers)
    assert resp.status_code == 200

    # Make key2 orphan and old (>24h) by rewriting its Redis created_at
    redis = get_redis()
    raw = await redis.get(f"pending_image:{APP_ID}:{key2}")
    assert raw is not None
    meta = json.loads(raw)
    # Set created_at to 25h ago
    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(hours=25)
    meta["created_at"] = old.isoformat()
    await redis.set(f"pending_image:{APP_ID}:{key2}", json.dumps(meta), ex=86400 * 2)

    # Run reaper
    from bazaar_api.modules.listings.images import reap_orphans

    reaped = await reap_orphans()
    assert reaped >= 1

    # key1 should still be attached, key2 should be gone from pending
    assert await redis.get(f"pending_image:{APP_ID}:{key2}") is None
    # key1 pending should be gone because it was attached (deleted on attach)
    # Verify listing still has key1
    owner = create_async_engine(settings.database_url)
    async with owner.connect() as conn:
        row = (
            await conn.execute(text("SELECT image_keys FROM listings WHERE id = :id"), {"id": listing_id[4:]})
        ).one()
    await owner.dispose()
    assert key1 in row[0]
