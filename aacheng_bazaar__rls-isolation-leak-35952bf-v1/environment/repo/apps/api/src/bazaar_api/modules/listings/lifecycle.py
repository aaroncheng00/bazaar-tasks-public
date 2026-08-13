"""Listing lifecycle — mark_sold (S2, T283279728) + remove (P2, stub)."""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bazaar_api.db.models import Listing as DbListing
from bazaar_api.errors import (
    INTERNAL_ERROR,
    LISTING_ALREADY_SOLD,
    LISTING_NOT_FOUND,
    SELLER_ONLY,
    VALIDATION_FAILED,
    ApiError,
)
from bazaar_api.generated.models import (
    Category,
    Condition,
    Currency,
    ErrorEnvelope,
    Listing,
    ListingStatus,
    MarkSoldRequest,
    RemoveRequest,
)
from bazaar_api.middleware.idempotency import IdempotentRoute
from bazaar_api.middleware.tenant import tenant_session

router = APIRouter(prefix="/listings", tags=["listings"], route_class=IdempotentRoute)


MAX_LISTING_ID_LEN = 64
MAX_USER_ID_LEN = 128
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_ref(ref: str) -> str:
    """Truncate to 50 and replace control chars with '?' to prevent log injection."""
    truncated = ref[:50] if len(ref) > 50 else ref
    return _CONTROL_RE.sub("?", truncated)


def _parse_listing_id(listing_ref: str) -> uuid.UUID:
    """Public id (lst_<uuid>) → bare uuid. Malformed is 404, not 400 — the same
    no-existence-leak contract as an unknown id (the spec's NotFound example
    itself uses a non-uuid id).

    Patched: bound length to 64 to prevent resource exhaustion; sanitize ref
    for error messages to prevent log injection via control characters.
    """
    safe_ref = _sanitize_ref(listing_ref)
    not_found = ApiError(
        status.HTTP_404_NOT_FOUND,
        LISTING_NOT_FOUND,
        f"No listing {safe_ref} for this app.",
    )
    if not listing_ref or len(listing_ref) > MAX_LISTING_ID_LEN:
        raise not_found
    if not listing_ref.startswith("lst_"):
        raise not_found
    try:
        return uuid.UUID(listing_ref[4:])
    except ValueError:
        raise not_found from None


def _require_seller(row: DbListing, acting_user_id: str) -> None:
    # Length is validated at handler entry with 400; mismatch is 403 seller_only
    if row.seller_user_id != acting_user_id:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            SELLER_ONLY,
            "acting_user_id does not match the listing's seller_user_id.",
        )


