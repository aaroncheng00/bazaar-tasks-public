#!/bin/bash
set -e

# <PROJECT> package lives at /app/src (pyproject: packages = ["src/<PKG>"]),
# so tests import via PYTHONPATH=/app/src.

run_all_tests() {
  echo "Running all tests..."
  cd /app
  export PYTHONPATH=/app/src:$PYTHONPATH
  python -m pytest tests/ -v --tb=short || true
}

run_selected_tests() {
  local test_files=("$@")
  echo "Running selected tests: ${test_files[@]}"
  cd /app
  export PYTHONPATH=/app/src:$PYTHONPATH
  for test_file in "${test_files[@]}"; do
    echo "Running test: $test_file"
    test_path=$(echo "$test_file" | sed 's/::.*//')
    python -m pytest "$test_path" -v --tb=short || true
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
