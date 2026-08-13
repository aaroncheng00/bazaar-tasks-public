# R2 image-upload pipeline — presign + attach-verify + orphan reaper

## Context

Bazaar is a headless FastAPI marketplace API (P2P). All `/v1` routes are HMAC-authenticated (`X-Bazaar-Key` / `Timestamp` / `Signature`, 300s window, single-use nonce via Redis), tenant-scoped via `current_app_id()` + Postgres RLS (`FORCE RLS` on `listings`), and idempotent via `Idempotency-Key` using `IdempotentRoute`.

On base commit `35952bfad071179dece536ae828761d9e2883162`, `apps/api/src/bazaar_api/modules/listings/images.py` is stubbed to 501 for both:
- `POST /v1/listings/{listing_id}/images` — request upload URL
- `POST /v1/listings/{listing_id}/images/attach` — verify and link

R2 is Cloudflare R2, locally emulated by Minio (`R2_ENDPOINT`, `R2_BUCKET`, etc. from `.env.example`).

## Task

Implement the two handlers replacing the 501 stubs, plus `reap_orphans()` helper.

**Requirements:**

1. **Tenant isolation:** `listing_id` is `lst_<uuid>`, invalid or unknown → 404 `listing_not_found` no leak. All DB access must be via RLS-scoped session. Authenticated `app_id` must match listing's `app_id`.

2. **Seller-only:** `acting_user_id` from body must equal `seller_user_id`, else 403 `seller_only`. Never trust header.

3. **Presign:** Validate content-type in allowed images and content-length ≤10MiB else 400. If listing not active → 409. Generate tenant-namespaced key and presigned PUT URL (expires ~15min). Track pending uploads in Redis for verification/reaper — use key `pending_image:{app_id}:{image_key}` with content metadata and `created_at` (TTL couple days). Tests may inject `actual_*` fields to simulate HEAD mismatch.

4. **Attach-verify:** Key must be namespaced, else 404. Verify seller, check object existence via R2 HEAD if available else pending, reject wrong actual type/size → 400, append key to `listings.image_keys` (JSONB, not array) and return updated `Listing`.

5. **Idempotency:** Preserve `IdempotentRoute`. Same `Idempotency-Key` + same body replays original response.

6. **Orphan reaper:** `async def reap_orphans() -> int` scans `pending_image:*`, collects referenced keys from listings, deletes pending older than 24h not referenced, deletes R2 object if possible.

## Constraints

- Only modify `images.py`.
- Preserve `IdempotentRoute`, use `current_app_id()`.
- `image_keys` appended, never overwritten.

## Out of scope

- Real R2 creation — Minio is fake. Tests mock HEAD or use Redis injection.

## Acceptance

- Presign returns 200 with namespaced key, PUT method, ~900s expiry
- Attach wrong actual type → 400, correct → 200 and appends
- Cross-tenant → 404, seller mismatch → 403
- Idempotency replay same body → same key; same sig reuse → HMAC 401 before idempotency
- Reaper deletes only unattached old pending
