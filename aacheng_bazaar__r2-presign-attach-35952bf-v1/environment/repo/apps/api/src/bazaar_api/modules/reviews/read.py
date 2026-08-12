"""Reviews read — history + aggregate. Owner: P1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from bazaar_api.generated.models import ReviewAggregate, ReviewPage
from bazaar_api.middleware.idempotency import IdempotentRoute

router = APIRouter(prefix="/reviews", tags=["reviews"], route_class=IdempotentRoute)


@router.get(
    "",
    response_model=ReviewPage,
    operation_id="listReviews",
    summary="List reviews for a subject",
    tags=["reviews"],
)
async def list_reviews(
    subject_user_id: Annotated[str, Query()],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ReviewPage:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GET /v1/reviews history — stub (P1)",
    )


@router.get(
    "/aggregate",
    response_model=ReviewAggregate,
    operation_id="getReviewAggregate",
    summary="Aggregate reputation for a subject",
    tags=["reviews"],
)
async def get_review_aggregate(
    subject_user_id: Annotated[str, Query()],
) -> ReviewAggregate:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="GET /v1/reviews/aggregate — stub (P1)",
    )
