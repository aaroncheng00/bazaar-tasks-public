# 01 — Ideate from champion reviews

**Purpose:** Surface candidate ideas from the strongest prior tasks and their reviews.

**When to run:** At the start of ideation, when you need a broad list that already cleared the bar once.

**Prompt — copy everything below into your model:**

```
You are helping a lab that authors benchmark tasks for <TRACK> (see <PROJECT_REPO>).
Read CORE_STANDARDS.md and GOLD_STANDARD.md for the quality bar.

Context for this run:
- Task repo: <TASK_REPO>
- Look at the strongest tasks the current roster links as champions in its README or review notes, and at the gaps reviewers called out.
- Propose 3-5 new ideas that are NOT duplicates of the roster or of pipeline/cards/.

For each idea, output a short card sketch with:
- target module or workflow in <PROJECT_REPO>
- why it is frontier-hard (name the trap or graded spread, not effort)
- novelty check (searches you would run, risk band low/medium/high with rationale)
- anti-cheat shape and how a naive attempt would partially fail

Do not write instruction.md. Do not author test assertions. Stop at the idea card — the human gates it.
Source: wiki Prompts — Champion Reviews (single wording).
```

**What you should get back:** 3-5 card sketches the human can gate for levers and novelty. No scaffold, no spec, no tests.

