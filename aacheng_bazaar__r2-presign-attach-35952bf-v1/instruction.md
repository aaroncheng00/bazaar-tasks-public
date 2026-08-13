# Image upload pipeline

Bazaar is a headless FastAPI marketplace. Listings are tenant-isolated via RLS and HMAC.

## Base

On `35952bfad071179dece536ae828761d9e2883162`, `images.py` stubs 501:
- `POST /v1/listings/{listing_id}/images`
- `POST /v1/listings/{listing_id}/images/attach`

## Task

Implement both handlers and `reap_orphans()` in `images.py`.

**Behavior:**

- `listing_id` is `lst_<uuid>` — invalid or unknown → 404 no leak, via RLS-scoped session. App must match listing's app.
- `acting_user_id` in body must equal `seller_user_id` → 403.
- Presign: validate image type and size → 400, active check → 409. Generate tenant-namespaced image key with random part, return presigned PUT URL and `image_key`. Track pending uploads in Redis at `pending_image:{app_id}:{image_key}` for verification and reaping.
- Attach: key must be namespaced, else 404. Verify seller, check object exists (try R2 HEAD, fallback to pending), reject wrong actual type/size → 400. Append key to listing's image keys and return updated listing.
- Idempotency: keep `IdempotentRoute` — same key + same body replays correctly.
- Reaper: `reap_orphans()` cleans up old pending uploads.

**Constraints:**

- Only edit `images.py`.
- Keep `IdempotentRoute`, use `current_app_id()`.
- Append image_keys, never overwrite.

**Out of scope:** Real R2, frontend.
