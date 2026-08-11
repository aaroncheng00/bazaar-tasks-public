# 06 — Evaluate difficulty levers

**Purpose:** Pressure-test that the levers are real before you scaffold.

**When to run:** After ideation (01–05) produces a card sketch, before claiming it.

**Prompt — copy everything below into your model:**

```
You are helping a lab for <TRACK>. Read CORE_STANDARDS.md and GOLD_STANDARD.md.

Card to evaluate: <TASK_SLUG> (proposed in pipeline/cards/)

Task: gate the difficulty levers, not the idea's appeal.
- Is the deliverable graded (model must execute, not just name a method)?
- Does the obvious solution fail on a coupled seam? Name the seam.
- Does the hidden suite give partial credit so a naive attempt lands mid-range?
- Would a model that ties all cases at one score mean no discriminator?
- Calibrate: which model plausibly lands 1-4/5 and why? If tie at 5/5 or 0/5, reject.

Output: a short gate memo with PASS / REJECT per lever and the human decision.
Do not write instruction.md. Do not author test assertions. This is a gate, not a scaffold.
Source: wiki Prompts — Difficulty Levers.
```

**What you should get back:** A gate memo that says which lever is real and which is wishful, so the human can approve or kill the card.

