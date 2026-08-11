#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
echo "Running pipeline checks from $ROOT"
echo "---"
PASS=0
FAIL=0
check() {
  local name="$1"
  shift
  echo ">> $name"
  if python3 "$@" 2>&1; then
    echo "   PASS"
    PASS=$((PASS+1))
  else
    echo "   FAIL — fix the file it names above"
    FAIL=$((FAIL+1))
  fi
  echo ""
}
check "check_before_repo_set_cmd" "$ROOT/pipeline/checks/check_before_repo_set_cmd.py" "$ROOT"
check "check_solution_paths" "$ROOT/pipeline/checks/check_solution_paths.py" "$ROOT"
check "check_card_schema" "$ROOT/pipeline/checks/check_card_schema.py" "$ROOT"
check "check_audit_tags" "$ROOT/pipeline/checks/check_audit_tags.py" "$ROOT"
echo "Summary: $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
  echo "One or more checks failed — see violations above (one line per file, fix it)."
  exit 1
fi
echo "All checks passed."
