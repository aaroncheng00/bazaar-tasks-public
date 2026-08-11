# 05 — Ideate from commits and PRs

**Purpose:** Find real bugs or gaps in the product history that could become graded tasks.

**When to run:** When you have access to the commit or PR history of <PROJECT_REPO>.

**Prompt — copy everything below into your model:**

```
You are helping a lab for <TRACK>. Read CORE_STANDARDS.md and GOLD_STANDARD.md.

Task: scan recent commits or PRs in <PROJECT_REPO> for bug fixes, edge-case additions,
or under-tested modules. Look for fixes where the obvious patch would be wrong on a
coupled case — those are the best candidates.

For each candidate:
- link the commit/PR and the real behavior gap
- record the commit's author in `source_author` (leave blank if it is my own commit); `author` stays the person who will own the task through submission
- why the naive fix is self-defeating or graded
- novelty band and duplicate check
- proposed test shape (behavior only, no hidden cases)

Do not write instruction.md. Do not author tests. Do not quote private code verbatim.
Stop at the card sketch. The human approves before scaffolding.
Source: wiki Prompts — Commits and PRs.
```

**What you should get back:** Commit-anchored card sketches with the real gap and the trap that makes it graded.

