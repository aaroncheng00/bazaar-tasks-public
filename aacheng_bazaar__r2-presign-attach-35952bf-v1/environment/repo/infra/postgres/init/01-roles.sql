-- Local-dev role bootstrap. Runs once, on first container init with an empty
-- pgdata volume (docker-entrypoint-initdb.d semantics). Managed Postgres
-- (Render/Supabase) never runs this — there, roles come from the provider
-- console and privileges from Alembic migrations.
--
-- The `bazaar` superuser (POSTGRES_USER) owns the schema and runs migrations.
-- `bazaar_app` is the role the API connects as at runtime: RLS is enforced for
-- non-owner roles, while the table owner bypasses it unless FORCE is set.

CREATE ROLE bazaar_app LOGIN PASSWORD 'bazaar_app';

GRANT CONNECT ON DATABASE bazaar TO bazaar_app;
GRANT USAGE ON SCHEMA public TO bazaar_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO bazaar_app;

-- Tables created by future migrations (run as `bazaar`) must also be readable
-- by bazaar_app — without this, every new table starts out inaccessible.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bazaar_app;
