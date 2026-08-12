import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bazaar_api.config import settings

OWNER_URL = settings.database_url
APP_URL = settings.app_database_url


@pytest.fixture
async def owner_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(OWNER_URL)
    yield engine
    await engine.dispose()


@pytest.fixture
async def app_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(APP_URL)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def clean_reviews(owner_engine: AsyncEngine) -> None:
    # Relies on the owner role bypassing RLS (superuser/BYPASSRLS today). Under
    # FORCE RLS a plain owner role would match zero rows with bazaar.app_id=''
    # and the DELETE would silently no-op, leaking rows across tests. Mirrors
    # clean_docs in test_tenant_isolation.py — same latent caveat.
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL bazaar.app_id = ''"))
        await conn.execute(text("DELETE FROM reviews"))


async def _set_tenant(conn, app_id: str) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text("SELECT set_config('bazaar.app_id', :app_id, true)"),
        {"app_id": app_id},
    )


async def _insert_review(  # type: ignore[no-untyped-def]
    conn,
    *,
    app_id: str = "app-a",
    subject_user_id: str = "seller-1",
    author_user_id: str = "buyer-1",
    listing_id: str | None = None,
    rating: int = 5,
    body: str | None = None,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO reviews (app_id, subject_user_id, author_user_id, listing_id, rating, body)
            VALUES (:app_id, :subject_user_id, :author_user_id, :listing_id, :rating, :body)
            """
        ),
        {
            "app_id": app_id,
            "subject_user_id": subject_user_id,
            "author_user_id": author_user_id,
            "listing_id": listing_id,
            "rating": rating,
            "body": body,
        },
    )


async def test_rating_check_accepts_1_to_5(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        for rating in (1, 2, 3, 4, 5):
            await _insert_review(conn, author_user_id=f"buyer-{rating}", rating=rating)


@pytest.mark.parametrize("rating", [0, 6])
async def test_rating_check_rejects_out_of_range(owner_engine: AsyncEngine, rating: int) -> None:
    async with owner_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await _insert_review(conn, rating=rating)


async def test_duplicate_review_same_listing_conflicts(owner_engine: AsyncEngine) -> None:
    # The unique violation the write handler maps to 409 review_exists.
    listing_id = str(uuid.uuid4())
    async with owner_engine.begin() as conn:
        await _insert_review(conn, listing_id=listing_id)
    async with owner_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await _insert_review(conn, listing_id=listing_id)


async def test_duplicate_review_null_listing_conflicts(owner_engine: AsyncEngine) -> None:
    # NULLS NOT DISTINCT: without it, two NULL listing_ids would never collide
    # and the constraint would silently allow duplicate listing-less reviews.
    async with owner_engine.begin() as conn:
        await _insert_review(conn, listing_id=None)
    async with owner_engine.begin() as conn:
        with pytest.raises(IntegrityError):
            await _insert_review(conn, listing_id=None)


async def test_same_author_can_review_different_listings(owner_engine: AsyncEngine) -> None:
    # Guards the constraint scope: uniqueness is per (author, listing), not per author.
    async with owner_engine.begin() as conn:
        await _insert_review(conn, listing_id=str(uuid.uuid4()))
        await _insert_review(conn, listing_id=str(uuid.uuid4()))


async def test_tenant_cannot_read_other_tenants_reviews(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await _insert_review(conn, app_id="app-a")
        rows = (await conn.execute(text("SELECT rating FROM reviews"))).all()
        assert [r[0] for r in rows] == [5]

    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-b")
        rows = (await conn.execute(text("SELECT rating FROM reviews"))).all()
        assert rows == []


async def test_insert_with_other_tenants_app_id_is_rejected(app_engine: AsyncEngine) -> None:
    # The WITH CHECK half of the policy: a tenant cannot write into another
    # tenant's namespace (the read test above only proves USING).
    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        with pytest.raises(DBAPIError, match="row-level security"):
            await _insert_review(conn, app_id="app-b")
