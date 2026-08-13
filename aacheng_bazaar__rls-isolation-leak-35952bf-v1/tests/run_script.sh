#!/bin/bash
set -e

# Bazaar API lives at /app/apps/api, src at /app/apps/api/src
# Tests need postgres + redis running (provided via docker-compose.yaml) and migrations applied

run_all_tests() {
  echo "Running all tests..."
  cd /app/apps/api
  export PYTHONPATH=/app/apps/api/src:$PYTHONPATH
  uv run alembic upgrade head 2>&1 | tail -n 20
  uv run python -m pytest tests/ -v --tb=short || true
}

run_selected_tests() {
  local test_files=("$@")
  echo "Running selected tests: ${test_files[@]}"
  cd /app/apps/api
  export PYTHONPATH=/app/apps/api/src:$PYTHONPATH
  uv run alembic upgrade head 2>&1 | tail -n 20
  for test_file in "${test_files[@]}"; do
    echo "Running test: $test_file"
    # test_file from config is like apps/api/tests/... - convert to relative from apps/api
    # If it starts with apps/api/, strip that prefix
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
