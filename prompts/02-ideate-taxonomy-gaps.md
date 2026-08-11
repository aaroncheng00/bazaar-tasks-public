# 02 — Ideate from taxonomy gaps

**Purpose:** Fill under-represented types and subdomains before brainstorming the next idea.

**When to run:** When the roster is heavy in one type; use the taxonomy to force coverage.

**Prompt — copy everything below into your model:**

```
You are helping a lab that authors benchmark tasks for <TRACK>.
Read CORE_STANDARDS.md and GOLD_STANDARD.md.

Task: scan the roster in <TASK_REPO> (and pipeline/cards/) for taxonomy coverage
(type, subdomain, usecase) and name the 2-3 emptiest slices that still have a plausible trap.

For each gap, propose one idea that fits that slice and clears the gates:
- concrete target in <PROJECT_REPO>
- the coupled invariant or graded suite that makes it hard
- novelty risk band with rationale
- why a shallow solution would partially fail

Do not write instruction.md. Do not author test assertions. Stop at the card sketch.
Source: wiki Prompts — Taxonomy Gaps.
```

**What you should get back:** A gap map plus 2-3 card sketches targeted at empty slices, ready for the human to approve or reject.

