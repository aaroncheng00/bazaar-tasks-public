"""POST /v1/reviews (T282737802) — verified-buyer gate, derived subject.

Contract (spec/openapi.yaml): only the recorded buyer of the referenced listing
may review it (403 review_not_eligible otherwise); subject_user_id is DERIVED
from listing.seller_user_id — a client-supplied subject is ignored, which is
what keeps the reputation aggregate uncorruptible. Duplicate → 409
review_exists, backed by UNIQUE(app_id, author_user_id, listing_id) NULLS NOT
DISTINCT. The op declares no 404: missing/cross-tenant/malformed listings
collapse into the same 403 — no existence leak.
"""

import hashlib
import hmac
import json
import time
import uuid
from collections.abc import AsyncIterator
from typing import cast

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import ApiKey, settings
from bazaar_api.db.redis import close_redis, get_redis
from bazaar_api.db.session import dispose_engine
from bazaar_api.main import app
from bazaar_api.middleware.auth_hmac import canonical_request

KEY_ID = "bzk_test"
SECRET = "bzs_test_secret"
# Real uuids, not "app-a": the generated Review response model types app_id as
# UUID, and FastAPI validates the response — a non-uuid tenant id would 500.
APP_ID = "9b2f6c1a-7e3d-4f0a-b5c8-2d1e9a7f3c55"
APP_B_ID = "1a2b3c4d-5e6f-4a5b-8c9d-0e1f2a3b4c5d"
SELLER = "wa_seller"
BUYER = "wa_buyer"
INTRUDER = "wa_intruder"


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
    async for key in redis.scan_iter("idem:*"):
        await redis.delete(key)
    owner = create_async_engine(settings.database_url)
    async with owner.begin() as conn:
        await conn.execute(text("SET LOCAL bazaar.app_id = ''"))
        await conn.execute(text("DELETE FROM reviews"))
        await conn.execute(text("DELETE FROM listings"))
    await owner.dispose()
    yield
    await close_redis()


_TS_OFFSET = 0  # two calls in the same second must still get distinct signatures (nonce)


async def _post_review(
    client: AsyncClient, payload: dict[str, object], idem_key: str | None = None
) -> Response:
    global _TS_OFFSET
    path = "/v1/reviews"
    body = json.dumps(payload).encode()
    _TS_OFFSET += 1
    ts = str(int(time.time()) + _TS_OFFSET)
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": hmac.new(
            SECRET.encode(), canonical_request("POST", path, "", ts, body), hashlib.sha256
        ).hexdigest(),
        "Content-Type": "application/json",
    }
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return await client.post(path, content=body, headers=headers)


def _review_payload(listing_uuid: uuid.UUID, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "listing_id": f"lst_{listing_uuid}",
        "author_user_id": BUYER,
        "rating": 5,
        "body": "Great couch",
    }
    payload.update(overrides)
    return payload


async def _seed_listing(
    *, app_id: str = APP_ID, status: str = "sold", buyer: str | None = BUYER
) -> uuid.UUID:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        row = (
            await conn.execute(
                text(
                    """
                    INSERT INTO listings (app_id, seller_user_id, title, price_cents,
                                          category, condition, lat, lng, geohash, status,
                                          buyer_user_id)
                    VALUES (:app_id, :seller, 'Leather couch', 25000, 'furniture', 'good',
                            37.7749, -122.4194, '9q8yy', :status, :buyer)
                    RETURNING id
                    """
                ),
                {"app_id": app_id, "seller": SELLER, "status": status, "buyer": buyer},
            )
        ).one()
    await engine.dispose()
    return cast("uuid.UUID", row[0])


async def _fetch_reviews() -> list[tuple[str, str, str, int]]:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT subject_user_id, author_user_id, app_id, rating"
                    " FROM reviews ORDER BY created_at"
                )
            )
        ).all()
    await engine.dispose()
    return [(r[0], r[1], r[2], r[3]) for r in rows]


