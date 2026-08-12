"""Listing core — create, detail with actions resolution, patch.

Owner: P2. Owns `resolve_actions()` as the single shared helper — imported by
P3's search module, never re-implemented. Spec: POST /v1/listings
(Idempotency-Key REQUIRED), GET/PATCH /v1/listings/{id}.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from bazaar_api.generated.models import (
    Listing,
    ListingAction,
    ListingCreateRequest,
    ListingPatchRequest,
    ListingStatus,
)
from bazaar_api.middleware.idempotency import IdempotentRoute

router = APIRouter(prefix="/listings", tags=["listings"], route_class=IdempotentRoute)


def resolve_actions(
    *,
    listing_status: ListingStatus,
    seller_user_id: str,
    viewer_user_id: str | None,
    buyer_user_id: str | None = None,
    has_reviewed: bool = False,
) -> list[ListingAction] | None:
    """Shared helper — P2 owns, P3 imports. See OpenAPI Spec tab Actions table."""
    if viewer_user_id is None:
        return None
    if listing_status == ListingStatus.REMOVED:
        return []
    if listing_status == ListingStatus.SOLD:
        if buyer_user_id is not None and viewer_user_id == buyer_user_id and not has_reviewed:
            return [ListingAction.LEAVE_REVIEW]
        return []
    if viewer_user_id == seller_user_id:
        return [ListingAction.EDIT, ListingAction.MARK_SOLD, ListingAction.REMOVE]
    return [ListingAction.CONTACT]


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=Listing,
    operation_id="createListing",
    summary="Create a listing",
    tags=["listings"],
)
async def create_listing(
    body: ListingCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> Listing:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="POST /v1/listings — stub, implement in Week-2",
    )


@router.get(
    "/{listing_id}",
    response_model=Listing,
    operation_id="getListing",
    summary="Get listing detail",
    tags=["listings"],
)
async def get_listing(
    listing_id: str,
    viewer_user_id: Annotated[str | None, Query()] = None,
) -> Listing:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"GET /v1/listings/{listing_id} — stub",
    )


@router.patch(
    "/{listing_id}",
    response_model=Listing,
    operation_id="updateListing",
    summary="Update a listing (seller only)",
    tags=["listings"],
)
async def update_listing(
    listing_id: str,
    body: ListingPatchRequest,
) -> Listing:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"PATCH /v1/listings/{listing_id} — stub",
    )
