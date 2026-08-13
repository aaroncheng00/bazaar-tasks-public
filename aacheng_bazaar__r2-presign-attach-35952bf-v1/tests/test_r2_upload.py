"""R2 presigned upload + attach-verify + orphan reaper tests (S1 image pipeline) — hard v2 fixed."""

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
APP_ID = "11111111-1111-4111-8111-111111111111"
SELLER = "usr_seller_1"

_last_ts = 0

def _next_ts() -> str:
    global _last_ts
    now = int(time.time())
    if now <= _last_ts:
        now = _last_ts + 1
    _last_ts = now
    return str(now)

@pytest.fixture(autouse=True)
def _keys_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "keys", {KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID)})
    monkeypatch.setattr(settings, "dev_skip_hmac", False)
    monkeypatch.setattr(settings, "env", "dev")

@pytest.fixture(autouse=True)
async def _clean_state() -> AsyncIterator[None]:
    global _last_ts
    _last_ts = 0
    await dispose_engine()
    redis = get_redis()
    async for key in redis.scan_iter("nonce:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("pending_image:*"):
        await redis.delete(key)
    async for key in redis.scan_iter("idem:*"):
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
    ts = _next_ts()
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
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign = await client.post(path, content=body_bytes, headers=headers)
    assert presign.status_code == 200
    image_key = presign.json()["image_key"]
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
    other_key_id = "bzk_other"
    other_secret = "bzs_other"
    other_app = "22222222-2222-4222-8222-222222222222"
    def _sign_other(method: str, path: str, body: bytes):
        ts = _next_ts()
        sig = hmac.new(
            other_secret.encode(),
            canonical_request(method, path, "", ts, body),
            hashlib.sha256,
        ).hexdigest()
        return ts, sig
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
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
        ts = _next_ts()
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
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.json()["image_key"] == r2.json()["image_key"]

@pytest.mark.asyncio
async def test_idempotency_same_timestamp_rejected_as_hmac_replay():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    idem_key = str(uuid.uuid4())
    ts = _next_ts()
    sig = _sign("POST", path, "", ts, body_bytes)
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Content-Type": "application/json",
        "Idempotency-Key": idem_key,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(path, content=body_bytes, headers=headers)
        r2 = await client.post(path, content=body_bytes, headers=headers)
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 401, f"Expected 401 replay, got {r2.status_code}: {r2.text}"

@pytest.mark.asyncio
async def test_orphan_reaper_deletes_only_unattached():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers1 = _headers("POST", path, body_bytes)
    headers2 = _headers("POST", path, body_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign1 = await client.post(path, content=body_bytes, headers=headers1)
        presign2 = await client.post(path, content=body_bytes, headers=headers2)
    assert presign1.status_code == 200, presign1.text
    assert presign2.status_code == 200, presign2.text
    key1 = presign1.json()["image_key"]
    key2 = presign2.json()["image_key"]
    attach_body = {"acting_user_id": SELLER, "image_key": key1}
    attach_bytes = _body_json(attach_body)
    attach_path = f"/v1/listings/{listing_id}/images/attach"
    attach_headers = _headers("POST", attach_path, attach_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(attach_path, content=attach_bytes, headers=attach_headers)
    assert resp.status_code == 200, resp.text
    redis = get_redis()
    raw = await redis.get(f"pending_image:{APP_ID}:{key2}")
    assert raw is not None
    meta = json.loads(raw)
    from datetime import datetime, timedelta, timezone
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    meta["created_at"] = old.isoformat()
    await redis.set(f"pending_image:{APP_ID}:{key2}", json.dumps(meta), ex=86400 * 2)
    from bazaar_api.modules.listings.images import reap_orphans
    reaped = await reap_orphans()
    assert reaped >= 1
    assert await redis.get(f"pending_image:{APP_ID}:{key2}") is None
    owner = create_async_engine(settings.database_url)
    async with owner.connect() as conn:
        row = (
            await conn.execute(text("SELECT image_keys FROM listings WHERE id = :id"), {"id": listing_id[4:]})
        ).one()
    await owner.dispose()
    assert key1 in row[0]

# --- Hardening traps ---

@pytest.mark.asyncio
async def test_cross_tenant_attach_forbidden():
    listing_id = await _insert_listing()
    body = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign = await client.post(path, content=body_bytes, headers=headers)
    assert presign.status_code == 200
    image_key = presign.json()["image_key"]
    other_key_id = "bzk_other"
    other_secret = "bzs_other"
    other_app = "22222222-2222-4222-8222-222222222222"
    def _sign_other(m, p, b):
        ts = _next_ts()
        sig = hmac.new(other_secret.encode(), canonical_request(m, p, "", ts, b), hashlib.sha256).hexdigest()
        return ts, sig
    from bazaar_api.config import settings as _settings
    _settings.keys = {
        KEY_ID: ApiKey(secret=SECRET, app_id=APP_ID),
        other_key_id: ApiKey(secret=other_secret, app_id=other_app),
    }
    attach_body = {"acting_user_id": SELLER, "image_key": image_key}
    attach_bytes = _body_json(attach_body)
    attach_path = f"/v1/listings/{listing_id}/images/attach"
    ts, sig = _sign_other("POST", attach_path, attach_bytes)
    other_headers = {
        "X-Bazaar-Key": other_key_id,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": sig,
        "Content-Type": "application/json",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(attach_path, content=attach_bytes, headers=other_headers)
    assert resp.status_code == 404

@pytest.mark.asyncio
async def test_attach_seller_only():
    listing_id = await _insert_listing(seller="owner_seller")
    body = {"acting_user_id": "owner_seller", "content_type": "image/jpeg", "content_length": 1024}
    body_bytes = _body_json(body)
    path = f"/v1/listings/{listing_id}/images"
    headers = _headers("POST", path, body_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        presign = await client.post(path, content=body_bytes, headers=headers)
    assert presign.status_code == 200
    image_key = presign.json()["image_key"]
    attach_body = {"acting_user_id": "attacker", "image_key": image_key}
    attach_bytes = _body_json(attach_body)
    attach_path = f"/v1/listings/{listing_id}/images/attach"
    attach_headers = _headers("POST", attach_path, attach_bytes)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(attach_path, content=attach_bytes, headers=attach_headers)
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "seller_only"

@pytest.mark.asyncio
async def test_idempotency_different_body_is_mismatch():
    """Same Idempotency-Key but different body must be 409 mismatch, not replay nor new."""
    listing_id = await _insert_listing()
    body1 = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 1024}
    body2 = {"acting_user_id": SELLER, "content_type": "image/jpeg", "content_length": 2048}
    body1_bytes = _body_json(body1)
    body2_bytes = _body_json(body2)
    path = f"/v1/listings/{listing_id}/images"
    idem_key = str(uuid.uuid4())
    def _headers_for(b):
        ts = _next_ts()
        sig = _sign("POST", path, "", ts, b)
        return {
            "X-Bazaar-Key": KEY_ID,
            "X-Bazaar-Timestamp": ts,
            "X-Bazaar-Signature": sig,
            "Content-Type": "application/json",
            "Idempotency-Key": idem_key,
        }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(path, content=body1_bytes, headers=_headers_for(body1_bytes))
        r2 = await client.post(path, content=body2_bytes, headers=_headers_for(body2_bytes))
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 409, f"Expected 409 mismatch for different body, got {r2.status_code}: {r2.text}"
