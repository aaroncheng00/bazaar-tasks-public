# R2 image-upload pipeline — presign + attach-verify + orphan reaper

## Context

Bazaar is a headless FastAPI marketplace API (P2P). All `/v1` routes are HMAC-authenticated (`X-Bazaar-Key` / `Timestamp` / `Signature`, 300s skew, Redis single-use nonce), tenant-scoped via `current_app_id()` + Postgres RLS (`FORCE RLS` on `listings`), and idempotent via `Idempotency-Key` header using `IdempotentRoute`.

On base commit `35952bfad071179dece536ae828761d9e2883162`, `apps/api/src/bazaar_api/modules/listings/images.py` is stubbed to 501 for both:
- `POST /v1/listings/{listing_id}/images` — request upload URL
- `POST /v1/listings/{listing_id}/images/attach` — verify and link

Real behavior is in `spec/openapi.yaml`: presign takes `ImageUploadRequest{acting_user_id, content_type, content_length}` and returns `ImageUpload{upload_url, method, image_key, expires_in}`; attach takes `ImageAttachRequest{acting_user_id, image_key}` and returns `Listing` with `image_keys` appended.

R2 is Cloudflare R2, locally emulated by Minio (`R2_ENDPOINT`, `R2_BUCKET`, etc. from `.env.example`).

## Task

Implement the two handlers replacing the 501 stubs, plus `reap_orphans()` helper, in `apps/api/src/bazaar_api/modules/listings/images.py`.

**Requirements:**

1. **Tenant isolation:** `listing_id` format is `lst_<uuid>`. Invalid format or unknown id → 404 `listing_not_found` (no leak). All DB access must go through the RLS-scoped session (`tenant_session` dependency). The authenticated `app_id` from HMAC must match the listing's `app_id` — cross-tenant access must be 404.

2. **Seller-only:** `acting_user_id` from body must equal listing's `seller_user_id`, else 403 `seller_only`. `acting_user_id` is body field, never header.

3. **Presign validation:** Allow only `image/jpeg`, `image/png`, `image/webp` and `content_length` in `[1, 10MiB]` else 400 `validation_failed`. If listing is not `active` (sold/removed) → 409 `listing_already_sold`.

4. **Key namespace:** Generated `image_key` must be namespaced by tenant to prevent guessing — include `app_id` and `listing_id` plus a random component and proper file extension.

5. **Presigned URL:** Return `method=PUT`, `expires_in=900`, and a presigned PUT URL for the generated key (boto3 if R2 config present, otherwise a deterministic fallback). Persist enough pending metadata for attach verification and the reaper to work (TTL a couple days).

6. **Attach-verify:** `image_key` must be namespaced to the requesting app/listing, else 404. Verify listing exists and seller check as above. Determine actual content-type/size of the uploaded object — try R2 `head_object` if client available, otherwise fall back to pending metadata. If no object found → 404. If actual type not allowed or size >10MiB → 400. On success, append (not overwrite) the key to `listings.image_keys` (JSONB) and return the updated `Listing` with `image_urls` derived from keys.

7. **Idempotency:** Router already uses `IdempotentRoute`. Same `Idempotency-Key` + same body must replay original response, not allocate a new key.

8. **Orphan reaper:** `async def reap_orphans() -> int` scans pending uploads, collects referenced keys from `SELECT image_keys FROM listings`, deletes pending older than 24h that are not referenced and deletes the R2 object if possible. Return count.

## Constraints

- Only modify `apps/api/src/bazaar_api/modules/listings/images.py`.
- Preserve `IdempotentRoute` on router.
- Use `current_app_id()` for tenant, not header parsing.
- `image_keys` must be appended, never overwritten.

## Out of scope

- Real R2 bucket creation — Minio is local fake. Tests may mock HEAD or inject mismatch via pending metadata.
- Frontend.

## Acceptance

- Presign returns 200 with key prefixed by `{app_id}/listings/{listing_id}/`, method PUT, expires 900
- Attach with mismatched actual type → 400, with correct → 200 and `image_keys` appended (len 1→2)
- Cross-tenant presign → 404, seller mismatch → 403, sold listing → 409 (if implemented)
- Same idempotency key replay returns same `image_key`
- Reaper deletes only unattached >24h pending
