# 09 — Review feedback loop

**Purpose:** Turn reviewer feedback into a concrete fix plan without rewriting the spec for the human.

**When to run:** After a review (human or automated) returns revise or reject.

**Prompt — copy everything below into your model:**

```
You are helping a lab for <TRACK>. Read CORE_STANDARDS.md and the review notes for <TASK_DIR>.

Task: map each reviewer finding to the owning file and tier:
- CORE vs TRACK vs PROJECT issue?
- Is it a spec/tests mismatch, a missing anti-cheat defense, a reproducibility pin, or a scope cut?

For each finding:
- one-line root cause
- exact file and the edit to make (or the card field to update)
- whether the fix is safe to do without re-calibration

Do not write instruction.md. Do not author new test assertions beyond the harness.
Leave the final prompt edits for the human. Stop at the plan; the human applies it.
Source: wiki Prompts — Review Feedback Loop.
```

**What you should get back:** A fix plan the human can apply, with file-level edits and whether re-proof is needed.

