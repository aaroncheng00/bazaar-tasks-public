# R2 image-upload pipeline — presign + attach-verify + orphan reaper

## Context

Bazaar is a headless FastAPI marketplace API (P2P). All `/v1` routes are HMAC-authenticated via `X-Bazaar-Key` / `X-Bazaar-Timestamp` / `X-Bazaar-Signature` (300s window, Redis single-use nonce), tenant-scoped via `current_app_id()` + Postgres RLS (`FORCE ROW LEVEL SECURITY`, `USING` + `WITH CHECK` `current_setting('bazaar.app_id', true)`), and idempotent via `Idempotency-Key` (template key `{app_id}:{hash(body)}`).

On base commit `35952bfad071179dece536ae828761d9e2883162`, `apps/api/src/bazaar_api/modules/listings/images.py` is stubbed to 501 for both:
- `POST /v1/listings/{listing_id}/images` — Step 1 presign
- `POST /v1/listings/{listing_id}/images/attach` — Step 2 verify+link

Real behavior is specced in `spec/openapi.yaml`: `ImageUploadRequest{acting_user_id, content_type, content_length}` (jpeg/png/webp, max 10MiB) → `ImageUpload{upload_url, method=PUT, image_key, expires_in=900}`; `ImageAttachRequest{acting_user_id, image_key}` → `Listing` with appended `image_keys`.

R2 is Cloudflare R2, locally faked by Minio (`R2_ENDPOINT=http://localhost:9000`, `R2_BUCKET=bazaar-media`, `R2_ACCESS_KEY_ID=minio`, `R2_SECRET_ACCESS_KEY=minio123` from `.env.example` — note these have no `BAZAAR_` prefix per comment). Bucket keys must be namespaced per tenant.

## Task

Implement the two handlers in `apps/api/src/bazaar_api/modules/listings/images.py` replacing the 501 stubs, plus `reap_orphans()` helper.

**Requirements (observable contract):**

1. **Tenant isolation:** `listing_id` is `lst_<uuid>`. Parse via `lst_` prefix → UUID, else 404 `listing_not_found` (no leak). Fetch listing via RLS-scoped session (`tenant_session`). Path `app_id` (from HMAC) must equal listing's `app_id` — cross-tenant → 404.
2. **Seller-only:** Body's `acting_user_id` must equal listing's `seller_user_id`, else 403 `seller_only`. `acting_user_id` is in body (HMAC-signed), never header.
3. **Presign validation (Step 1):** `content_type ∈ {image/jpeg, image/png, image/webp}`, `content_length ∈ [1, 10485760]` else 400 `validation_failed`. Lifecycle guard: if listing `status != active` → 409 `listing_already_sold`.
4. **Key namespace:** Generate `image_key = {app_id}/listings/{listing_id}/{uuid4}.{ext}` where ext maps jpeg→jpg, png→png, webp→webp. This prevents tenant leak via guessable keys.
5. **Presigned URL:** Return `ImageUpload` with `upload_url` that is a presigned PUT URL for R2 (use boto3 `generate_presigned_url('put_object', Params={'Bucket': bucket, 'Key': key, 'ContentType': content_type}, ExpiresIn=900)` if `R2_ENDPOINT` set, else fallback fake URL `{endpoint}/{bucket}/{key}?presigned=1&expires=900`), `method=PUT`, `image_key`, `expires_in=900`. Store pending metadata in Redis `pending_image:{app_id}:{image_key}` with `content_type`, `content_length`, `created_at` (ISO UTC) for attach-verify and reaper, TTL 2 days.
6. **Attach-verify (Step 2):** `image_key` must start with `{app_id}/listings/{listing_id}/` else 404 (prevent path traversal). Fetch listing + seller check as above. Retrieve pending from Redis or try `head_object` via R2 client. If HEAD fails and no pending → 404. Validate actual content-type/size (from HEAD `ContentType`/`ContentLength` or pending's `actual_content_type`/`actual_content_length` if test injects mismatch) — if actual type not in allowed or actual size >10MiB → 400. Then append (not overwrite) key to `listings.image_keys` (JSONB column, not array — use `image_keys || jsonb_build_array(cast(:key as text))` with `RETURNING` to avoid ORM cache) and return updated `Listing` with `image_urls` derived as `{endpoint}/{bucket}/{key}` index-aligned. Handle both UUID and non-UUID `app_id` values (tests use `app-a` shortcut; map non-UUID to deterministic UUID5 for response validation).
7. **Idempotency:** Router uses `IdempotentRoute`, so same `Idempotency-Key` + same body must replay original response (URL), not allocate new key. Do not break the guard. HMAC signatures are single-use nonce (`nonce:{key_id}:{sig}`) — a retry MUST re-sign with fresh timestamp (keep `Idempotency-Key` stable, vary only `X-Bazaar-Timestamp`). Reusing same timestamp/signature causes 401 replay before idempotency layer.
8. **Orphan reaper:** Implement `async def reap_orphans() -> int` that scans `pending_image:*` in Redis, collects referenced keys from `SELECT image_keys FROM listings`, deletes pending older than 24h that are not referenced and deletes R2 object via `delete_object` if client exists. Return count reaped. Called by cron.

## Constraints

- Only modify `apps/api/src/bazaar_api/modules/listings/images.py`. Do not modify `config.py` (read `R2_*` via `os.getenv`), but you may add optional boto3 import with fallback.
- Preserve `IdempotentRoute` on router.
- Use `current_app_id()` for tenant, not header.
- `image_keys` is JSONB — append via `|| jsonb_build_array(...)`, never overwrite array.

## Out of scope

- Real R2 bucket creation — Minio is local fake. Tests mock HEAD or inject `actual_content_type` via Redis.
- Frontend.

## Acceptance

- `POST .../images` returns 200 with key prefixed by `{app_id}/listings/{listing_id}/`
- `POST .../images/attach` with wrong actual type → 400, with correct → 200 and `image_keys` appended
- Cross-tenant presign → 404, seller mismatch → 403, sold listing → 409
- Same idempotency key replay returns same `image_key`
- Orphan reaper deletes only unattached >24h pending
