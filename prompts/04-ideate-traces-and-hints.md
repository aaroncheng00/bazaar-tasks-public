# 04 — Ideate from traces and hints

**Purpose:** Turn real execution traces and reviewer hints into task ideas.

**When to run:** When you have agent traces, verifier logs, or reviewer comments that point at a wedge.

**Prompt — copy everything below into your model:**

```
You are helping a lab for <TRACK>. Read CORE_STANDARDS.md and GOLD_STANDARD.md.

Context: you have traces or hints from prior runs on <PROJECT_REPO>
(e.g. verifier logs, reviewer notes, flaky stules). Use them to propose ideas where
the obvious attempt fails on a coupled seam.

For each idea:
- trace or hint that suggests the seam
- target workflow and the coupled rules a shallow attempt would miss
- novelty risk and difficulty hypothesis (which model lands 1-4/5, why)
- anti-cheat notes (what a stub would do)

Do not write instruction.md. Do not author test assertions. Stop at the card.
Source: wiki Prompts — Traces and Hints.
```

**What you should get back:** Card sketches grounded in a concrete trace or hint, not speculation.

