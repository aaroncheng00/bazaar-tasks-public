import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
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
async def clean_docs(owner_engine: AsyncEngine) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL bazaar.app_id = ''"))
        await conn.execute(text("DELETE FROM docs"))


async def _set_tenant(conn, app_id: str) -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text("SELECT set_config('bazaar.app_id', :app_id, true)"),
        {"app_id": app_id},
    )


async def test_tenant_cannot_read_other_tenants_rows(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await conn.execute(text("INSERT INTO docs (app_id, payload) VALUES ('app-a', 'secret-a')"))
        rows = (await conn.execute(text("SELECT payload FROM docs"))).all()
        assert [r[0] for r in rows] == ["secret-a"]

    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-b")
        rows = (await conn.execute(text("SELECT payload FROM docs"))).all()
        assert rows == []


async def test_insert_with_other_tenants_app_id_is_rejected(app_engine: AsyncEngine) -> None:
    from sqlalchemy.exc import DBAPIError

    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        with pytest.raises(DBAPIError):
            await conn.execute(
                text("INSERT INTO docs (app_id, payload) VALUES ('app-b', 'forged')")
            )


async def test_unset_tenant_sees_nothing(
    owner_engine: AsyncEngine, app_engine: AsyncEngine
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(text("SET LOCAL bazaar.app_id = ''"))
        await conn.execute(text("INSERT INTO docs (app_id, payload) VALUES ('app-a', 'secret-a')"))

    async with app_engine.begin() as conn:
        rows = (await conn.execute(text("SELECT payload FROM docs"))).all()
        assert rows == []


async def test_tenant_setting_does_not_leak_across_transactions(app_engine: AsyncEngine) -> None:
    async with app_engine.begin() as conn:
        await _set_tenant(conn, "app-a")
        await conn.execute(
            text("INSERT INTO docs (app_id, payload) VALUES ('app-a', :p)"),
            {"p": f"doc-{uuid.uuid4()}"},
        )

    # New transaction, no SET LOCAL: the GUC from the previous transaction
    # must be gone, so even app-a's own row is invisible.
    async with app_engine.begin() as conn:
        rows = (await conn.execute(text("SELECT payload FROM docs"))).all()
        assert rows == []
