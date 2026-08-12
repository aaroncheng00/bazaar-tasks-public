---
status: claimed
claimed_at: 2026-08-11T21:17:19.248528Z
slug: bazaar-r2-presign-attach
title: R2 presigned upload + attach-verify + orphan reaper (S1 image pipeline)
author: aacheng
source_author: srimanisha
created_at: 2026-08-11
claimed_by: aacheng
task_dir: aacheng_bazaar__r2-presign-attach-35952bf-v1
base_commit: 35952bfad071179dece536ae828761d9e2883162
novelty_risk: medium
difficulty_hypothesis: Avocado 2/5, Opus 3/5, Codex 1/5 — trap in attach-verify HEAD + tenant-isolation + idempotency template key
taxonomy:
  type: Implement New Feature
  subdomain: build_and_ci
  usecase: provision_infrastructure
---

# Idea

On `main` `35952bf`, `apps/api/src/bazaar_api/modules/listings/images.py` is stubbed to 501 for both `POST /v1/listings/{listing_id}/images` (presign) and `POST .../images/attach` (verify+link). Real behavior gap from T282737474 / T282737592: client must PUT bytes directly to R2 (Minio locally, Cloudflare R2 prod) so bytes never transit API (§7). Keys namespaced `{app_id}/listings/{listing_id}/{uuid}.jpg`. MVP validates content-type/size via server HEAD before linking, seller-only via `acting_user_id` in body, idempotency via `Idempotency-Key` template key to prevent cardinality explosion, orphan unattached uploads reaped after 24h.

Target modules: `modules/listings/images.py`, `db/models.py` (image_keys JSONB), `middleware/tenant_context`, `middleware/idempotency`, `infra` postgres init for RLS still applies (listings table). This is the blocking S1 image pipeline for journey P2.

# Why This Is Hard

Trap is in attach-verify, not spec. Obvious approach:
- generates presigned URL but forgets to namespace key by `app_id` (tenant leak — other tenant can guess key)
- trusts client-declared content-type/size from Step 1, skip HEAD verify — presigned PUT cannot enforce type/size, so malicious client can upload `application/octet-stream` as `image/jpeg`
- overwrites `image_keys` instead of appends, breaking existing images
- misses `acting_user_id` seller check (uses header not body) — bypassable
- misses idempotency template key: uses raw `Idempotency-Key` as Redis key without `app_id` + body hash → other tenant replay or cardinality DoS
- orphan reaper deletes attached keys too (no check `image_keys` contains key)
- Two distinct miss-paths: happy-path presign works, but attach fails closed (400) or fails open (200 with wrong type)

Spec stays terse contract only — no worked example of R2 HEAD or reaper.

# Novelty Check

Searched:
- "S3 presigned URL upload" → 10+ tutorials (aws blog, dev.to, transloadit) — core single SDK call `generate_presigned_url` / `create_presigned_url` is HIGH recall
- "Cloudflare R2 presigned URL + Hono" → lirantal blog — same pattern
- "S3 attach verify HEAD content-type/size" + "orphan reaping" + "tenant_isolation RLS" → 0 results (combination novel)
- StackOverflow "S3 presigned URL content-type validation" → canonical answer is HEAD verification, but no tenant isolation + idempotency template + seller check combo

Risk band: medium — core presign is well-known (HIGH alone), but combination with attach-verify HEAD, namespace `{app_id}/...`, seller-only `acting_user_id` in body, idempotency template key, orphan reaper, RLS `FORCE`/`WITH CHECK` is bespoke to Bazaar. Component Composition Rule downgrades from HIGH to MEDIUM. No public GitHub issue/PR/commit URL in instruction. Base commit `35952bf` is internal repo `metainternal-aai/aai_labs_bazaar` not in public training data.

# Proposed Test Shape

Behavior contract, not privileged cases:

- Contract: `POST /v1/apps` → `bzp_` token → `POST /v1/apps/{id}/keys` via ProvisioningBearer → HMAC key to auth. Then create listing, request presign, PUT bytes to Minio (S3 compatible) via presigned URL, attach.

- Grade via `tests/config.json` fail_to_pass:
  - `test_presign_returns_url_with_app_prefix` — URL contains `{app_id}/listings/{listing_id}/`
  - `test_attach_verify_rejects_wrong_content_type` — Step1 declared `image/jpeg`, but actual object is `application/octet-stream` → 400 `validation_failed`
  - `test_attach_appends_not_overwrites` — attach second image, `image_keys` len 2, first still present
  - `test_cross_tenant_presign_forbidden` — other tenant's listing_id → 404 (no leak)
  - `test_seller_only_via_acting_user_id` — `acting_user_id` != seller → 403 `seller_only`
  - `test_idempotency_replay_returns_original` — same `Idempotency-Key` + same body → same URL, not double alloc
  - `test_orphan_reaper_deletes_only_unattached` — upload via presign but never attach, run reaper, key gone; attached key stays

Pass_to_pass: existing RLS negatives (12 tests), `test_tenant_isolation`, `test_keys_api`, `test_apps_api` still pass.

Naive attempt (just generate URL, skip HEAD) passes presign but fails `test_attach_verify_rejects_wrong_content_type`.

# Anti-Cheat Notes

- No-op (keep 501 stubs) → all fail_to_pass false → 0
- Hardcoded URL string — tests recompute expected prefix from `app_id`/`listing_id` returned at runtime, not literal comparison
- Overfitting to visible tests — hidden tests add extra content-type `image/png` vs `image/jpeg` mismatch, extra tenant id
- Modifying test files — `test_patch` applied by verifier, agent patch touching `tests/` rejected via `check_solution_paths.py`
- Bypassing via `listings.image_keys = [client_key]` without R2 HEAD — `test_attach_verify_rejects_wrong_content_type` fails because it checks R2 HEAD mock
- Ground truth stays verifier-side: reference solution patch in `solution/solve.sh` not visible to agent; Minio mock returns real HEAD data

# Scaffold Notes

To be filled by oracle-scaffolder: task dir `aacheng_bazaar__r2-presign-attach-35952bf-v1`, base commit `35952bf`, proof commands `codimango bench run -p ... -a oracle` etc., reward results.

# Rejection Notes

None yet.
