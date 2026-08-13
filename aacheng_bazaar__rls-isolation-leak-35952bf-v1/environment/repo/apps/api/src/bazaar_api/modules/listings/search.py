"""Browse/search — GET /v1/listings. Owner: P3. Unified endpoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi import status as http_status

from bazaar_api.generated.models import Category, Condition, ListingPage, ListingStatus, SortOrder
from bazaar_api.middleware.idempotency import IdempotentRoute
from bazaar_api.modules.listings.crud import resolve_actions  # noqa: F401

router = APIRouter(prefix="/listings", tags=["listings"], route_class=IdempotentRoute)


@router.get(
    "",
    response_model=ListingPage,
    operation_id="browseListings",
    summary="Browse / search listings",
    tags=["listings"],
)
async def browse_listings(
    lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    lng: Annotated[float | None, Query(ge=-180, le=180)] = None,
    radius_km: Annotated[float | None, Query(gt=0, le=50)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    category: Annotated[Category | None, Query()] = None,
    condition: Annotated[Condition | None, Query()] = None,
    sort: Annotated[SortOrder | None, Query()] = None,
    seller_user_id: Annotated[str | None, Query()] = None,
    status: Annotated[ListingStatus | None, Query()] = None,
    viewer_user_id: Annotated[str | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ListingPage:
    raise HTTPException(
        status_code=http_status.HTTP_501_NOT_IMPLEMENTED,
        detail="GET /v1/listings browse/search — stub, search module (P3)",
    )