def _listing_response(row: DbListing) -> Listing:
    # listings.app_id is Text but the response contract is format:uuid. Prod
    # tenants get uuid app_ids from provisioning; a slug (dev KEYS seed, ops
    # CLI mint) is a data/config bug — fail loudly with a pointer rather than
    # a bare ValueError surfacing as an unactionable 500.
    try:
        app_id = uuid.UUID(row.app_id)
    except ValueError:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            INTERNAL_ERROR,
            "stored app_id is not a uuid — tenant provisioning/config bug",
        ) from None
    # image_urls: public-URL derivation lands with the images module (S1);
    # empty while image_keys is empty, index-aligned per spec. actions/distance_km
    # stay None — mark_sold has no viewer_user_id param and is never geo-filtered.
    return Listing(
        id=f"lst_{row.id}",
        app_id=app_id,
        seller_user_id=row.seller_user_id,
        title=row.title,
        description=row.description,
        price_cents=row.price_cents,
        currency=Currency(row.currency),
        category=Category(row.category),
        condition=Condition(row.condition),
        status=ListingStatus(row.status),
        lat=row.lat,
        lng=row.lng,
        image_keys=list(row.image_keys),
        image_urls=[],
        buyer_user_id=row.buyer_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.post(
    "/{listing_id}/mark_sold",
    response_model=Listing,
    operation_id="markListingSold",
    summary="Mark a listing sold and record the buyer",
    tags=["listings"],
    # ApiError paths are raised to the global handler and are therefore
    # invisible to app.openapi() — declare them or the operation documents
    # only 200 and the spec↔app drift guard (and the SDK) sees a lie.
    # The shared 401 is declared once on v1_router (api.py).
    responses={
        403: {"model": ErrorEnvelope, "description": "Not the listing's seller"},
        404: {"model": ErrorEnvelope, "description": "Missing or cross-tenant listing"},
        409: {"model": ErrorEnvelope, "description": "Already sold to another buyer / removed"},
    },
)
async def mark_listing_sold(
    listing_id: str,
    body: MarkSoldRequest,
    session: AsyncSession = Depends(tenant_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Listing:
    """Sets status=sold and records buyer_user_id — the verified interaction
    that later gates review eligibility.

    One atomic conditional UPDATE: the row matches only while active OR already
    sold to THIS buyer. Concurrent marks naming different buyers serialize on
    the row lock — the loser's predicate no longer matches, so it falls through
    to 409 instead of overwriting. A same-buyer retry re-matches the sold row,
    which is what makes the operation naturally idempotent rather than relying
    on the Idempotency-Key replay layer alone.

    A 0-row UPDATE is ambiguous, so a follow-up SELECT in the same RLS-scoped
    transaction distinguishes missing/cross-tenant (404) from
    sold-to-another-buyer/removed (409). The seller check runs before either
    outcome; raising there rolls the UPDATE back, so a non-seller's write never
    persists.
    """
    # Preserve 404 precedence: parse listing_id before any body validation that
    # could 400/403. Previously long buyer_user_id caused 403 before 404.
    raw_id = _parse_listing_id(listing_id)

    # Validate body user_ids — 400 for length/empty, not 403 fabricated authz
    if not body.buyer_user_id or len(body.buyer_user_id) > MAX_USER_ID_LEN:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            VALIDATION_FAILED,
            "buyer_user_id too long or empty",
        )
    if not body.acting_user_id or len(body.acting_user_id) > MAX_USER_ID_LEN:
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            VALIDATION_FAILED,
            "acting_user_id too long or empty",
        )

    stmt = (
        update(DbListing)
        .where(DbListing.id == raw_id)
        .where(
            or_(
                DbListing.status == ListingStatus.ACTIVE.value,
                and_(
                    DbListing.status == ListingStatus.SOLD.value,
                    DbListing.buyer_user_id == body.buyer_user_id,
                ),
            )
        )
        .values(status=ListingStatus.SOLD.value, buyer_user_id=body.buyer_user_id)
        .returning(DbListing)
    )
    row = (await session.execute(stmt)).scalars().one_or_none()

    if row is None:
        existing = (
            (await session.execute(select(DbListing).where(DbListing.id == raw_id)))
            .scalars()
            .one_or_none()
        )
        if existing is None:
            safe_ref = _sanitize_ref(listing_id)
            raise ApiError(
                status.HTTP_404_NOT_FOUND,
                LISTING_NOT_FOUND,
                f"No listing {safe_ref} for this app.",
            )
        _require_seller(existing, body.acting_user_id)
        # removed → LISTING_ALREADY_SOLD is spec-mandated (spec text: "already
        # sold to a different buyer, or removed" → 409; the a6ad93f split).
        # The code saying "sold" for a removed listing is a known spec smell —
        # for the spec owner to resolve. Do NOT unilaterally 404 here: that
        # IS the spec drift the guard exists to catch.
        safe_ref = _sanitize_ref(listing_id)
        detail = (
            f"Listing {safe_ref} is removed."
            if existing.status == ListingStatus.REMOVED.value
            else f"Listing {safe_ref} is already sold to another buyer."
        )
        raise ApiError(status.HTTP_409_CONFLICT, LISTING_ALREADY_SOLD, detail)

    # INVARIANT: this raise must run BEFORE any commit. The authz safety of
    # update-then-authorize rests entirely on tenant_session's session.begin()
    # rolling back on exception. If this handler ever commits internally (or
    # the dependency stops using session.begin()), a non-seller's sale would
    # persist. Keep the check strictly before the return.
    _require_seller(row, body.acting_user_id)
    return _listing_response(row)


@router.post(
    "/{listing_id}/remove",
    response_model=Listing,
    operation_id="removeListing",
    summary="Remove a listing",
    tags=["listings"],
)
async def remove_listing(
    listing_id: str,
    body: RemoveRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Listing:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"POST /v1/listings/{listing_id}/remove — stub (P2)",
    )
