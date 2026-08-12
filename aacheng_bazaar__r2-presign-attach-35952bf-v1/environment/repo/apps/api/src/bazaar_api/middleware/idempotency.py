"""Idempotency for POST requests (T283279748).

Keyed on the Idempotency-Key header — NEVER the signature. Signatures are
single-use (the auth nonce), so keying on them would make every legitimate
retry look like a fresh request.

Split into two halves because of where verified identity becomes available:

- idempotency_guard (dependency, PRE-check): runs inside routing, after
  verify_signature, so it has the verified app_id. A middleware cannot do
  this — middleware runs before routing, before the key is resolved. Checks
  Redis and either lets the request proceed (SETNX an in-flight marker) or
  short-circuits via the control exceptions below.

- IdempotentRoute (APIRoute subclass, POST-store): wraps the route handler so
  it can see the RESPONSE — dependencies cannot. On a 2xx it stores
  {status, body, body_hash} with a 24h TTL, overwriting the in-flight marker.
  On failure it deletes the marker so the client can retry after a 5xx —
  except for the three control exceptions, which must leave Redis untouched
  (a replay must stay replayable, a 409 marker must keep blocking).

Set route_class=IdempotentRoute on any router whose POSTs need idempotency.
include_router preserves each router's own route class (verified by probe on
FastAPI 0.141: routes are delegated via _IncludedRouter, not re-created).
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable, Coroutine
from typing import Any, cast

from fastapi import Depends, Request, Response, status
from fastapi.routing import APIRoute
from starlette.responses import JSONResponse

from bazaar_api.config import settings
from bazaar_api.db.redis import get_redis
from bazaar_api.errors import (
    IDEMPOTENCY_MISMATCH,
    REQUEST_IN_FLIGHT,
    VALIDATION_FAILED,
    ApiError,
    envelope_response,
)
from bazaar_api.middleware.auth_hmac import verify_signature

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_HEADER = "idempotency-key"
REPLAY_HEADER = "x-idempotency-replay"
# In-flight markers expire fast: they exist to block concurrent duplicates,
# and a crashed request must not brick the key for the full 24h.
IN_FLIGHT_TTL_SECONDS = 300

# Bound Idempotency-Key length and charset to prevent Redis key explosion
# and log injection. 64 chars matches request_id cap.
MAX_IDEMPOTENCY_KEY_LEN = 64
_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._\-]+$")

# Max stored response body to avoid Redis memory blowup (1 MB)
MAX_STORED_BODY_BYTES = 1024 * 1024


class IdempotencyReplay(Exception):
    """Control flow, not an error: a stored response exists — replay it."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record


class IdempotencyInFlight(Exception):
    """Same key is mid-execution elsewhere — 409."""


class IdempotencyMismatch(Exception):
    """Same key, different body — 409."""


def _redis_key(app_id: str, request: Request, idem_key: str) -> str:
    # Route TEMPLATE (e.g. /v1/listings/{id}), not the raw path, so the key is
    # stable per endpoint rather than per resource id.
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    return f"idem:{app_id}:{template}:{idem_key}"


async def idempotency_guard(request: Request, app_id: str = Depends(verify_signature)) -> None:
    """Pre-execution idempotency check. No-op unless POST + Idempotency-Key."""
    if request.method != "POST":
        return
    idem_key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not idem_key:
        return

    # Patched: validate length and charset — attacker-controlled header that
    # becomes part of Redis key and is echoed via replay path.
    idem_key = idem_key.strip()
    if not idem_key:
        return
    if len(idem_key) > MAX_IDEMPOTENCY_KEY_LEN or not _IDEMPOTENCY_KEY_RE.match(idem_key):
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            VALIDATION_FAILED,
            f"invalid {IDEMPOTENCY_KEY_HEADER}: must match "
            f"{_IDEMPOTENCY_KEY_RE.pattern} and be <= {MAX_IDEMPOTENCY_KEY_LEN} chars",
        )

    redis = get_redis()
    body_hash = hashlib.sha256(await request.body()).hexdigest()
    redis_key = _redis_key(app_id, request, idem_key)

    # Atomic claim: if we set the in-flight marker, we own this execution.
    claimed = await redis.set(redis_key, f"inflight:{body_hash}", nx=True, ex=IN_FLIGHT_TTL_SECONDS)
    if claimed:
        request.scope["bazaar.idem"] = {"redis_key": redis_key, "body_hash": body_hash}
        return

    # decode_responses=True on the client, so this is str (never bytes).
    existing = cast("str | None", await redis.get(redis_key))
    if existing is None:
        # Marker expired between SETNX and GET — treat as a fresh race; safest
        # answer is 409 (the caller retries and wins the claim).
        raise IdempotencyInFlight
    if existing.startswith("inflight:"):
        raise IdempotencyInFlight

    record = json.loads(existing)
    if record.get("body_hash") == body_hash:
        raise IdempotencyReplay(record)
    raise IdempotencyMismatch


