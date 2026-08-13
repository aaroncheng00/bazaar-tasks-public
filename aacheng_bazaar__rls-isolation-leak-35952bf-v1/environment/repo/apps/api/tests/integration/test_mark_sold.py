"""POST /v1/listings/{id}/mark_sold (T283279728).

Contract (spec/openapi.yaml): sets status=sold and records buyer_user_id — the
verified interaction that later gates review eligibility. Seller-only via
acting_user_id. Naturally idempotent on the same buyer; sold-to-a-different-
buyer or removed → 409 listing_already_sold; missing, malformed, or
cross-tenant id → 404 listing_not_found (no existence leak).
"""

import asyncio
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
# Real uuids, not "app-a": the generated Listing response model types app_id as
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
        await conn.execute(text("DELETE FROM listings"))
    await owner.dispose()
    yield
    await close_redis()


def _sign(method: str, path: str, query: str, timestamp: str, body: bytes) -> str:
    return hmac.new(
        SECRET.encode(), canonical_request(method, path, query, timestamp, body), hashlib.sha256
    ).hexdigest()


_TS_OFFSET = 0  # two calls in the same second must still get distinct signatures (nonce)


async def _post_mark_sold(
    client: AsyncClient,
    listing_ref: str,
    *,
    acting: str,
    buyer: str,
    idem_key: str | None = None,
) -> Response:
    global _TS_OFFSET
    path = f"/v1/listings/{listing_ref}/mark_sold"
    body = json.dumps({"acting_user_id": acting, "buyer_user_id": buyer}).encode()
    _TS_OFFSET += 1
    ts = str(int(time.time()) + _TS_OFFSET)
    headers = {
        "X-Bazaar-Key": KEY_ID,
        "X-Bazaar-Timestamp": ts,
        "X-Bazaar-Signature": _sign("POST", path, "", ts, body),
        "Content-Type": "application/json",
    }
    if idem_key is not None:
        headers["Idempotency-Key"] = idem_key
    return await client.post(path, content=body, headers=headers)


async def _seed_listing(
    *, app_id: str = APP_ID, status: str = "active", buyer: str | None = None
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


async def _fetch_listing_state(listing_id: uuid.UUID) -> tuple[str, str | None]:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text("SELECT status, buyer_user_id FROM listings WHERE id = :id"),
                {"id": listing_id},
            )
        ).one()
    await engine.dispose()
    return row[0], row[1]


async def test_mark_sold_sets_status_and_records_buyer() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(
            client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER, idem_key=str(uuid.uuid4())
        )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == f"lst_{listing_id}"
    assert body["app_id"] == APP_ID
    assert body["status"] == "sold"
    assert body["buyer_user_id"] == BUYER
    assert body["seller_user_id"] == SELLER
    assert body["image_keys"] == []
    assert body["image_urls"] == []
    assert body["actions"] is None  # mark_sold has no viewer_user_id param
    assert await _fetch_listing_state(listing_id) == ("sold", BUYER)


async def test_mark_sold_same_buyer_is_naturally_idempotent() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post_mark_sold(
            client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER, idem_key=str(uuid.uuid4())
        )
        # A retry with a DIFFERENT Idempotency-Key must still 200 — the domain
        # operation itself is idempotent, not just the replay layer.
        second = await _post_mark_sold(
            client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER, idem_key=str(uuid.uuid4())
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["buyer_user_id"] == BUYER
    assert await _fetch_listing_state(listing_id) == ("sold", BUYER)


async def test_mark_sold_different_buyer_conflicts() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _post_mark_sold(client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER)
        second = await _post_mark_sold(client, f"lst_{listing_id}", acting=SELLER, buyer="wa_other")

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "listing_already_sold"
    assert await _fetch_listing_state(listing_id) == ("sold", BUYER)  # unchanged


async def test_mark_sold_removed_listing_conflicts() -> None:
    listing_id = await _seed_listing(status="removed")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "listing_already_sold"


async def test_mark_sold_non_seller_forbidden_and_writes_nothing() -> None:
    listing_id = await _seed_listing()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, f"lst_{listing_id}", acting=INTRUDER, buyer=BUYER)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "seller_only"
    # The 403 must roll back: no partial status/buyer write may survive.
    assert await _fetch_listing_state(listing_id) == ("active", None)


