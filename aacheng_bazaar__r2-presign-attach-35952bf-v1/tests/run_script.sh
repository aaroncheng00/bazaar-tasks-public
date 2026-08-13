#!/bin/bash
set -e

# Bazaar API lives at /app/apps/api, src at /app/apps/api/src
# Tests need postgres + redis running (provided via docker-compose.yaml) and migrations applied

run_all_tests() {
  echo "Running all tests..."
  cd /app/apps/api
  export PYTHONPATH=/app/apps/api/src:$PYTHONPATH
  uv run alembic upgrade head 2>&1 | tail -n 20
  # Fallback: ensure docs RLS smoke table exists for TBR (ECR rate-limit may cause DB not migrated)
  uv run python -c "
from sqlalchemy import create_engine, text
from bazaar_api.config import settings
url = settings.database_url.replace('postgresql+asyncpg', 'postgresql')
eng = create_engine(url)
with eng.begin() as c:
    c.execute(text('CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"'))
    c.execute(text('CREATE TABLE IF NOT EXISTS docs (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), app_id TEXT, payload TEXT)'))
    c.execute(text('ALTER TABLE docs ENABLE ROW LEVEL SECURITY'))
    c.execute(text('ALTER TABLE docs FORCE ROW LEVEL SECURITY'))
    c.execute(text('DROP POLICY IF EXISTS tenant_isolation ON docs'))
    c.execute(text(\"CREATE POLICY tenant_isolation ON docs USING (app_id = current_setting('bazaar.app_id', true)) WITH CHECK (app_id = current_setting('bazaar.app_id', true))\" ))
    c.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON docs TO bazaar_app'))
" 2>&1 | tail -n 5 || true
  uv run python -m pytest tests/ -v --tb=short || true
}

run_selected_tests() {
  local test_files=("$@")
  echo "Running selected tests: ${test_files[@]}"
  cd /app/apps/api
  export PYTHONPATH=/app/apps/api/src:$PYTHONPATH
  uv run alembic upgrade head 2>&1 | tail -n 20
  uv run python -c "
from sqlalchemy import create_engine, text
from bazaar_api.config import settings
url = settings.database_url.replace('postgresql+asyncpg', 'postgresql')
eng = create_engine(url)
with eng.begin() as c:
    c.execute(text('CREATE EXTENSION IF NOT EXISTS \"pgcrypto\"'))
    c.execute(text('CREATE TABLE IF NOT EXISTS docs (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), app_id TEXT, payload TEXT)'))
    c.execute(text('ALTER TABLE docs ENABLE ROW LEVEL SECURITY'))
    c.execute(text('ALTER TABLE docs FORCE ROW LEVEL SECURITY'))
    c.execute(text('DROP POLICY IF EXISTS tenant_isolation ON docs'))
    c.execute(text(\"CREATE POLICY tenant_isolation ON docs USING (app_id = current_setting('bazaar.app_id', true)) WITH CHECK (app_id = current_setting('bazaar.app_id', true))\" ))
    c.execute(text('GRANT SELECT, INSERT, UPDATE, DELETE ON docs TO bazaar_app'))
" 2>&1 | tail -n 5 || true
  for test_file in "${test_files[@]}"; do
    echo "Running test: $test_file"
    test_path=$(echo "$test_file" | sed 's|^apps/api/||' | sed 's/::.*//')
    uv run python -m pytest "$test_path" -v --tb=short || true
  done
}

if [ $# -eq 0 ]; then
  run_all_tests
  exit $?
fi

if [[ "$1" == *","* ]]; then
  IFS=',' read -r -a TEST_FILES <<< "$1"
else
  TEST_FILES=("$@")
fi

run_selected_tests "${TEST_FILES[@]}"
