#!/usr/bin/env bash
# validate.sh — 3-step proof loop for a AAI Labs SWE-Bench task.
#
# Proves the task is sound the same way <EXAMPLE_TASK> was validated:
#   1. BASE   (base + test_patch, no gold)     -> fail_to_pass RED   (feature absent)
#   2. ORACLE (base + gold + test_patch)       -> ALL green, reward 1
#   3. NAIVE  (base + naive.patch + test_patch)-> PARTIAL (optional; proves the
#             suite grades correctness across axes, not just happy-path)
#
# Usage:
#   GH_TOKEN_FILE=/path/to/gh_token.txt ./validate.sh
#   (optional) drop a tests/naive.patch to exercise step 3.
#   (optional) BASE_COMMIT=<sha> overrides tests/config.json _base_commit_sha.
#
# Requires: Docker with BuildKit. The token is passed as a build secret and is
# never written to the image or the repo.
set -uo pipefail

TASK_DIR="$(cd "$(dirname "$0")" && pwd)"
CFG="$TASK_DIR/tests/config.json"
: "${GH_TOKEN_FILE:?set GH_TOKEN_FILE to a file containing a GitHub PAT (never commit it)}"
[ -f "$GH_TOKEN_FILE" ] || { echo "GH_TOKEN_FILE not found: $GH_TOKEN_FILE"; exit 2; }
[ -f "$CFG" ] || { echo "config.json not found: $CFG"; exit 2; }

BASE_COMMIT="${BASE_COMMIT:-$(python3 -c "import json;print(json.load(open('$CFG')).get('_base_commit_sha',''))")}"
[ -n "$BASE_COMMIT" ] && [ "$BASE_COMMIT" != "@@FILL:40-hex commit where the target feature is ABSENT@@" ] || {
  echo "Set _base_commit_sha in tests/config.json (or pass BASE_COMMIT=<sha>)."; exit 2; }

IMAGE="<PROJECT>-task-validate:$$"
WORK="$(mktemp -d)"
cleanup() { docker rmi -f "$IMAGE" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "== Building image @ base commit ${BASE_COMMIT:0:12} =="
DOCKER_BUILDKIT=1 docker build \
  --secret id=gh_token,src="$GH_TOKEN_FILE" \
  --build-arg BASE_COMMIT="$BASE_COMMIT" \
  -f "$TASK_DIR/environment/Dockerfile" -t "$IMAGE" "$TASK_DIR/environment" \
  >"$WORK/build.log" 2>&1 || { echo "BUILD FAILED:"; tail -25 "$WORK/build.log"; exit 1; }
echo "   build ok"

# Run one scenario in a fresh container. $1=name  $2=pre-test hook (bash run in /app).
# test.sh applies test_patch + grades; we mount a per-case host /logs to read results.
run_case() {
  local name="$1" hook="$2"
  local logdir="$WORK/$name"
  mkdir -p "$logdir/verifier"
  docker run --rm --network none \
    -v "$TASK_DIR/tests:/tests:ro" \
    -v "$TASK_DIR/solution:/solution:ro" \
    -v "$logdir:/logs" \
    "$IMAGE" bash -c "set -uo pipefail; cd /app; $hook; bash /tests/test.sh" \
    >"$logdir/console.log" 2>&1 || true
}

# Host-side tally of fail_to_pass / pass_to_pass from a case's output.json.
tally() { # $1=logdir  -> prints "ftp_pass/ftp_total ptp_pass/ptp_total reward"
  python3 - "$1" "$CFG" <<'PY'
import json,sys,os
logdir,cfg=sys.argv[1],sys.argv[2]
c=json.load(open(cfg))
ftp=set(c.get("fail_to_pass",[])); ptp=set(c.get("pass_to_pass",[]))
passed=set()
oj=os.path.join(logdir,"verifier","output.json")
if os.path.exists(oj):
    for t in json.load(open(oj)).get("tests",[]):
        if t.get("status")=="PASSED": passed.add(t.get("name",""))
rf=os.path.join(logdir,"verifier","reward.txt")
reward=open(rf).read().strip() if os.path.exists(rf) else "?"
print(f"{len(ftp&passed)}/{len(ftp)} {len(ptp&passed)}/{len(ptp)} {reward}")
PY
}

echo "== 1. BASE (no gold) — expect fail_to_pass RED, reward 0 =="
run_case base ":"
read -r B_FTP B_PTP B_REW <<<"$(tally "$WORK/base")"
echo "   fail_to_pass=$B_FTP  pass_to_pass=$B_PTP  reward=$B_REW"

echo "== 2. ORACLE (gold via solve.sh) — expect ALL green, reward 1 =="
run_case oracle "bash /solution/solve.sh"
read -r O_FTP O_PTP O_REW <<<"$(tally "$WORK/oracle")"
echo "   fail_to_pass=$O_FTP  pass_to_pass=$O_PTP  reward=$O_REW"

NAIVE_OK=1
if [ -f "$TASK_DIR/tests/naive.patch" ]; then
  echo "== 3. NAIVE (tests/naive.patch) — expect PARTIAL, reward 0 =="
  run_case naive "git apply /tests/naive.patch"
  read -r N_FTP N_PTP N_REW <<<"$(tally "$WORK/naive")"
  echo "   fail_to_pass=$N_FTP  pass_to_pass=$N_PTP  reward=$N_REW"
  np=${N_FTP%/*}; nt=${N_FTP#*/}
  [ "$np" -gt 0 ] && [ "$np" -lt "$nt" ] || NAIVE_OK=0
else
  echo "== 3. NAIVE skipped (no tests/naive.patch) — recommended to add one =="
fi

echo ""
echo "================ PROOF ================"
op=${O_FTP%/*}; ot=${O_FTP#*/}; opp=${O_PTP%/*}; opt=${O_PTP#*/}
bp=${B_FTP%/*}
BASE_OK=$([ "$bp" -lt "${B_FTP#*/}" ] && echo 1 || echo 0)      # not all ftp pass at base
ORACLE_OK=$([ "$op" -eq "$ot" ] && [ "$opp" -eq "$opt" ] && [ "$O_REW" = "1" ] && echo 1 || echo 0)
printf "| base fail_to_pass RED      | %s | %s |\n" "$B_FTP" "$([ $BASE_OK = 1 ] && echo PASS || echo FAIL)"
printf "| oracle all green, reward 1 | %s ftp, %s ptp, r=%s | %s |\n" "$O_FTP" "$O_PTP" "$O_REW" "$([ $ORACLE_OK = 1 ] && echo PASS || echo FAIL)"
[ -f "$TASK_DIR/tests/naive.patch" ] && printf "| naive partial              | %s | %s |\n" "$N_FTP" "$([ $NAIVE_OK = 1 ] && echo PASS || echo FAIL)"

if [ "$BASE_OK" = 1 ] && [ "$ORACLE_OK" = 1 ] && [ "$NAIVE_OK" = 1 ]; then
  echo "✓ TASK SOUND — base red, oracle green, $([ -f "$TASK_DIR/tests/naive.patch" ] && echo 'naive partial' || echo 'naive N/A')"
  exit 0
fi
echo "✗ TASK NOT SOUND — see table (base must be red, oracle must be all-green r=1)."
echo "  Do NOT tune tests/threshold to force green — fix the gold patch, base commit, or test set."
exit 1
