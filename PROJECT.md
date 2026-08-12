# PROJECT — Lab Configuration

> **Already filled for the Bazaar pod. Joining? You do not need to edit this file.**
> It holds *lab-level* config only — values that are the same for every author and
> every task. Change it when lab-level facts change (repo moves, new owner, domain
> notes go stale), not when you start a task.
>
> Per-task values (task dir, slug, author handle, base commit) deliberately live
> **on the card**, not here — see `pipeline/cards/`. A shared config file cannot hold
> five authors' current task without conflicting.

Everything else is either shared infrastructure (`CORE_STANDARDS.md` — nobody downstream
edits) or track guidance (`GOLD_STANDARD.md` — track owner, rarely). Keep this file small;
its smallness is the product.

---

## Lab identity

- **Lab name:** `Bazaar`
- **Track:** `swe-bench`
- **Owner / contact:** `vetaylor`

## Repos and paths

- **Product repo (the system under test):** `https://github.com/metainternal-aai/aai_labs_bazaar`
- **Task repo (where tasks live):** `https://github.com/codimango/bazaar-swe-aai-pipeline`
- **Task skeletons:** shipped in-repo as `single_turn_template/` and `multi_turn_template/` — upstream: github.com/codimango/swe-bench-pro-template
- **Local checkout paths:** per-person, wherever you cloned them. Several task-dir
  commands assume the product repo is checked out beside the task repo; keep both
  under one parent dir and the relative paths in `prompts/` work unchanged.

## Docs and roster

- **Setup doc this lab follows:** `SETUP.md` (and `PROJECT.md` — this file)
- **Task roster location:** `README.md` <!-- e.g. README.md task table in task repo -->
- **Cards board:** `pipeline/cards/`

## Domain notes

Bazaar is headless FastAPI + Postgres RLS (app_id = current_setting('bazaar.app_id', true) + FORCE + WITH CHECK), Redis for nonce/idempotency (SETNX) + rate-limit, Cloudflare R2 (Minio locally) for listing images. S1 image upload is stubbed: POST /v1/listings/{id}/images should return presigned R2 PUT URL with key {app_id}/listings/{listing_id}/{uuid}.jpg (tenant-isolated), POST .../images/attach must HEAD verify content-type/size and append to image_keys, seller-only via acting_user_id, orphan reap after 24h, Idempotency-Key required. Bugs hide in tenant leak across tx and attach-verify bypass.
