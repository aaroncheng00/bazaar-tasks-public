import hashlib
import hmac
import json
import logging
import re
import time
from typing import cast

from fastapi import Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import settings
from bazaar_api.db.redis import get_redis
from bazaar_api.db.session import session_factory
from bazaar_api.errors import (
    INVALID_SIGNATURE,
    MALFORMED_TIMESTAMP,
    MISSING_AUTH_HEADERS,
    REPLAY_DETECTED,
    STALE_TIMESTAMP,
    UNAUTHENTICATED,
    UNKNOWN_KEY,
    ApiError,
)

logger = logging.getLogger(__name__)

SIGNATURE_WINDOW_SECONDS = 300
# Nonce entries outlive the acceptance window so a signature replayed just
# inside the window is still caught as it ages out.
NONCE_TTL_SECONDS = 2 * SIGNATURE_WINDOW_SECONDS

HEADER_KEY = "x-bazaar-key"
HEADER_TIMESTAMP = "x-bazaar-timestamp"
HEADER_SIGNATURE = "x-bazaar-signature"

# Bound header lengths and charset to prevent resource exhaustion and
# log injection via attacker-controlled headers. key_id is attacker-controlled.
MAX_KEY_ID_LEN = 64
MAX_SIGNATURE_LEN = 128
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


def canonical_request(method: str, path: str, query: str, timestamp: str, body: bytes) -> bytes:
    """The five signed fields (Architecture §14 / API Surface Ownership).

    Query is included so a signature for ?category=a is not valid for
    ?category=b — the pre-§14 design signed body+timestamp only and was open
    to path/query substitution.

    CONTRACT (raw query, no canonicalisation): `query` is the raw query string
    exactly as sent (request.url.query). We deliberately do NOT sort or
    re-encode params, so ?a=1&b=2 and ?b=2&a=1 produce different signatures.
    Consequence: any client/proxy that reorders or re-encodes params breaks
    auth. The SDK must sign the identical bytes it puts on the wire. This is
    the documented contract — see the P3 note (search/browse signs the most
    params) before changing it.
    """
    body_digest = hashlib.sha256(body).hexdigest()
    return f"{method}\n{path}\n{query}\n{timestamp}\n{body_digest}".encode()


async def _resolve_key(key_id: str) -> tuple[str, str]:
    """Resolve a presented key_id to (secret, app_id). Fails closed to 401.

    Timing note: an unknown key returns here before any HMAC work, while a
    known key with a bad signature does the full HMAC + nonce round-trip — a
    timing oracle that distinguishes valid key_ids from invalid ones. Accepted
    for MVP: the nonce store must not be touched by unauthenticated callers,
    and key_ids are not secret (the secret is). Worth a constant-time lookup
    if key enumeration becomes a concern; do not "fix" it by moving the nonce
    write before verification. To properly mitigate, always perform the DB
    lookup with a sentinel key_id and constant-time dummy HMAC, not a 20-byte
    dummy hash — the DB SELECT with pgp_sym_decrypt dominates timing (ms) vs
    HMAC (micros).

    Length/charset validation is defense against resource exhaustion and log
    injection, not a timing-oracle fix.
    """
    # Validate key_id format early — bound resource usage for attacker-controlled header
    if not key_id or len(key_id) > MAX_KEY_ID_LEN or not _KEY_ID_RE.match(key_id):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, UNKNOWN_KEY, "unknown key")

    # DB is authoritative. bazaar_app has SELECT on api_keys by design (0002);
    # the secret is decrypted on demand with the env-held master key.
    async with session_factory()() as session:
        row = (
            await session.execute(
                text(
                    "SELECT app_id, pgp_sym_decrypt(secret_ciphertext, :master_key), revoked_at"
                    " FROM api_keys WHERE key_id = :key_id"
                ),
                {"master_key": settings.key_encryption_secret, "key_id": key_id},
            )
        ).first()
    if row is not None:
        app_id, secret, revoked_at = row[0], row[1], row[2]
        # Revoked and unknown share UNKNOWN_KEY: a caller learns nothing by
        # distinguishing them, and the code registry stays small.
        if revoked_at is not None:
            raise ApiError(status.HTTP_401_UNAUTHORIZED, UNKNOWN_KEY, "key revoked")
        if not secret or not isinstance(secret, str):
            raise ApiError(status.HTTP_401_UNAUTHORIZED, UNKNOWN_KEY, "unknown key")
        return secret, app_id
    # Env map is the dev seed ONLY: consulted when no DB row exists, so a
    # DB-revoked key can never fall through and stay live.
    record = settings.keys.get(key_id)
    if record is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, UNKNOWN_KEY, "unknown key")
    return record.secret, record.app_id


