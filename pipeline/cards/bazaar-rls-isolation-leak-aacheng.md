---
status: claimed
claimed_at: 2026-08-13T14:50:00Z
slug: bazaar-rls-isolation-leak
title: Fix tenant isolation leak — RLS permissive (USING true, no FORCE/WITH CHECK) + missing SET LOCAL
author: aacheng
source_author: aacheng
created_at: 2026-08-13
claimed_by: aacheng
task_dir: aacheng_bazaar__rls-isolation-leak-35952bf-v1
base_commit: 35952bfad071179dece536ae828761d9e2883162
novelty_risk: low
difficulty_hypothesis: hard — trap is silent RLS bypass: ENABLE without FORCE bypassed by owner, USING true leaks cross-tenant, missing WITH CHECK allows forged app_id inserts, tenant_session missing SET LOCAL. Integration tests pass while isolation broken, only tests/rls/ negative suite catches it.
taxonomy:
  type: Bug Fix
  subdomain: security_and_privacy
  usecase: enforce_policy
---

# Idea

From GSD T283279615 `[S1] tests/rls/ negative isolation suite` and hardening T283279625 `WITH CHECK, FORCE, two-arg current_setting`. At base commit `35952bf` (main), Bazaar had correct RLS, but we inject the bug that existed in early review: `docs` and `listings` tables have permissive RLS `USING (true)` without `FORCE ROW LEVEL SECURITY` and without `WITH CHECK`. Plus `tenant_session` never issues `SET LOCAL bazaar.app_id`. Result: `bazaar` owner bypasses ENABLE-only RLS, any tenant can read other tenant's rows, forged `app_id` inserts succeed.

This task proves the S1 platform invariant I1: no endpoint returns data across app_id boundaries; cross-tenant reads must be 404, and is the P0 gate — RLS negative-suite failure = treat as live breach.

# Why This Is Hard

Trap is silent, not visible in happy-path integration:

- Obvious: add `ENABLE RLS` only — still bypassed by owner/superuser, tests still show leak because `bazaar` user is owner in migrations. Need `FORCE`.
- Obvious: add `USING (app_id = current_setting('bazaar.app_id'))` one-arg — throws error when GUC unset instead of fail-closed NULL, crashes. Need two-arg `current_setting('bazaar.app_id', true)`.
- Obvious: add `USING` but forget `WITH CHECK` — SELECT is scoped but INSERT with forged `app_id` succeeds (test_insert_with_other_tenants_app_id_is_rejected fails).
- Obvious: fix migrations but forget `tenant_session` `SET LOCAL` — policy uses two-arg which returns NULL when unset → 0 rows always, even own rows invisible, or with USING true leaks.

Integration tests (`tests/integration/*`) all pass while isolation broken, because they use `tenant_session` correctly but never test cross-tenant negative case. Only `tests/rls/test_tenant_isolation.py` catches it — that's why suite is separate CI job.

Agent must fix three files:
- `apps/api/migrations/versions/0001_initial.py` (docs)
- `apps/api/migrations/versions/0003_listings.py` (listings)
- `apps/api/src/bazaar_api/middleware/tenant.py` (SET LOCAL)

# Novelty Check

Searched:
- "Postgres RLS tenant isolation USING true" → generic RLS tutorials (Supabase, etc.) show correct pattern, but bug pattern USING true + missing FORCE is not posed as task
- "current_setting two-arg fail-closed" → Postgres docs, but no SWE-bench task combining ENABLE+FORCE+WITH CHECK+two-arg+SET LOCAL transaction scoping + owner bypass gotcha
- "SET LOCAL set_config is_local true leak across pooled connections" → 0 results as task
- Existing SWE-bench: no RLS task with silent bypass by owner (Architecture S15.4)

Risk: low — Bazaar is private `metainternal-aai/aai_labs_bazaar` (not in public training), combination of three layers + role split + ContextVar is bespoke. No public GitHub issue/PR.

# Proposed Test Shape

Behavior contracts, not implementation:

fail_to_pass (must FAIL at base, PASS with gold):
- `tests/rls/test_tenant_isolation.py::test_tenant_cannot_read_other_tenants_rows` — app-a inserts `secret-a`, app-b transaction sees [] not leak
- `test_insert_with_other_tenants_app_id_is_rejected` — INSERT with app-b while SET LOCAL app-a raises DBAPIError via WITH CHECK
- `test_unset_tenant_sees_nothing` — no SET LOCAL → two-arg returns NULL → [] fail-closed
- `test_tenant_setting_does_not_leak_across_transactions` — GUC evaporates at commit, next txn sees []

pass_to_pass (must PASS both base and oracle, regression guard):
- `tests/unit/test_tenant_leak.py::*` — ContextVar isolation under concurrency (50 tasks)
- `tests/unit/test_config.py::*` — env var wiring, fail-safe defaults

selected_test_files_to_run: `apps/api/tests/rls/test_tenant_isolation.py`, `apps/api/tests/unit/test_tenant_leak.py`, `apps/api/tests/unit/test_config.py`

Naive attempt: only adds ENABLE without FORCE, or only fixes tenant.py but not migrations → still leaks or 0 rows.

# Anti-Cheat Notes

- No-op (keep USING true, no SET LOCAL) → fail_to_pass 0/4 → reward 0
- Hardcode test app_ids in policy (e.g., `app_id IN ('app-a','app-b')`) — fails when new tenant id in hidden test
- Skip FORCE — owner `bazaar` still bypasses in migration runner, but `bazaar_app` enforces; hidden test checks FORCE exists via `\d` or migration linter
- One-arg `current_setting` — passes some tests but crashes on unset tenant test
- Modifying test files — blocked by `check_solution_paths.py` (solution must not touch tests/)
- Ground truth stays verifier-side: gold.patch in solution/, not visible to agent; repo vendored via COPY so history unrecoverable

# Scaffold Notes

- Task dir: `aacheng_bazaar__rls-isolation-leak-35952bf-v1`, base_commit `35952bfad071179dece536ae828761d9e2883162`
- Vendor: `environment/repo` (22.99MB) — private repo, COPY not clone, git init base
- Dockerfile: `python:3.12@sha256:dd4fe98...` full (has git), `uv sync --frozen` + `pytest==9.1.1 httpx==0.28.1`
- docker-compose: postgres:16 + redis:7 + main (BAZAAR_APP_DATABASE_URL=bazaar_app)
- Proof: `codimango bench run -p aacheng_bazaar__rls-isolation-leak-35952bf-v1 -a oracle` → Mean 1.0 job `2026-08-13__14-48-16__26422e` (base 0/4 fail, oracle 4/4 + 13 unit green)
- Structural: 6/6 files, taxonomy valid, WARN empty test_patch (expected, tests already in repo)

# Rejection Notes

None.

