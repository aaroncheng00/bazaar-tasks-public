---
status: proposed
slug: replace-with-task-slug
title: Replace with short task title
author: replace-with-author        # owns the task through submission — gets the credit
source_author:                     # who wrote base_commit, if you harvested someone else's work
created_at: YYYY-MM-DD
claimed_by:
task_dir:
base_commit:
novelty_risk: medium
difficulty_hypothesis: at least one target model lands 1-4/5
taxonomy:
  type:
  subdomain:
  usecase:
---

# Idea

Describe the real behavior gap, target module or workflow in <PROJECT_REPO>, and why this should become a task.
Keep the spec non-prescriptive — no fix strategy, no hidden case details.

# Why This Is Hard

Explain the reasoning trap, coupled invariant, or graded behavior surface that a weaker model is likely to partially miss.
Name the seam (e.g. sentinel ordering, short-circuit, sign-extension, leakage, distribution shift).

# Novelty Check

Record searches performed (public PRs, issues, blogs, StackOverflow, docs, similar benchmarks), public matches considered, and why the solving path is not recallable. State the risk band (`low` / `medium` / `high`) with rationale.

# Proposed Test Shape

Describe the behavior contract to test without listing privileged hidden cases or expected outputs.
State the grade shape (multi-case suite or mutant set) and how a naive attempt partially fails.

# Anti-Cheat Notes

Explain how tests should reject no-op, hardcoded, string-match, simpler-algorithm, and no-assert shortcuts.
Note that ground truth stays verifier-side and is not reachable from the agent workspace.

# Scaffold Notes

Filled by the oracle-scaffolder. Include task directory, base commit, proof commands, reward results (base / oracle / no-op / naive), and any remaining human actions.

# Rejection Notes

If rejected, explain the exact failed gate and what future brainstorming should avoid or try differently.

