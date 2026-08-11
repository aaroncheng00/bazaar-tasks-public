#!/usr/bin/env python3
"""Guard: every task.toml must carry the audit-trail tags.

Per the ADO agentic-pipelines audit-trail rules, a task produced by a pipeline
must be attributable. Its [metadata] tags must contain:

  - "synthetic"       marks the task as agent-generated
  - the pipeline name so the generator gets credit
  - every model used to generate it
  - "human-reviewed"  if a human edited or curated it after generation

Skipped: task.toml under deprecated/ and jobs/.
Stdlib only. Exit 1 with a one-line actionable message per violation.
"""
import os
import re
import sys

PIPELINE = "aai-labs-harvester"
REQUIRED = ["synthetic", PIPELINE]
SKIP_DIRS = {"deprecated", "jobs", ".git", "node_modules"}


def tags_of(path):
    text = open(path, encoding="utf-8", errors="ignore").read()
    m = re.search(r"^tags\s*=\s*\[(.*?)\]", text, re.M | re.S)
    if not m:
        return None
    return [t.strip().strip('"\'') for t in m.group(1).split(",") if t.strip()]


def main(argv):
    roots = argv[1:] or ["."]
    total, bad = 0, 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            if "task.toml" not in filenames:
                continue
            path = os.path.join(dirpath, "task.toml")
            total += 1
            tags = tags_of(path)
            if tags is None:
                bad += 1
                print(f"[VIOLATION] {path}: no `tags = [...]` in [metadata] — "
                      f'add tags = ["synthetic", "{PIPELINE}", "<model-id>", "human-reviewed", ...]')
                continue
            missing = [t for t in REQUIRED if t not in tags]
            if missing:
                bad += 1
                print(f"[VIOLATION] {path}: tags missing {missing} — "
                      f"the audit trail needs them or this task credits no pipeline")
    if bad:
        print(f"\nScanned {total} task.toml; {bad} with violations.")
        return 1
    print(f"Scanned {total} task.toml; 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
