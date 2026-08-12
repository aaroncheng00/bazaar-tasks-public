"""Regenerate generated/models.py from spec/openapi.yaml via datamodel-codegen.

This script is the single source of truth for the generator invocation —
package.json (`pnpm gen` / `pnpm gen:check`) and CI both call it, so the
flag set can never drift between "regenerate" and "verify" paths.

Default mode rewrites src/bazaar_api/generated/models.py. The command is
idempotent (--disable-timestamp), so a no-op regen produces a no-op diff.

--check mode (CI): generate in memory and fail if the committed file
differs — i.e. someone edited spec/openapi.yaml without re-running
`pnpm gen`. Companion to check_spec_drift.py (T283279799), which guards the
runtime route surface; this guards the generated models.

Run from apps/api:  uv run python -m bazaar_api._maint.gen_models [--check]
"""

from __future__ import annotations

import argparse
import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # apps/api
SPEC = ROOT.parent.parent / "spec" / "openapi.yaml"
OUT = ROOT / "src" / "bazaar_api" / "generated" / "models.py"

# The generator version is pinned by uv.lock (dev dep) — that pin is
# load-bearing. --check asserts byte equality, so dev and CI must run the
# same datamodel-codegen; bumping the dep may legitimately change output.
# On a bump: uv sync, `pnpm gen`, commit the regen with the lockfile.
CMD = [
    "datamodel-codegen",
    "--input",
    str(SPEC),
    "--input-file-type",
    "openapi",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--use-annotated",
    "--field-constraints",
    "--snake-case-field",
    "--capitalise-enum-members",
    "--use-schema-description",
    "--target-python-version",
    "3.12",
    "--disable-timestamp",
]


def generate() -> str:
    """Run datamodel-codegen and return the generated source.

    Writes to a real temp file, not /dev/stdout: on Linux CI runners stdout
    is a pipe, and /dev/stdout fails the tool's regular-file output handling
    (Exit.ERROR, status 2) — macOS tolerated it, ubuntu did not. stderr is
    surfaced on failure (the tool reports every error there; swallowing it
    made the first CI failure undebuggable from the traceback alone).
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "models.py"
        result = subprocess.run(
            [*CMD, "--output", str(out)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"datamodel-codegen exited {result.returncode}:\n{result.stderr.strip()}"
            )
        if result.stdout.strip():
            # Anything on stdout would poison the --check byte comparison.
            print(f"warning: datamodel-codegen wrote to stdout: {result.stdout.strip()}")
        return out.read_text()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed models.py differs from a fresh regen",
    )
    args = parser.parse_args()

    fresh = generate()

    if not args.check:
        OUT.write_text(fresh)
        print(f"wrote {OUT} from {SPEC}")
        return 0

    committed = OUT.read_text()
    if fresh == committed:
        print(f"ok: {OUT} is up to date with {SPEC}")
        return 0

    print(
        f"STALE GENERATED MODELS: {OUT} differs from a fresh regen of {SPEC}.\n"
        "The spec was edited without re-running codegen. Fix: `pnpm gen` "
        "(apps/api) and commit the result."
    )
    sys.stdout.writelines(
        difflib.unified_diff(
            committed.splitlines(keepends=True),
            fresh.splitlines(keepends=True),
            fromfile="committed",
            tofile="fresh-regen",
        )
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
