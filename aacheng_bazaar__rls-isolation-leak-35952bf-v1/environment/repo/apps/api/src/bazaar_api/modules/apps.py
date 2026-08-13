"""Tenant signup (POST /v1/apps) — the only unauthenticated route under /v1.

Mounted OUTSIDE v1_router in main.py: the fail-closed tenant_session
dependency requires a key that does not exist yet. Per-tenant rate limiting
can't apply (no verified app_id), so flood protection here is the edge/infra
layer's job (see RateLimitMiddleware's docstring).

Bootstrap flow: signup returns app_id + a one-time provisioning token
(bzp_, 15-minute TTL, shown once, stored as a sha256 hash). The token
authenticates the FIRST POST /v1/apps/{app_id}/keys via
Authorization: Bearer — see middleware/auth_hmac.verify_signature. Every key
after that signs normally.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from bazaar_api.config import settings
from bazaar_api.generated.models import App, AppCreateRequest, ErrorEnvelope
from bazaar_api.middleware.idempotency import IdempotentRoute

PROVISIONING_TTL_MINUTES = 15

router = APIRouter(route_class=IdempotentRoute, tags=["apps"])


@router.post(
    "/apps",
    operation_id="createApp",
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {
            "model": ErrorEnvelope,
            "description": "Idempotency-Key replayed with a different body",
        },
        429: {"model": ErrorEnvelope, "description": "Rate limit exceeded"},
    },
)
async def signup(
    body: AppCreateRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> App:
    app_id = str(uuid.uuid4())
    token = "bzp_" + secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + timedelta(minutes=PROVISIONING_TTL_MINUTES)

    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        created_at = (
            await conn.execute(
                text(
                    "INSERT INTO apps (app_id, name, owner_email, provisioning_token_hash,"
                    " provisioning_expires_at)"
                    " VALUES (:app_id, :name, :owner_email, :token_hash, :expires_at)"
                    " RETURNING created_at"
                ),
                {
                    "app_id": app_id,
                    "name": body.name,
                    "owner_email": body.owner_email,
                    "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                    "expires_at": expires_at,
                },
            )
        ).scalar_one()
    await engine.dispose()

    return App(
        app_id=uuid.UUID(app_id),
        name=body.name,
        provisioning_token=token,
        created_at=created_at,
    )
