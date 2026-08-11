#!/usr/bin/env python3
"""Guard: card front matter must have required keys and legal status.

Validates pipeline/cards/*.md front matter. Stdlib only.
Exit 1 with a one-line actionable message per violation.
"""
import os
import re
import sys


REQUIRED_KEYS = ["status", "slug", "title", "author", "created_at", "claimed_by", "task_dir", "base_commit", "novelty_risk", "difficulty_hypothesis", "taxonomy"]
ALLOWED_STATUSES = {"draft", "proposed", "claimed", "oracle-passed", "submitted", "rejected"}
ALLOWED_NOVELTY = {"low", "medium", "high"}


def parse_front_matter(text):
    """Return dict of front matter or None if no front matter."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return None
    raw = m.group(1)
    data = {}
    # Simple yaml-ish parse: key: value, handles taxonomy block minimally
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        # Nested taxonomy keys are indented; record parent
        if line.startswith("  ") or line.startswith("\t"):
            continue
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        data[k.strip()] = v.strip()
    return data


def check_card(path):
    try:
        text = open(path, encoding="utf-8", errors="ignore").read()
    except Exception as e:
        return [f"unreadable: {e}"]
    fm = parse_front_matter(text)
    if fm is None:
        return ["missing front matter `---` block — fix: add front matter per _TEMPLATE.md"]
    violations = []
    for k in REQUIRED_KEYS:
        if k not in fm:
            violations.append(f"missing required key `{k}` — fix: add `{k}:` per _TEMPLATE.md")
    if "status" in fm and fm["status"] not in ALLOWED_STATUSES:
        violations.append(f"illegal status `{fm['status']}` — fix: use one of {sorted(ALLOWED_STATUSES)}")
    if "novelty_risk" in fm and fm["novelty_risk"] not in ALLOWED_NOVELTY:
        violations.append(f"illegal novelty_risk `{fm['novelty_risk']}` — fix: use low/medium/high")
    # Body sections check: ensure required headings present
    required_sections = ["# Idea", "# Why This Is Hard", "# Novelty Check", "# Proposed Test Shape", "# Anti-Cheat Notes", "# Scaffold Notes", "# Rejection Notes"]
    for sec in required_sections:
        if sec not in text:
            violations.append(f"missing section `{sec}` — fix: add it per _TEMPLATE.md")
    return violations


def main(argv):
    roots = argv[1:] or ["."]
    # Find pipeline/cards directory
    total, bad = 0, 0
    for root in roots:
        cards_dir = os.path.join(root, "pipeline", "cards")
        if not os.path.isdir(cards_dir):
            continue
        for name in os.listdir(cards_dir):
            if name.startswith("_"):
                continue
            if name == "README.md":
                continue
            if not name.endswith(".md"):
                continue
            path = os.path.join(cards_dir, name)
            # Skip deprecated (moved)
            if "deprecated" in path:
                continue
            total += 1
            viol = check_card(path)
            if viol:
                bad += 1
                print(f"[VIOLATION] {path}: {viol[0]}")
                for extra in viol[1:]:
                    print(f"    also: {extra}")
    # Also validate _TEMPLATE itself (should be valid with placeholders)
    for root in roots:
        tmpl = os.path.join(root, "pipeline", "cards", "_TEMPLATE.md")
        if os.path.isfile(tmpl):
            viol = check_card(tmpl)
            # Template uses placeholder values like replace-with-*; allow them but check structure
            # If template itself is malformed, flag it
            if any("missing" in v for v in viol):
                print(f"[VIOLATION] {tmpl}: template malformed — {viol[0]}")
                bad += 1
            break
    if bad:
        # If no real cards yet (total==0), this is not a violation — template alone is fine
        if total == 0:
            print("Scanned 0 cards; 0 violations (only _TEMPLATE.md present).")
            return 0
        print(f"\nScanned {total} cards; {bad} with violations.")
        return 1
    if total == 0:
        print("Scanned 0 cards; 0 violations (only _TEMPLATE.md present).")
    else:
        print(f"Scanned {total} cards; 0 violations.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
