"""API key issuance CLI (OD-1).

Minting connects as the OWNER role — the runtime role (bazaar_app) is
read-only on api_keys by design (see migration 0002). The plaintext secret is
printed exactly once; only pgcrypto ciphertext persists server-side.

Usage:
    uv run python -m bazaar_api.keys create --app app-a
"""

import argparse
import asyncio
import secrets
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import settings

KEY_ID_PREFIX = "bzk_"
SECRET_PREFIX = "bzs_"


def generate_key_id() -> str:
    # 9 bytes ~72 bits entropy; token_urlsafe(9) yields 12 base64url chars
    raw = secrets.token_urlsafe(9)
    # Defensive: ensure CSPRNG did not return truncated output
    if len(raw) < 12:
        raise RuntimeError("generated key_id too short — CSPRNG failure")
    return KEY_ID_PREFIX + raw


def generate_secret() -> str:
    # 32 bytes ~256 bits entropy; token_urlsafe(32) yields 43 base64url chars.
    # secrets.token_urlsafe uses os.urandom CSPRNG.
    raw = secrets.token_urlsafe(32)
    # token_urlsafe(32) should be 43 chars; fail fast if shorter
    if len(raw) < 43:
        raise RuntimeError("generated secret too short — CSPRNG failure")
    return SECRET_PREFIX + raw


async def mint_key(app_id: str) -> tuple[str, str]:
    """Insert one active key for app_id; return (key_id, plaintext secret)."""
    if not app_id or len(app_id) > 128:
        raise ValueError("invalid app_id length")
    key_id = generate_key_id()
    secret = generate_secret()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO api_keys (key_id, app_id, secret_ciphertext)"
                    " VALUES (:key_id, :app_id, pgp_sym_encrypt(:secret, :master_key))"
                ),
                {
                    "key_id": key_id,
                    "app_id": app_id,
                    "secret": secret,
                    "master_key": settings.key_encryption_secret,
                },
            )
            return key_id, secret
    finally:
        await engine.dispose()


async def mint_first_key(app_id: str, token_hash: str) -> tuple[str, str] | None:
    """Claim the app's provisioning token and mint its first key, atomically.

    Returns (key_id, secret), or None if the claim matched nothing (token
    used, expired, or hash mismatch) — the caller maps None to 401. The claim
    UPDATE carries the full predicate set, so concurrent first-mint requests
    cannot both succeed; and because claim + insert share one transaction, a
    failed mint rolls the claim back — the token is NOT burned by failure.

    Patched: add length bounds to prevent resource exhaustion via long ids.
    """
    if not app_id or len(app_id) > 128:
        raise ValueError("invalid app_id length")
    if not token_hash or len(token_hash) > 512:
        raise ValueError("invalid token_hash length")
    key_id = generate_key_id()
    secret = generate_secret()
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            claimed = (
                await conn.execute(
                    text(
                        "UPDATE apps SET provisioning_used_at = now()"
                        " WHERE app_id = :app_id"
                        " AND provisioning_token_hash = :token_hash"
                        " AND provisioning_used_at IS NULL"
                        " AND provisioning_expires_at > now()"
                        " RETURNING app_id"
                    ),
                    {"app_id": app_id, "token_hash": token_hash},
                )
            ).scalar_one_or_none()
            if claimed is None:
                return None
            await conn.execute(
                text(
                    "INSERT INTO api_keys (key_id, app_id, secret_ciphertext)"
                    " VALUES (:key_id, :app_id, pgp_sym_encrypt(:secret, :master_key))"
                ),
                {
                    "key_id": key_id,
                    "app_id": app_id,
                    "secret": secret,
                    "master_key": settings.key_encryption_secret,
                },
            )
            return key_id, secret
    finally:
        await engine.dispose()


async def revoke_key(app_id: str, key_id: str) -> datetime | None:
    """Soft-revoke one active key; return its revoked_at, or None if no match.

    Soft: the row stays for audit. Scoped by app_id because api_keys has no
    RLS (control-plane) — the app_id always comes from the verified tenant,
    never from request input alone.
    """
    if not app_id or not key_id:
        raise ValueError("app_id and key_id required")
    if len(app_id) > 128 or len(key_id) > 64:
        raise ValueError("id length exceeds bound")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as conn:
            revoked_at = (
                await conn.execute(
                    text(
                        "UPDATE api_keys SET revoked_at = now()"
                        " WHERE key_id = :key_id AND app_id = :app_id AND revoked_at IS NULL"
                        " RETURNING revoked_at"
                    ),
                    {"key_id": key_id, "app_id": app_id},
                )
            ).scalar_one_or_none()
    finally:
        await engine.dispose()
    return revoked_at


def main() -> None:
    parser = argparse.ArgumentParser(prog="bazaar-keys")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="mint a new API key for an app")
    create.add_argument("--app", required=True, help="app_id the key belongs to")
    args = parser.parse_args()

    if args.command == "create":
        key_id, secret = asyncio.run(mint_key(args.app))
        print(f"key_id: {key_id}")
        print(f"secret: {secret}")
        print()
        print("Store the secret somewhere safe now (e.g. a secrets manager). It is")
        print("shown only once — Bazaar keeps only pgcrypto ciphertext and cannot")
        print("display or recover the plaintext after this.")


if __name__ == "__main__":
    main()