class IdempotentRoute(APIRoute):
    """Stores successful responses against the in-flight marker from the guard."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def handler(request: Request) -> Response:
            # The guard's scope stash does NOT exist yet here — it is set by the
            # dependency DURING original(request). Read it after, never before.
            try:
                response = await original(request)
            except (IdempotencyReplay, IdempotencyInFlight, IdempotencyMismatch):
                raise  # control flow — preserve Redis state exactly as found
            except Exception:
                # Failed requests are not memoized: free the key for a retry.
                idem = request.scope.get("bazaar.idem")
                if idem is not None:
                    await get_redis().delete(idem["redis_key"])
                raise

            idem = request.scope.get("bazaar.idem")
            if idem is None:
                return response  # GET, no Idempotency-Key, or guard not applied

            body = getattr(response, "body", None)
            if 200 <= response.status_code < 300 and body is not None:
                if len(body) > MAX_STORED_BODY_BYTES:
                    # Too large to memoize safely — free key so client can retry.
                    # Semantics change: no longer idempotent for large bodies,
                    # but better than 500 with key stuck 300s. Log visible;
                    # consider 409 marker if API ever returns large bodies.
                    logger.warning(
                        "idempotency: body too large (%d bytes) for key %s "
                        "— not memoizing, retry will re-execute",
                        len(body),
                        idem["redis_key"],
                    )
                    await get_redis().delete(idem["redis_key"])
                    return response
                try:
                    decoded_body = body.decode()
                except UnicodeDecodeError:
                    # Previously raised -> 500 with key stuck 300s.
                    # Now free key and log.
                    logger.warning(
                        "idempotency: binary body for key %s "
                        "— not memoizing, retry will re-execute",
                        idem["redis_key"],
                    )
                    await get_redis().delete(idem["redis_key"])
                    return response
                record = {
                    "status": response.status_code,
                    "body": decoded_body,
                    "body_hash": idem["body_hash"],
                    # Preserve response headers (e.g. a 201's Location) so a
                    # replay returns the full original response, not a shell.
                    # content-length is excluded — it is recomputed on replay.
                    # Patched: also exclude set-cookie, authorization, etc. not needed
                    "headers": {
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() not in ("content-length", "set-cookie")
                    },
                }
                await get_redis().set(
                    idem["redis_key"], json.dumps(record), ex=settings.idempotency_ttl_seconds
                )
            else:
                # Non-2xx (or a streaming response with no materialized body):
                # not memoized, free the key.
                await get_redis().delete(idem["redis_key"])
            return response

        return handler


# --- Envelope handlers for the control exceptions -----------------------------


async def idempotency_replay_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, IdempotencyReplay)
    headers = dict(exc.record.get("headers", {}))
    content_type = headers.pop("content-type", "application/json")
    headers[REPLAY_HEADER] = "true"
    return Response(
        content=exc.record["body"],
        status_code=exc.record["status"],
        media_type=content_type,
        headers=headers,
    )


async def idempotency_in_flight_handler(request: Request, exc: Exception) -> JSONResponse:
    return envelope_response(
        REQUEST_IN_FLIGHT,
        "a request with this Idempotency-Key is still in progress",
        status.HTTP_409_CONFLICT,
    )


async def idempotency_mismatch_handler(request: Request, exc: Exception) -> JSONResponse:
    return envelope_response(
        IDEMPOTENCY_MISMATCH,
        "Idempotency-Key was already used with a different request body",
        status.HTTP_409_CONFLICT,
    )


def register_idempotency_handlers(app: Any) -> None:
    app.add_exception_handler(IdempotencyReplay, idempotency_replay_handler)
    app.add_exception_handler(IdempotencyInFlight, idempotency_in_flight_handler)
    app.add_exception_handler(IdempotencyMismatch, idempotency_mismatch_handler)
