# Fix tenant isolation leak — RLS policies permissive and tenant context not set

## Context

Bazaar is a headless FastAPI marketplace API (P2P). Multi-tenancy is enforced via three layers (Architecture S15.4, S7):

1. **Auth**: HMAC `X-Bazaar-Key`/`Timestamp`/`Signature` → exactly one `app_id` (verified tenant)
2. **App scoping**: request-scoped `ContextVar` + data-access layer via `current_app_id()`
3. **Postgres RLS backstop**: `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY` on every tenant table (`docs`, `listings`, `reviews`) with policy `USING (app_id = current_setting('bazaar.app_id', true)) WITH CHECK (...)` — `SET LOCAL bazaar.app_id` per transaction via `tenant_session`

If any layer fails, the failure is **silent**: ordinary integration tests pass while cross-tenant data leaks.

On base commit `35952bfad071` (vendored under `/app`), RLS is **broken**:

- `apps/api/migrations/versions/0001_initial.py` (table `docs`) and `0003_listings.py` (table `listings`) create a permissive policy `USING (true)` — no `app_id` check, no `WITH CHECK`, no `FORCE`. The table owner `bazaar` bypasses `ENABLE` alone; only `FORCE` makes it apply to owners.
- `infra/postgres/init/01-roles.sql` creates `bazaar_app` login, but migrations never use `FORCE`, so `bazaar` superuser and owner still bypass.
- `apps/api/src/bazaar_api/middleware/tenant.py` `tenant_session` does NOT issue `SET LOCAL bazaar.app_id` — it just yields a session. The `current_setting('bazaar.app_id', true)` two-arg fail-closed form is never set, so even a correct policy would see NULL and return zero rows (fail-closed) instead of scoped rows. Combined with `USING (true)`, it leaks.

Result: `tests/rls/test_tenant_isolation.py` fails — tenant B can read tenant A's rows, and forged `app_id` inserts succeed.

## Task

Fix the three broken layers so tenant isolation holds. You must make `tests/rls/` pass as its own CI job (it must never be merged into integration).

### Requirements

**1. Migrations — RLS hardening (`WITH CHECK, FORCE, two-arg current_setting`):**

In `apps/api/migrations/versions/0001_initial.py` and `0003_listings.py`:

- Every tenant table (`docs`, `listings`) must have:
  ```sql
  ALTER TABLE <table> ENABLE ROW LEVEL SECURITY
  ALTER TABLE <table> FORCE ROW LEVEL SECURITY
  CREATE POLICY tenant_isolation ON <table>
    USING (app_id = current_setting('bazaar.app_id', true))
    WITH CHECK (app_id = current_setting('bazaar.app_id', true))
  ```
- Use the **two-arg** `current_setting('bazaar.app_id', true)` — it returns NULL instead of error when GUC is unset (fail-closed). One-arg form `current_setting('bazaar.app_id')` throws and can crash.
- `USING` for SELECT/UPDATE/DELETE filtering, `WITH CHECK` for INSERT/UPDATE — missing `WITH CHECK` allows forged `app_id` inserts.
- `FORCE` is mandatory — without it, table owners and superusers bypass RLS silently (S15.4).

**2. Tenant session — `SET LOCAL` per transaction:**

In `apps/api/src/bazaar_api/middleware/tenant.py`:

- Inside `tenant_session`, after `session.begin()` and before `yield`, issue:
  ```python
  await session.execute(text("SELECT set_config('bazaar.app_id', :app_id, true)"), {"app_id": app_id})
  ```
- `set_config(..., true)` is `SET LOCAL` semantics — transaction-scoped, evaporates at commit, cannot leak across pooled connections.
- Preserve `ContextVar` handling: `set_app_id(app_id)` before yield, `reset_app_id(token)` in finally.

**3. Role split invariant:**

- `infra/postgres/init/01-roles.sql` already creates `bazaar_app` non-owner.
- API must connect as `bazaar_app` at runtime (`BAZAAR_APP_DATABASE_URL`), migrations as `bazaar` owner. Do NOT change URLs in code — env vars `BAZAAR_DATABASE_URL` (owner) and `BAZAAR_APP_DATABASE_URL` (app) are used by `config.py` and tests. Your fix must work when app connects as `bazaar_app`.

**4. Security invariant I1:**

No endpoint returns data across `app_id` boundaries. Cross-tenant reads must be indistinguishable from missing: 404 `listing_not_found` via RLS returning zero rows + application 404.

### Out of scope

- Real R2/Redis parts — not needed for RLS tests
- Adding new tables — only fix `docs` and `listings` (reviews already has correct policy in 0004? Check and fix if needed)
- Boot-time role assertion (`SELECT current_user`) — nice to have but not required for this task

### Acceptance criteria

- `apps/api/tests/rls/test_tenant_isolation.py::test_tenant_cannot_read_other_tenants_rows` — app-b sees 0 rows after app-a inserts
- `test_insert_with_other_tenants_app_id_is_rejected` — INSERT with forged `app_id` raises `DBAPIError` via `WITH CHECK`
- `test_unset_tenant_sees_nothing` — transaction without `SET LOCAL` sees 0 rows (fail-closed, two-arg form)
- `test_tenant_setting_does_not_leak_across_transactions` — GUC evaporates at commit
- Existing integration tests that do not depend on broken RLS must stay green (they use `tenant_session` correctly once fixed)

### Hints

- See `apps/api/migrations/versions/0001_initial.py` and `0003_listings.py` for current broken `USING (true)` — replace with full policy block.
- See `apps/api/src/bazaar_api/middleware/tenant.py` — add the `set_config` line.
- Run `uv run alembic upgrade head` then `uv run pytest apps/api/tests/rls -v` to verify — this suite is the P0 gate; if it fails, treat as live breach until disproven.