async def test_mark_sold_non_seller_on_sold_listing_still_forbidden() -> None:
    # Seller check precedes the lifecycle conflict: a non-seller gets 403 even
    # on an already-sold listing (never a state-distinguishing 409).
    listing_id = await _seed_listing(status="sold", buyer=BUYER)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, f"lst_{listing_id}", acting=INTRUDER, buyer=BUYER)

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "seller_only"


async def test_mark_sold_unknown_listing_not_found() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, f"lst_{uuid.uuid4()}", acting=SELLER, buyer=BUYER)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "listing_not_found"


@pytest.mark.parametrize("bad_ref", ["lst_not-a-uuid", "9b2f6c1a7e3d4f0ab5c82d1e9a7f3c55"])
async def test_mark_sold_malformed_id_not_found(bad_ref: str) -> None:
    # Malformed ids are 404, not 400 — same no-existence-leak contract as a
    # well-formed but unknown id (spec NotFound example uses a non-uuid id).
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, bad_ref, acting=SELLER, buyer=BUYER)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "listing_not_found"


async def test_mark_sold_cross_tenant_is_not_found() -> None:
    # Seeded under app-b; RLS hides it from app-a's session — 404, never 403/409.
    listing_id = await _seed_listing(app_id=APP_B_ID)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await _post_mark_sold(client, f"lst_{listing_id}", acting=SELLER, buyer=BUYER)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "listing_not_found"


async def _set_tenant(conn, app_id: str) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text("SELECT set_config('bazaar.app_id', :app_id, true)"),
        {"app_id": app_id},
    )


# The exact predicate the handler emits — exercised at the SQL layer so the
# lock serialization is observable without orchestrating two HTTP requests.
_COND_UPDATE = text(
    """
    UPDATE listings SET status = 'sold', buyer_user_id = :buyer
    WHERE id = :id
      AND (status = 'active' OR (status = 'sold' AND buyer_user_id = :buyer))
    """
)


async def test_concurrent_marks_serialize_loser_gets_no_rows() -> None:
    # The handler's load-bearing race property: two marks naming DIFFERENT
    # buyers never both win. The loser's UPDATE blocks on the winner's row
    # lock, re-evaluates its predicate after the winner commits, matches 0
    # rows, and the handler maps that to 409 — no lost update.
    listing_id = await _seed_listing()
    first_wrote = asyncio.Event()
    engine = create_async_engine(settings.app_database_url)

    async def first() -> int:
        async with engine.begin() as conn:
            await _set_tenant(conn, APP_ID)
            result = await conn.execute(_COND_UPDATE, {"id": listing_id, "buyer": BUYER})
            first_wrote.set()
            # Hold the lock so the loser must block and re-evaluate.
            await asyncio.sleep(0.2)
            return result.rowcount

    async def second() -> int:
        await first_wrote.wait()
        async with engine.begin() as conn:
            await _set_tenant(conn, APP_ID)
            result = await conn.execute(_COND_UPDATE, {"id": listing_id, "buyer": "wa_other"})
            return result.rowcount

    winner_rows, loser_rows = await asyncio.gather(first(), second())
    await engine.dispose()
    assert winner_rows == 1
    assert loser_rows == 0
    assert await _fetch_listing_state(listing_id) == ("sold", BUYER)


def test_mark_sold_declares_error_responses_in_openapi() -> None:
    # Pins the drift-guard property: the generated OpenAPI for markListingSold
    # must document the full spec response set, not just the 200. The 401
    # comes from the router-level declaration on v1_router.
    operation = app.openapi()["paths"]["/v1/listings/{listing_id}/mark_sold"]["post"]
    assert {"200", "401", "403", "404", "409"} <= set(operation["responses"])
