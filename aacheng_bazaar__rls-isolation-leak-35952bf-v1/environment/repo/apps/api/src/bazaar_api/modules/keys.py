"""Self-serve key rotation (OD-1 follow-up).

Create and revoke are SEPARATE primitives — an atomic "rotate" call would
kill the old key before the new secret is deployed, reintroducing the
downtime the one-app-many-keys model exists to avoid. The flow is:
mint #2 → deploy at your pace → revoke #1.

Authorization is the pipeline itself: a valid HMAC from any active key of the
tenant proves the caller may manage that tenant's keys, so no admin token is
needed. Two guards on top:
  - path app_id must equal the authenticated tenant (can't touch other apps)
  - the presented key cannot revoke itself (403 forbidden — a permission
    rule, not a state conflict; forces mint-first hygiene. The
    only-key-leaked recovery path is the ops CLI, not this endpoint)

Writes run as the OWNER role via bazaar_api.keys: api_keys is control-plane
(no RLS by design) and read-only for the runtime role, so the /v1 tenant
session cannot serve these handlers.

Routes declare their spec'd error responses explicitly (drift guard,
T283279799): exceptions raised to the global handlers are otherwise
invisible to app.openapi(), leaving the published contract incomplete.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bazaar_api.errors import FORBIDDEN, NOT_FOUND, UNAUTHENTICATED, ApiError
from bazaar_api.generated.models import (
    ApiKeyInfo,
    ApiKeyList,
    ApiKeyRevoked,
    AppKeyCreated,
    ErrorEnvelope,
)
from bazaar_api.keys import mint_first_key, mint_key, revoke_key
from bazaar_api.middleware.idempotency import IdempotentRoute
from bazaar_api.middleware.tenant import tenant_session
from bazaar_api.middleware.tenant_context import current_app_id

# route_class is load-bearing: without it the idempotency guard claims the
# marker but the post-handler store never runs — every retry 409s. The route
# walk in tests/integration/test_errors.py enforces this on every router.
router = APIRouter(tags=["keys"], route_class=IdempotentRoute)

_AUTH_401: dict[str, object] = {
    "model": ErrorEnvelope,
    "description": "Bad/missing HMAC, stale timestamp, or replayed nonce",
}
_TENANT_403: dict[str, object] = {
    "model": ErrorEnvelope,
    "description": "Path app_id is not the authenticated tenant",
}


MAX_LIST_KEYS = 100
MAX_APP_ID_LEN = 128
MAX_KEY_ID_LEN = 64


def _require_own_app(app_id: str) -> None:
    # Patched: bound app_id length to prevent resource exhaustion via long path
    if not app_id or len(app_id) > MAX_APP_ID_LEN:
        raise ApiError(status.HTTP_403_FORBIDDEN, FORBIDDEN, "cannot manage keys for another app")
    if app_id != current_app_id():
        raise ApiError(status.HTTP_403_FORBIDDEN, FORBIDDEN, "cannot manage keys for another app")


@router.get(
    "/apps/{app_id}/keys",
    response_model=ApiKeyList,
    operation_id="listAppKeys",
    summary="List API keys (metadata only)",
    responses={401: _AUTH_401, 403: _TENANT_403},
)
async def list_keys(app_id: str, session: AsyncSession = Depends(tenant_session)) -> ApiKeyList:
    _require_own_app(app_id)
    # api_keys is SELECT-able for the runtime role, so the tenant session
    # serves this read; the WHERE clause does the scoping RLS would (this
    # table deliberately has none).
    # Patched: add LIMIT to prevent large result set DoS; newest first, bounded.
    result = await session.execute(
        text(
            "SELECT key_id, created_at, revoked_at FROM api_keys"
            " WHERE app_id = :app_id ORDER BY created_at DESC LIMIT :lim"
        ),
        {"app_id": app_id, "lim": MAX_LIST_KEYS},
    )
    return ApiKeyList(
        keys=[ApiKeyInfo(key_id=row[0], created_at=row[1], revoked_at=row[2]) for row in result]
    )


@router.post(
    "/apps/{app_id}/keys",
    status_code=status.HTTP_201_CREATED,
    response_model=AppKeyCreated,
    operation_id="createAppKey",
    summary="Issue an API key for a tenant",
    responses={
        401: _AUTH_401,
        404: {"model": ErrorEnvelope, "description": "No such app"},
        409: {
            "model": ErrorEnvelope,
            "description": "Idempotency-Key replayed with a different body",
        },
        429: {"model": ErrorEnvelope, "description": "Per-app rate limit exceeded"},
    },
)
async def create_key(
    app_id: str,
    request: Request,
    session: AsyncSession = Depends(tenant_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> AppKeyCreated:
    _require_own_app(app_id)
    if request.scope.get("bazaar.provisioning"):
        # First-key bootstrap: verify_signature validated the token; claim +
        # mint here, atomically, so a failed mint cannot burn the token.
        token_hash = request.scope["bazaar.provisioning_token_hash"]
        result = await mint_first_key(app_id, token_hash)
        if result is None:
            raise ApiError(
                status.HTTP_401_UNAUTHORIZED, UNAUTHENTICATED, "provisioning token claim failed"
            )
        key_id, secret = result
    else:
        key_id, secret = await mint_key(app_id)
    # mint_key/mint_first_key commit on their own owner-role connection before
    # returning, so the row is visible here; api_keys is SELECT-able for the
    # runtime role.
    created_at = (
        await session.execute(
            text("SELECT created_at FROM api_keys WHERE key_id = :key_id"),
            {"key_id": key_id},
        )
    ).scalar_one()
    return AppKeyCreated(key_id=key_id, secret=secret, created_at=created_at)


@router.post(
    "/apps/{app_id}/keys/{key_id}/revoke",
    response_model=ApiKeyRevoked,
    operation_id="revokeAppKey",
    summary="Revoke an API key (rotation)",
    responses={
        401: _AUTH_401,
        403: _TENANT_403,
        404: {
            "model": ErrorEnvelope,
            "description": "No active key with this key_id for this tenant",
        },
        409: {
            "model": ErrorEnvelope,
            "description": "The presenting key cannot revoke itself",
        },
    },
)
async def revoke(app_id: str, key_id: str, request: Request) -> ApiKeyRevoked:
    _require_own_app(app_id)
    if not key_id or len(key_id) > MAX_KEY_ID_LEN:
        raise ApiError(status.HTTP_404_NOT_FOUND, NOT_FOUND, "key not found")
    if key_id == request.scope.get("bazaar.key_id"):
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            FORBIDDEN,
            "cannot revoke the key presenting this request",
        )
    revoked_at = await revoke_key(app_id, key_id)
    if revoked_at is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, NOT_FOUND, "key not found")
    return ApiKeyRevoked(key_id=key_id, revoked_at=revoked_at)