async def _resolve_provisioning_token(request: Request, token: str) -> str:
    """Validate a provisioning token: first-key bootstrap for a brand-new app.

    Scoped to exactly one route (POST /v1/apps/{app_id}/keys) — a bearer token
    must never authenticate anything else. Unlike HMAC secrets the token is
    presented directly, so it is stored as a sha256 hash and compared by hash.

    This VALIDATES ONLY. The claim (marking the token used) happens in the
    mint handler's transaction via bazaar_api.keys.mint_first_key, so a failed
    mint rolls the claim back instead of burning the token. Reads run as the
    owner role: bazaar_app has no grants on apps (see migration 0006).
    """
    path_app_id = request.path_params.get("app_id")
    if request.method != "POST" or path_app_id is None or not request.url.path.endswith("/keys"):
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            UNAUTHENTICATED,
            "provisioning token is only valid for first key issuance",
        )

    token_hash = hashlib.sha256(token.encode()).hexdigest()
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        predicates = {"app_id": path_app_id, "token_hash": token_hash}
        valid = (
            await conn.execute(
                text(
                    "SELECT 1 FROM apps"
                    " WHERE app_id = :app_id"
                    " AND provisioning_token_hash = :token_hash"
                    " AND provisioning_used_at IS NULL"
                    " AND provisioning_expires_at > now()"
                ),
                predicates,
            )
        ).first()
        if valid is None:
            # Retry of a lost response presents the same (now used) token, so
            # validity above fails before the idempotency layer is consulted.
            # Detect that exact case: hash matches this app, but already used.
            used = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM apps"
                        " WHERE app_id = :app_id"
                        " AND provisioning_token_hash = :token_hash"
                        " AND provisioning_used_at IS NOT NULL"
                    ),
                    predicates,
                )
            ).first()
        else:
            used = None
    await engine.dispose()

    if valid is None:
        if used is not None:
            await _replay_bootstrap_response(request, path_app_id)
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            UNAUTHENTICATED,
            "invalid, expired, or already-used provisioning token",
        )
    request.scope["bazaar.app_id"] = path_app_id
    request.scope["bazaar.provisioning"] = True
    request.scope["bazaar.provisioning_token_hash"] = token_hash
    return str(path_app_id)


async def _replay_bootstrap_response(request: Request, app_id: str) -> None:
    """Replay the stored first-mint response for a legitimate retry.

    Raises IdempotencyReplay when a stored response exists (same Idempotency-
    Key, same body); returns quietly otherwise, and the caller 401s. Expiry is
    deliberately not re-checked: the mint already happened, the client is just
    collecting the response it is owed.
    """
    # Local import: idempotency imports verify_signature from this module, so
    # a top-level import here would be circular.
    from bazaar_api.middleware.idempotency import (
        IdempotencyMismatch,
        IdempotencyReplay,
        _redis_key,
    )

    idem_key = request.headers.get("idempotency-key")
    if not idem_key:
        return
    # decode_responses=True on the client, so this is str (never bytes).
    existing = cast("str | None", await get_redis().get(_redis_key(app_id, request, idem_key)))
    if existing is None or existing.startswith("inflight:"):
        return
    record = json.loads(existing)
    body_hash = hashlib.sha256(await request.body()).hexdigest()
    if record.get("body_hash") != body_hash:
        raise IdempotencyMismatch
    raise IdempotencyReplay(record)


