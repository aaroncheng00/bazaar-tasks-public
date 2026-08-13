"""0004 search indexes: generated search_vector + index catalog assertions."""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
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


_INSERT = text(
    """
    INSERT INTO listings (app_id, seller_user_id, title, description, price_cents,
                          category, condition, lat, lng, geohash)
    VALUES ('app-a', 'wa_usr_1', :title, :description, 25000,
            'furniture', 'good', 37.7749, -122.4194, '9q8yy')
    RETURNING id
    """
)


async def _insert(conn, title: str, description: str) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(_INSERT, {"title": title, "description": description})


async def test_search_vector_matches_title_and_description(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await _insert(conn, "Leather couch", "Well loved")
        await _insert(conn, "Wooden table", "Pairs nicely with a leather ottoman")
        await _insert(conn, "Floor lamp", "Brushed brass")
        rows = (
            await conn.execute(
                text(
                    "SELECT title FROM listings "
                    "WHERE search_vector @@ plainto_tsquery('english', 'leather')"
                )
            )
        ).all()
    assert sorted(r[0] for r in rows) == ["Leather couch", "Wooden table"]


async def test_title_match_outranks_description_match(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await _insert(conn, "Unrelated item", "This description mentions stroller")
        await _insert(conn, "Stroller", "Barely used")
        titles = (
            await conn.execute(
                text(
                    "SELECT title FROM listings "
                    "WHERE search_vector @@ plainto_tsquery('english', 'stroller') "
                    "ORDER BY ts_rank(search_vector, plainto_tsquery('english', 'stroller')) "
                    "DESC"
                )
            )
        ).all()
    assert [r[0] for r in titles] == ["Stroller", "Unrelated item"]


async def test_search_indexes_exist(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        rows = (
            await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'listings'")
            )
        ).all()
    names = {r[0] for r in rows}
    assert {
        "listings_search_vector_idx",
        "listings_browse_idx",
        "listings_lat_idx",
        "listings_lng_idx",
    } <= names
