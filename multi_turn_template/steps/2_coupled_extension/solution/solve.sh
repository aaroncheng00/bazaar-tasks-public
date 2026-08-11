#!/usr/bin/env bash
# MUST be byte-identical to this step's config.json "patch" (cumulative gold from base, steps 1..N)
set -euo pipefail
git apply --verbose <<'__SOLUTION_PATCH__'
<PASTE cumulative gold patch here — identical to config.json patch>
__SOLUTION_PATCH__
