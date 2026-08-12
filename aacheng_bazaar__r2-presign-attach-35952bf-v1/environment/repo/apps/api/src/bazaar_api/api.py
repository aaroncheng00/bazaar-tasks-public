"""The /v1 API surface.

Everything versioned hangs off `v1_router`. Adding a module router here is
the ONLY wiring step a new domain needs; main.py does not change.

`dependencies=[Depends(tenant_session)]` makes the whole tree fail-closed:
auth (HMAC via verify_signature) and the tenant-scoped RLS session run for
every /v1 request, including routes added later by handlers that forget to
ask for them. FastAPI's per-request dependency cache means a handler that
also declares `Depends(tenant_session)` gets the SAME session — one
transaction per request, not two.

NOTE ON MIDDLEWARE VS DEPENDENCY (T282737559): The task text says "Middleware
resolves the API key"; the implementation uses a router dependency. This is
intentional: dependencies inject the session cleanly (one transaction per
request) and the 501 catch-all ensures every /v1/* path matches. However,
router dependencies run AFTER routing — unlike ASGI middleware, which runs
before. Consequence: ASGI middlewares (RateLimitMiddleware, etc.) cannot see
the verified app_id because it hasn't been resolved yet.

RESOLUTION (T283279748): anything needing the verified tenant lives HERE, in
the dependency chain — not in middleware. The order below is deliberate:
  1. rate_limit       — 429 before any DB work; keyed on verified app_id
  2. idempotency_guard — replay/409 before opening a transaction
  3. tenant_session   — opens the RLS transaction (last, so rejects skip it)
verify_signature runs once (FastAPI caches it across all three). The frozen
ASGI middleware order in main.py is unchanged by this.
"""

from fastapi import APIRouter, Depends, Request, status

from bazaar_api.errors import NOT_IMPLEMENTED, ApiError
from bazaar_api.generated.models import ErrorEnvelope
from bazaar_api.middleware.idempotency import IdempotentRoute, idempotency_guard
from bazaar_api.middleware.rate_limit import rate_limit
from bazaar_api.middleware.tenant import tenant_session
from bazaar_api.modules import keys
from bazaar_api.modules.listings import crud, images, lifecycle, search
from bazaar_api.modules.reviews import read, write

v1_router = APIRouter(
    prefix="/v1",
    dependencies=[Depends(rate_limit), Depends(idempotency_guard), Depends(tenant_session)],
    route_class=IdempotentRoute,
    # Every /v1 route authenticates, so the shared 401 is documented once at
    # the router (FastAPI merges it into every route's OpenAPI entry). Domain
    # errors (403/404/409) are declared per handler — see listings/lifecycle.
    responses={
        401: {
            "model": ErrorEnvelope,
            "description": "Bad/missing HMAC, stale timestamp, or replayed nonce",
        },
    },
)

v1_router.include_router(keys.router)
v1_router.include_router(crud.router)
v1_router.include_router(search.router)
v1_router.include_router(images.router)
v1_router.include_router(lifecycle.router)
v1_router.include_router(write.router)
v1_router.include_router(read.router)


@v1_router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    # Internal 501 catch-all, not public surface: excluded from the schema (it
    # also emitted duplicate operation ids, one per method, on app.openapi()).
    include_in_schema=False,
)
async def _not_implemented(request: Request, path: str) -> None:
    """Catch-all for /v1 surface that has no handler yet.

    A registered route 404s when no handler matches, but an UNMATCHED path
    under /v1 would also 404 — indistinguishable from "not implemented." This
    catch-all is routed, authenticated, and tenant-scoped like any real route,
    so unimplemented surface fails loudly as 501 instead of silently 200ing
    once a handler file exists but its routes aren't written. It is removed
    once the /v1 surface is fully populated.

    ORDER MATTERS: this must stay registered AFTER the module routers above.
    FastAPI matches routes in registration order, so a specific module route
    wins over this wildcard. Register the catch-all first and it would shadow
    every real /v1 route.
    """
    raise ApiError(
        status.HTTP_501_NOT_IMPLEMENTED,
        NOT_IMPLEMENTED,
        f"no handler for {request.method} /v1/{path}",
    )
