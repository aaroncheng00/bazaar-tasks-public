import logging
import time

from fastapi import Depends, status
from starlette.types import ASGIApp, Receive, Scope, Send

from bazaar_api.config import settings
from bazaar_api.db.redis import get_redis
from bazaar_api.errors import RATE_LIMITED, UNAUTHENTICATED, ApiError
from bazaar_api.middleware.auth_hmac import verify_signature

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """No-op pass-through — slot held in the frozen middleware order.

    Per-tenant rate limiting does NOT live here. This middleware runs before
    routing, so it cannot see the verified app_id (that is resolved by a
    router dependency). Keying a limiter on the unverified X-Bazaar-Key header
    would let anyone burn a victim tenant's quota with requests that all 401 —
    key_ids are not secret. So per-tenant limiting is the `rate_limit`
    dependency below, keyed on the verified app_id; unrouted/unauthenticated
    requests are rejected cheaply (401) and edge flood protection is the infra
    layer's job (Architecture §2: "edge: TLS, rate-limit, request logging").

    This slot remains for a future in-app flood limiter (e.g. per-IP) that
    needs no tenant identity.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.app(scope, receive, send)


async def rate_limit(app_id: str = Depends(verify_signature)) -> None:
    """Per-tenant fixed-window limiter, keyed on the VERIFIED app_id.

    Runs as a router dependency (before tenant_session, so a 429 never opens
    a DB transaction). 429s raised here pass through the error-envelope
    handler inside RequestIdMiddleware, so they carry code/request_id and the
    X-Request-Id header like any other error.

    DEVIATION FROM ARCHITECTURE §9 (documented, not accidental): §9 specifies
    "per-app_id and per-endpoint token bucket." This is per-app_id ONLY, fixed
    window. Two accepted MVP consequences: (1) a fixed window permits a 2x
    burst straddling a window boundary; (2) one budget covers every endpoint,
    so a cheap GET and P3's expensive geo search draw from the same pool. If
    an endpoint needs its own budget, that's a §9 follow-up — do not assume it
    has one today.

    Patched: pipeline uses transaction=True for atomicity (MULTI/EXEC),
    TTL 70, guards against None count.
    """
    # app_id comes from verify_signature — verified tenant, not unverified header.
    # This prevents quota burn by unauthenticated callers.
    if not app_id or len(app_id) > 128:
        # Defensive: verify_signature should have validated, but fail closed
        # with a registered code if dependency cache is ever bypassed.
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            UNAUTHENTICATED,
            "unauthenticated",
        )
    now = time.time()
    window = int(now // 60)
    redis_key = f"rl:{app_id}:{window}"
    redis = get_redis()
    # transaction=True makes INCR+EXPIRE atomic via MULTI/EXEC, preventing
    # a TTL-less key if process dies between commands.
    try:
        async with redis.pipeline(transaction=True) as pipe:
            pipe.incr(redis_key)
            pipe.expire(redis_key, 70)  # window + slack; never outlive next window
            results = await pipe.execute()
            count = results[0] if results else None
    except Exception:
        # Fail open for availability: auth already uses Redis for nonce and
        # would have failed earlier if Redis is down, but rate_limit should not
        # brick the API if Redis flaps after auth. Emit warning so outage is
        # visible; healthz checks Redis and will alert.
        logger.warning("rate_limit Redis error, failing open", exc_info=True)
        count = 0

    if count is None:
        count = 0

    if count > settings.rate_limit_per_minute:
        # Fixed window, so the correct wait is to the next boundary — not a
        # guessed backoff. Architecture's own error example promises Retry-After.
        retry_after = 60 - int(now % 60)
        if retry_after <= 0:
            retry_after = 1
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            RATE_LIMITED,
            "rate limit exceeded",
            headers={"Retry-After": str(retry_after)},
        )
