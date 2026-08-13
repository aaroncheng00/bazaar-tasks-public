# Fix tenant isolation leak

Bazaar is a headless FastAPI marketplace. Data is tenant-isolated via Postgres RLS.

## Base

On `35952bfad071179dece536ae828761d9e2883162`, RLS is broken for `docs` and `listings`:

- `apps/api/migrations/versions/0001_initial.py` and `0003_listings.py` use a permissive policy that allows cross-tenant reads and inserts.
- `apps/api/src/bazaar_api/middleware/tenant.py` does not set the per-transaction tenant context.

Result: `apps/api/tests/rls/test_tenant_isolation.py` fails — tenant B can read tenant A's rows, forged app_id inserts succeed, and tenant context leaks.

## Task

Fix tenant isolation so `tests/rls/` passes as its own CI job.

**Behavior:**

- Tenant A inserts a doc, Tenant B transaction must see no rows for A.
- INSERT with a different tenant's app_id must be rejected.
- Transaction without tenant context must see no rows (fail-closed).
- Tenant setting must not leak across transactions (evaporates at commit).

**Constraints:**

- Only edit `apps/api/migrations/versions/0001_initial.py`, `0003_listings.py`, and `apps/api/src/bazaar_api/middleware/tenant.py`.
- Preserve existing `ContextVar` handling in `tenant.py` (set before yield, reset after).
- API runs as `bazaar_app` (non-owner) at runtime; owners must not bypass RLS.

**Out of scope:** R2, Redis, frontend, boot-time role assertion.

**Acceptance:** `uv run alembic upgrade head && uv run pytest apps/api/tests/rls -v` green.

