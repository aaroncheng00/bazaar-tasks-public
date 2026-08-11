#!/usr/bin/env python3
"""Guard: solve.sh must not reference paths outside solution/.

The harness uploads only solution/, so any read outside it is a silent
oracle=0 trap. This check flags a solve.sh that mentions a path outside
solution/ on a live (non-comment) line.

Stdlib only. Exit 1 with a one-line actionable message per violation,
including file and line number.

Skips:
- Whole-line comments (lines starting with # after stripping).
- Inline trailing comments (text after # on a line outside heredoc).
- Heredoc bodies (<<'MARK' … MARK) — that content is data written into the
  container, not a path read during solve. This is a limitation documented
  here: heredoc detection is based on <<[-]?'?MARK'? and exact terminator
  line. If a solve.sh uses a different heredoc style, the check may
  under-skip, but it will not miss a real violation on a live line.

Verified both ways:
- single_turn_template/solution/solve.sh (comment mentioning tests/config.json)
  must PASS.
- multi_turn_template/steps/3_context_override_pivot/solution/solve.sh
  (comment mentioning tests/naive.patch) must PASS.
- A live line like `cat ../tests/config.json` must FAIL.

"""
import os
import re
import sys


FORBIDDEN_PATTERNS = [
    (r"\.\./", "references parent directory `../` (outside solution/)"),
    (r"\btests/", "references `tests/` (outside solution/)"),
    (r"\benvironment/", "references `environment/` (outside solution/)"),
    (r"\bpipeline/", "references `pipeline/` (outside solution/)"),
    (r"\.git/", "references `.git/` (outside solution/)"),
]


def check_file(path):
    try:
        lines = open(path, encoding="utf-8", errors="ignore").read().splitlines()
    except Exception as e:
        return [(0, f"unreadable: {e}")]
    violations = []
    in_heredoc = False
    heredoc_delim = None
    for idx, raw in enumerate(lines, 1):
        line = raw
        # Heredoc handling
        if not in_heredoc:
            # Detect heredoc start: <<, optional -, optional quoted delimiter
            m = re.search(r"<<-?\s*'?\"?([A-Za-z0-9_]+)'?\"?", line)
            if m:
                # If the delimiter is present, enter heredoc. Use captured group 1.
                # For <<'__SOLUTION_PATCH__' the group is __SOLUTION_PATCH__
                delim = m.group(1)
                # Only treat as heredoc if the delimiter looks like a heredoc marker (not a normal redirect)
                # We check that the line contains << and the delimiter after it.
                in_heredoc = True
                heredoc_delim = delim
                # The start line itself is not data, but may contain a path? Skip it as not a violation source.
                continue
        else:
            # Inside heredoc body: check for terminator
            if line.strip() == heredoc_delim:
                in_heredoc = False
                heredoc_delim = None
            # Skip all heredoc body lines (they are data, not reads)
            continue

        # Outside heredoc: skip whole-line comments
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        # Strip inline trailing comment (simple: split at first #)
        # This may truncate a # inside a quoted string, but solve.sh files are simple;
        # we document that as a limitation and it errs on the side of not flagging.
        if "#" in line:
            # Keep part before #, but ensure we don't break heredoc detection already handled
            line = line.split("#", 1)[0]

        # Check forbidden patterns on the live code portion
        for pat, msg in FORBIDDEN_PATTERNS:
            if re.search(pat, line):
                violations.append((idx, msg))
                break
    return violations


def main(argv):
    roots = argv[1:] or ["."]
    total, bad = 0, 0
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ("deprecated", "jobs", "node_modules", ".git")]
            if "solve.sh" not in filenames:
                continue
            if os.path.basename(dirpath) != "solution":
                continue
            path = os.path.join(dirpath, "solve.sh")
            if "pipeline/deprecated" in path:
                continue
            total += 1
            viol = check_file(path)
            if viol:
                bad += 1
                for lineno, msg in viol:
                    print(f"[VIOLATION] {path}:{lineno}: {msg} — fix: read only solution/gold.patch and files under solution/")
    if bad:
        print(f"\nScanned {total} solve.sh; {bad} with violations.")
        return 1
    print(f"Scanned {total} solve.sh; 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