async def test_create_review_derives_subject_and_persists() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(
            client, _review_payload(listing_id), idem_key=str(uuid.uuid4())
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"].startswith("rev_")
    assert body["app_id"] == APP_ID
    assert body["listing_id"] == f"lst_{listing_id}"
    assert body["subject_user_id"] == SELLER  # derived from the listing, never client-sent
    assert body["author_user_id"] == BUYER
    assert body["rating"] == 5
    assert body["body"] == "Great couch"
    assert body["created_at"] is not None
    assert await _fetch_reviews() == [(SELLER, BUYER, APP_ID, 5)]


async def test_create_review_ignores_client_supplied_subject() -> None:
    # Anti-poisoning: a verified buyer posting against an arbitrary subject
    # would corrupt the one trust signal in the MVP. The server ignores it.
    listing_id = await _seed_listing()
    payload = _review_payload(listing_id, subject_user_id="wa_evil")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, payload)

    assert response.status_code == 201
    assert response.json()["subject_user_id"] == SELLER
    assert (await _fetch_reviews())[0][0] == SELLER


async def test_create_review_non_buyer_forbidden() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(listing_id, author_user_id=INTRUDER))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_not_eligible"
    assert await _fetch_reviews() == []


async def test_create_review_active_listing_forbidden() -> None:
    # No recorded buyer (listing never sold) → nobody is eligible.
    listing_id = await _seed_listing(status="active", buyer=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(listing_id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_not_eligible"


async def test_create_review_unknown_listing_forbidden_no_leak() -> None:
    # Spec declares no 404 for this op: missing collapses into the same 403.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(uuid.uuid4()))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_not_eligible"


@pytest.mark.parametrize("bad_ref", ["lst_not-a-uuid", "9b2f6c1a7e3d4f0ab5c82d1e9a7f3c55"])
async def test_create_review_malformed_listing_ref_forbidden(bad_ref: str) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(uuid.uuid4(), listing_id=bad_ref))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_not_eligible"


async def test_create_review_cross_tenant_forbidden() -> None:
    # Seeded under app-b; RLS hides it — the same 403 as "missing", no leak.
    listing_id = await _seed_listing(app_id=APP_B_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(listing_id))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "review_not_eligible"


async def test_create_review_duplicate_conflicts() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post_review(client, _review_payload(listing_id))
        # A DIFFERENT Idempotency-Key reaches the handler and hits the unique
        # constraint — one review per author per listing.
        second = await _post_review(client, _review_payload(listing_id))

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "review_exists"
    assert len(await _fetch_reviews()) == 1


async def test_create_review_same_key_retry_replays_not_conflicts() -> None:
    # A legitimate retry (same key + same body) must short-circuit at the
    # replay layer with the original 201 — never reach the constraint and 409.
    listing_id = await _seed_listing()
    idem_key = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post_review(client, _review_payload(listing_id), idem_key=idem_key)
        retry = await _post_review(client, _review_payload(listing_id), idem_key=idem_key)

    assert first.status_code == 201
    assert retry.status_code == 201
    assert retry.headers["x-idempotency-replay"] == "true"
    assert retry.json()["id"] == first.json()["id"]
    assert len(await _fetch_reviews()) == 1


@pytest.mark.parametrize("rating", [0, 6])
async def test_create_review_rating_out_of_range_400(rating: int) -> None:
    # The generated layer validates (ge=1, le=5); the DB CHECK is the backstop.
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_review(client, _review_payload(listing_id, rating=rating))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "validation_failed"


def test_create_review_declares_error_responses_in_openapi() -> None:
    # Pins the drift-guard property: the op documents its full spec response
    # set (note: 401/403/409 only — the spec deliberately declares no 404).
    operation = app.openapi()["paths"]["/v1/reviews"]["post"]
    assert {"201", "401", "403", "409"} <= set(operation["responses"])
