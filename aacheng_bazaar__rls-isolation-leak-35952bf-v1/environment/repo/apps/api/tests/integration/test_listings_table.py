"""0003 listings table: DDL defaults, CHECK constraints, updated_at trigger, RLS block."""

import asyncio
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bazaar_api.config import settings


@pytest.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(settings.database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_listings(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await conn.execute(text("DELETE FROM listings"))


async def _set_tenant(conn, app_id: str) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text("SELECT set_config('bazaar.app_id', :app_id, true)"),
        {"app_id": app_id},
    )


def _listing(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "app_id": "app-a",
        "seller_user_id": "wa_usr_1",
        "title": "Leather couch",
        "description": "Well loved",
        "price_cents": 25000,
        "category": "furniture",
        "condition": "good",
        "lat": 37.7749,
        "lng": -122.4194,
        "geohash": "9q8yy",
    }
    row.update(overrides)
    return row


_INSERT = text(
    """
    INSERT INTO listings (app_id, seller_user_id, title, description, price_cents,
                          category, condition, lat, lng, geohash)
    VALUES (:app_id, :seller_user_id, :title, :description, :price_cents,
            :category, :condition, :lat, :lng, :geohash)
    RETURNING id, currency, status, buyer_user_id, image_keys, created_at, updated_at
    """
)


async def test_insert_applies_defaults(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        row = (await conn.execute(_INSERT, _listing())).mappings().one()
    assert row["currency"] == "USD"
    assert row["status"] == "active"
    assert row["buyer_user_id"] is None
    assert row["image_keys"] == []
    assert row["id"] is not None
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


@pytest.mark.parametrize("bad", [{"category": "cars"}, {"condition": "broken"}])
async def test_check_constraints_rejected(owner_engine: AsyncEngine, bad: dict[str, str]) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        with pytest.raises(DBAPIError):
            await conn.execute(_INSERT, _listing(**bad))


async def test_invalid_status_rejected(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        with pytest.raises(DBAPIError):
            await conn.execute(
                text(
                    """
                    INSERT INTO listings (app_id, seller_user_id, title, price_cents,
                                          category, condition, lat, lng, geohash, status)
                    VALUES ('app-a', 'wa_usr_1', 'x', 100, 'furniture', 'new',
                            37.7, -122.4, '9q8yy', 'pending')
                    """
                )
            )


async def test_updated_at_bumped_on_update(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        row = (await conn.execute(_INSERT, _listing())).mappings().one()
    await asyncio.sleep(0.05)  # now() is transaction time — separate txs must differ
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await conn.execute(
            text("UPDATE listings SET title = 'x' WHERE id = :id"), {"id": row["id"]}
        )
        updated = (
            await conn.execute(
                text("SELECT updated_at FROM listings WHERE id = :id"), {"id": row["id"]}
            )
        ).scalar_one()
    assert updated > row["updated_at"]


async def test_rls_enabled_forced_with_tenant_policy(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        flags = (
            await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'listings'"
                )
            )
        ).one()
        policies = (
            await conn.execute(
                text(
                    "SELECT p.polname FROM pg_policy p "
                    "JOIN pg_class c ON p.polrelid = c.oid WHERE c.relname = 'listings'"
                )
            )
        ).all()
    assert flags == (True, True)
    assert [p[0] for p in policies] == ["tenant_isolation"]
