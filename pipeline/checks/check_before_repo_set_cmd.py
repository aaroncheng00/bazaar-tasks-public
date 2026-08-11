#!/usr/bin/env python3
"""Preflight guard: before_repo_set_cmd must be `rm -f <NET_NEW_TEST_PATHS>`.

Why this exists (root-caused 2026-08-07): the verifier runs
`before_repo_set_cmd` and THEN re-applies `test_patch` (which adds the hidden
tests as `new file mode`), then runs tests. So the command must CLEAR the
net-new test paths so test_patch can add them cleanly.

Three ways it goes wrong, each an oracle=0.0 or structural reject:
  * `git clean ...`                 -> structural REJECTS git clean.
  * `git checkout <c> -- <netnew>`  -> file not in HEAD -> "pathspec did not
                                       match" -> "Gold tests checkout failed"
                                       -> oracle reward 0.0.
  * net-new test file left present  -> test_patch's new-file apply hits
                                       "already exists" -> oracle 0.0.

Correct: `rm -f <exact test paths test_patch ADDS>` (single line; source paths
are disjoint so agent source survives). Use `git checkout HEAD -- <path>` ONLY
for a test_patch that MODIFIES a pre-existing tracked file.

Usage:  python3 pipeline/checks/check_before_repo_set_cmd.py [repo_root ...]
Exit 0 if clean, 1 if any violation. Skips deprecated/, jobs/, and empty
aggregate configs (no test_patch = build-to-a-bar / multi-turn root).
"""
import json
import os
import re
import sys


def patched_files(test_patch):
    """Return [(path, is_new_file)] for each file the patch touches."""
    files = []
    for ln in test_patch.split("\n"):
        m = re.match(r"^diff --git a/(\S+) b/(\S+)", ln)
        if m:
            files.append([m.group(2), False])
        elif ln.startswith("new file mode") and files:
            files[-1][1] = True
    return files


def check_config(path):
    """Return a list of violation strings for one config.json (empty = clean)."""
    try:
        d = json.load(open(path))
    except Exception as e:
        return [f"unreadable JSON: {e}"]
    tp = d.get("test_patch", "") or ""
    if not tp.strip():
        return []  # build-to-a-bar or empty multi-turn root aggregate
    b = (d.get("before_repo_set_cmd", "") or "").strip()
    files = patched_files(tp)
    news = [f for f, n in files if n]
    mods = [f for f, n in files if not n]
    v = []
    if "git clean" in b:
        v.append("uses `git clean` (structural rejects it)")
    if "git reset" in b:
        v.append("uses `git reset` (too broad; wipes agent work)")
    for f in news:
        if re.search(r"git checkout\b.*\b" + re.escape(f), b):
            v.append(f"`git checkout ... {f}` but {f} is NET-NEW (not in HEAD) -> pathspec fail -> oracle 0.0")
        if not re.search(r"\brm\b[^&|;]*\b" + re.escape(f), b):
            v.append(f"net-new test file {f} is NOT cleared by an `rm` -> test_patch 'already exists' -> oracle 0.0")
    for f in mods:
        if re.search(r"\brm\b[^&|;]*\b" + re.escape(f), b):
            v.append(f"`rm {f}` but {f} is MODIFIED (exists in base) -> should be `git checkout HEAD -- {f}`")
    if "\n" in b:
        v.append("before_repo_set_cmd is multi-line; test.sh runs only the last line -> keep it single-line (&&-join)")
    return v


def main(argv):
    roots = argv[1:] or ["."]
    total, bad = 0, 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("jobs", "deprecated", "node_modules", ".git")]
            if "config.json" not in filenames:
                continue
            if not dirpath.endswith(os.path.join("tests")):
                continue
            cfg = os.path.join(dirpath, "config.json")
            if os.sep + "environment" + os.sep in cfg:
                continue
            total += 1
            viol = check_config(cfg)
            if viol:
                bad += 1
                print(f"\n[VIOLATION] {cfg}")
                for x in viol:
                    print(f"    - {x}")
    print(f"\nScanned {total} grading config.json; {bad} with violations.")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
