# PROJECT — Lab Configuration

> Fill this file in when you adopt the template. It is the **only file you must edit**
> to get started. Every other file is either shared infrastructure (`CORE_STANDARDS.md`)
> or track guidance (`GOLD_STANDARD.md`). Keep this file small — its smallness is the product.

This file holds the per-lab config surface. Replace every placeholder below with your lab's values.
Comments show worked examples. After you finish, no placeholder should remain in any command you run.

---

## Lab identity

- **Lab name:** `Bazaar`
- **Track:** `swe-bench`
- **Owner / contact:** `aacheng`

## Repos and paths

- **Product repo (the system under test):** `https://github.com/metainternal-aai/aai_labs_bazaar`
- **Task repo (where tasks live):** `<github.com/codimango/aacheng-swe-aai-pipeline`
- **Task skeletons:** shipped in-repo as `single_turn_template/` and `multi_turn_template/` — upstream: github.com/codimango/swe-bench-pro-template
- **Local checkout path for product repo:** `/home/aacheng/aai_labs_bazaar`
- **Local checkout path for task repo:** `/home/aacheng/aacheng-swe-aai-pipeline`

## Task authoring knobs

- **Base commit for new tasks:** `35952bf`  <!-- origin/main head (K3 hardening merged), where images.py is still 501 stub -->
- **Task directory name for next idea:** `aacheng_bazaar__r2-presign-attach-35952bf-v1` <!-- e.g. example-schema-migration-chain -->
- **Author handle for cards:** `aacheng`
- **Token file for credless builds (gitignored):** `~/.aacheng_gh_token`

## Docs and roster

- **Setup doc this lab follows:** `SETUP.md` (and `PROJECT.md` — this file)
- **Task roster location:** `README.md` <!-- e.g. README.md task table in task repo -->
- **Cards board:** `pipeline/cards/`

## Domain notes

Bazaar is headless FastAPI + Postgres RLS (app_id = current_setting('bazaar.app_id', true) + FORCE + WITH CHECK), Redis for nonce/idempotency (SETNX) + rate-limit, Cloudflare R2 (Minio locally) for listing images. S1 image upload is stubbed: POST /v1/listings/{id}/images should return presigned R2 PUT URL with key {app_id}/listings/{listing_id}/{uuid}.jpg (tenant-isolated), POST .../images/attach must HEAD verify content-type/size and append to image_keys, seller-only via acting_user_id, orphan reap after 24h, Idempotency-Key required. Bugs hide in tenant leak across tx and attach-verify bypass.
