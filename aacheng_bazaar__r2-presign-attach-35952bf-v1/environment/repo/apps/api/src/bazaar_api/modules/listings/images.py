"""Image upload — presign + attach-verify. Owner: S1."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, status

from bazaar_api.generated.models import ImageAttachRequest, ImageUpload, ImageUploadRequest, Listing
from bazaar_api.middleware.idempotency import IdempotentRoute

router = APIRouter(prefix="/listings", tags=["listings"], route_class=IdempotentRoute)


@router.post(
    "/{listing_id}/images",
    response_model=ImageUpload,
    operation_id="createImageUpload",
    summary="Step 1 of upload — request a presigned URL",
    tags=["listings"],
)
async def create_image_upload(
    listing_id: str,
    body: ImageUploadRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ImageUpload:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"POST /v1/listings/{listing_id}/images — stub (S1)",
    )


@router.post(
    "/{listing_id}/images/attach",
    response_model=Listing,
    operation_id="attachImage",
    summary="Step 2 of upload — verify and link the object",
    tags=["listings"],
)
async def attach_image(
    listing_id: str,
    body: ImageAttachRequest,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Listing:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"POST /v1/listings/{listing_id}/images/attach — stub (S1)",
    )
