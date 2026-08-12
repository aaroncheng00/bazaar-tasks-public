"""Reviews write — verified-buyer gate (S2, T282737802).

Eligibility is the recorded sale: listing.buyer_user_id == author_user_id,
else 403 review_not_eligible. The spec declares NO 404 for this op — missing,
malformed, and cross-tenant listings collapse into the same 403, so the
endpoint leaks nothing about which listings exist or sold. subject_user_id is
derived from listing.seller_user_id, never taken from the client: a verified
buyer posting against an arbitrary subject would poison the one trust signal
in the MVP.

One review per author per listing is enforced by the DB unique constraint
(UNIQUE NULLS NOT DISTINCT, migration 0004) mapped to 409 review_exists —
concurrent duplicates serialize on it the same way mark_sold serializes on
its row lock, so no SELECT-then-INSERT race can double-create. The aggregate
update the spec mentions ("Postgres-authoritative, Redis write-through") is
P1 read-model scope (listReviews/getReviewAggregate); nothing exists to
update until that lands.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bazaar_api.db.models import Listing as DbListing
from bazaar_api.db.models import Review as DbReview
from bazaar_api.errors import (
    INTERNAL_ERROR,
    REVIEW_EXISTS,
    REVIEW_NOT_ELIGIBLE,
    VALIDATION_FAILED,
    ApiError,
)
from bazaar_api.generated.models import ErrorEnvelope, Review, ReviewCreateRequest
from bazaar_api.middleware.idempotency import IdempotentRoute
from bazaar_api.middleware.tenant import tenant_session
from bazaar_api.middleware.tenant_context import current_app_id

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

router = APIRouter(prefix="/reviews", tags=["reviews"], route_class=IdempotentRoute)

_REVIEW_UNIQUE_CONSTRAINT = "uq_reviews_author_listing"


def _is_review_unique_violation(exc: IntegrityError) -> bool:
    """Match the (app_id, author, listing) unique violation by constraint name.

    The attribute lives on the RAW driver error: SQLAlchemy's asyncpg layer
    wraps it in an adapted DBAPI error (no constraint_name) before core wraps
    that in exc.orig — so walk the __cause__ chain rather than touching one
    fixed depth. Only this constraint maps to 409; anything else is a real
    500 and must not be masked.
    """
    error: BaseException | None = exc
    while error is not None:
        constraint: object = getattr(error, "constraint_name", None)
        if constraint is not None:
            return constraint == _REVIEW_UNIQUE_CONSTRAINT
        error = error.__cause__
    return False


MAX_LISTING_ID_LEN = 64
MAX_USER_ID_LEN = 128
MAX_BODY_LEN = 2000


def _parse_listing_ref(listing_ref: str) -> uuid.UUID | None:
    """Public id (lst_<uuid>) → bare uuid; malformed → None. The caller maps
    None to the same 403 as unknown/cross-tenant — this op has no 404 (no
    existence leak), unlike mark_sold, so this doesn't raise.

    Same parsing rule as listings/lifecycle._parse_listing_id; duplicated
    because that implementation lives on the mark_sold branch — converge on
    one helper once both PRs land.

    Patched: bound length to 64 to prevent DoS via huge id; reject control
    characters to prevent log injection via detail messages that echo the ref
    (even though this endpoint returns uniform 403, we keep detail safe).
    """
    if not listing_ref or len(listing_ref) > MAX_LISTING_ID_LEN:
        return None
    if _CONTROL_RE.search(listing_ref):
        return None
    if not listing_ref.startswith("lst_"):
        return None
    try:
        return uuid.UUID(listing_ref[4:])
    except ValueError:
        return None


def _review_response(review: DbReview, listing_id: uuid.UUID) -> Review:
    # Same guarded conversion as listings/lifecycle: reviews.app_id is Text in
    # DDL but format:uuid in the response contract; a slug tenant id is a
    # seed/config bug and must fail loudly with a pointer.
    try:
        app_id = uuid.UUID(review.app_id)
    except ValueError:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            INTERNAL_ERROR,
            "stored app_id is not a uuid — tenant provisioning/config bug",
        ) from None
    return Review(
        id=f"rev_{review.id}",
        app_id=app_id,
        subject_user_id=review.subject_user_id,
        author_user_id=review.author_user_id,
        listing_id=f"lst_{listing_id}",
        rating=review.rating,
        body=review.body,
        created_at=review.created_at,
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Review,
    operation_id="createReview",
    summary="Create a review",
    tags=["reviews"],
    # ApiError paths are invisible to app.openapi() unless declared — the
    # spec↔app drift guard compares per-op response codes. No 404 by spec.
    # Declared here (not via v1_router) so this PR stays independent of the
    # mark_sold PR, which adds the router-level 401.
    responses={
        401: {
            "model": ErrorEnvelope,
            "description": "Bad/missing HMAC, stale timestamp, or replayed nonce",
        },
        403: {
            "model": ErrorEnvelope,
            "description": "Listing not found, or author is not the recorded buyer",
        },
        409: {"model": ErrorEnvelope, "description": "Author already reviewed this listing"},
    },
)
async def create_review(
    body: ReviewCreateRequest,
    session: AsyncSession = Depends(tenant_session),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Review:
    # Patched: bound user_id lengths before DB work; generated model already
    # validates but double-bound here to prevent large payload in SELECT.
    if not body.author_user_id or len(body.author_user_id) > MAX_USER_ID_LEN:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            REVIEW_NOT_ELIGIBLE,
            "listing not found, or author is not the recorded buyer",
        )
    if body.body is not None and len(body.body) > MAX_BODY_LEN:
        # Body length should be enforced by generated model (max 2000) but
        # bound defensively here to avoid large JSONB insert.
        raise ApiError(
            status.HTTP_400_BAD_REQUEST,
            VALIDATION_FAILED,
            "body too long",
        )

    raw_listing_id = _parse_listing_ref(body.listing_id)
    listing = None
    if raw_listing_id is not None:
        listing = (
            (await session.execute(select(DbListing).where(DbListing.id == raw_listing_id)))
            .scalars()
            .one_or_none()
        )

    # One uniform 403 for malformed/missing/cross-tenant/not-the-buyer — the
    # spec's no-existence-leak contract for this op.
    if listing is None or listing.buyer_user_id != body.author_user_id:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            REVIEW_NOT_ELIGIBLE,
            "listing not found, or author is not the recorded buyer",
        )

    # Patched: ensure seller_user_id derived, bounded, and not attacker-controlled
    if not listing.seller_user_id or len(listing.seller_user_id) > MAX_USER_ID_LEN:
        raise ApiError(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            INTERNAL_ERROR,
            "stored seller_user_id invalid — data bug",
        )

    review = DbReview(
        app_id=current_app_id(),
        subject_user_id=listing.seller_user_id,  # derived — never client-supplied
        author_user_id=body.author_user_id,
        listing_id=listing.id,
        rating=body.rating,
        body=body.body,
    )
    session.add(review)
    try:
        # flush surfaces the unique violation inside the request transaction;
        # raising the 409 rolls it back via tenant_session's session.begin().
        await session.flush()
    except IntegrityError as exc:
        if _is_review_unique_violation(exc):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                REVIEW_EXISTS,
                "author_user_id has already reviewed this listing",
            ) from None
        raise  # any other constraint is a real 500 — don't mask it

    return _review_response(review, listing.id)
