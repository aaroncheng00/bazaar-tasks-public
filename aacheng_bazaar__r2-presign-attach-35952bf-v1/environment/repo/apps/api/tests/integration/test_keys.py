import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import settings
from bazaar_api.keys import mint_key


@pytest.fixture(autouse=True)
async def clean_api_keys() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM api_keys"))
    await engine.dispose()


async def test_minted_secret_roundtrips_through_ciphertext() -> None:
    """The verification path's exact lookup: active key_id → app_id + secret."""
    key_id, secret = await mint_key("app-a")

    assert key_id.startswith("bzk_")
    assert secret.startswith("bzs_")

    engine = create_async_engine(settings.app_database_url)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT app_id, pgp_sym_decrypt(secret_ciphertext, :master_key)"
                    " FROM api_keys WHERE key_id = :key_id AND revoked_at IS NULL"
                ),
                {"master_key": settings.key_encryption_secret, "key_id": key_id},
            )
        ).one()
    await engine.dispose()

    assert row[0] == "app-a"
    assert row[1] == secret


async def test_plaintext_secret_is_not_stored() -> None:
    key_id, secret = await mint_key("app-a")

    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        ciphertext = (
            await conn.execute(
                text("SELECT secret_ciphertext FROM api_keys WHERE key_id = :key_id"),
                {"key_id": key_id},
            )
        ).scalar_one()
    await engine.dispose()

    assert secret.encode() not in ciphertext


async def test_runtime_role_cannot_mint_directly() -> None:
    """Locks in the 0002 REVOKE: bazaar_app is read-only on api_keys."""
    engine = create_async_engine(settings.app_database_url)
    with pytest.raises(DBAPIError):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO api_keys (key_id, app_id, secret_ciphertext)"
                    " VALUES ('bzk_forge', 'app-a', 'x')"
                )
            )
    await engine.dispose()