async def verify_signature(request: Request) -> str:
    """Resolve the caller's app_id from X-Bazaar-Key / -Timestamp / -Signature.

    The signature binds method, path, query, timestamp, and body, so a captured
    signature cannot be replayed against a different endpoint, query, or payload.
    A Redis nonce (the signature itself, per key) makes each signature single-use
    within the acceptance window.

    RETRY CONTRACT: because each signature is single-use, a client retrying a
    request MUST re-sign with a fresh timestamp (a retry reusing the original
    timestamp reproduces the original signature and is rejected as a replay
    before it can reach the idempotency layer). Keep Idempotency-Key stable
    across attempts; vary only the timestamp. Corollary for T283279748:
    idempotency replay must be keyed on Idempotency-Key, never on the signature.
    """
    # Bootstrap path: a one-time provisioning token (bzp_) authenticates the
    # FIRST key mint for a brand-new app, before any key exists to HMAC with.
    authorization = request.headers.get("authorization")
    if authorization and authorization.startswith("Bearer bzp_"):
        return await _resolve_provisioning_token(request, authorization.removeprefix("Bearer "))

    key_id = request.headers.get(HEADER_KEY)
    signature = request.headers.get(HEADER_SIGNATURE)
    timestamp = request.headers.get(HEADER_TIMESTAMP)
    if not key_id:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, MISSING_AUTH_HEADERS, "missing auth headers")

    # Bound signature length to prevent DoS via huge header stored as Redis nonce key
    if signature is not None and len(signature) > MAX_SIGNATURE_LEN:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, INVALID_SIGNATURE, "invalid signature")

    secret, app_id = await _resolve_key(key_id)

    # Stash identity on the ASGI scope so the OUTERMOST middleware can read it
    # at access-log time. The tenant ContextVar is set by an inner router
    # dependency and reset before the outer middleware regains control
    # (verified by probe — inner→outer ContextVar propagation does not survive
    # the dependency's finally). scope is the same mutable dict across the
    # whole request lifecycle, so writes here ARE visible to the outer
    # middleware afterward. Only app_id + key_id — never the secret, signature,
    # or Idempotency-Key.
    request.scope["bazaar.app_id"] = app_id
    request.scope["bazaar.key_id"] = key_id

    # Dev-only unsigned path. Hard-refused outside dev at startup (see
    # main.validate_dev_flags), so reaching here implies env == "dev". Even
    # skipped, the key resolved above to a real app_id and the request is
    # still tenant-scoped. Loud per request so a misconfigured dev box is obvious.
    if settings.dev_skip_hmac and settings.env == "dev":
        logger.warning("dev_skip_hmac: skipping HMAC verification for key_id=%s", key_id)
        return app_id

    if not signature or not timestamp:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, MISSING_AUTH_HEADERS, "missing auth headers")

    try:
        skew = abs(time.time() - int(timestamp))
    except ValueError:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, MALFORMED_TIMESTAMP, "malformed timestamp"
        ) from None
    if skew > SIGNATURE_WINDOW_SECONDS:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED, STALE_TIMESTAMP, "timestamp outside allowed window"
        )

    body = await request.body()
    expected = hmac.new(
        secret.encode(),
        canonical_request(request.method, request.url.path, request.url.query, timestamp, body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ApiError(status.HTTP_401_UNAUTHORIZED, INVALID_SIGNATURE, "invalid signature")

    # Consume the nonce AFTER verification so unauthenticated callers can't
    # fill Redis. SETNX: if this (key, signature) was already used, it's a replay.
    nonce_key = f"nonce:{key_id}:{signature}"
    was_fresh = await get_redis().set(nonce_key, "1", nx=True, ex=NONCE_TTL_SECONDS)
    if not was_fresh:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, REPLAY_DETECTED, "replay detected")

    return app_id
