# 07 — Scaffold and prove

**Purpose:** Turn a gated card into a locally-proven scaffold without crossing the human spec gate.

**When to run:** After the human has approved the levers on a `proposed` card.

**Prompt — copy everything below into your model:**

```
You are scaffolding for <TRACK> from card pipeline/cards/<TASK_SLUG>-<AUTHOR>.md.
Read CORE_STANDARDS.md and GOLD_STANDARD.md, plus the card and the skeleton fetched in SETUP.md.

Steps:
1. Claim the card: set status=claimed, claimed_by=<AUTHOR>, timestamp.
2. Copy `single_turn_template/` (or `multi_turn_template/` for a cascade) from this repo to <TASK_DIR> and adapt the coupled pieces together (Dockerfile, task.toml, hidden test patch, solution/gold.patch, verifier config).
3. Build the image and prove on the REAL chain:
   - base fails the intended checks
   - oracle passes with reward 1 (3+ runs, stable)
   - no-op gives 0
   - naive patch partially passes (proves partial credit)
4. Run the anti-cheat checklist from CORE_STANDARDS.md and the silent-trap preflight:
   python3 pipeline/checks/check_before_repo_set_cmd.py <TASK_DIR>
   python3 pipeline/checks/check_solution_paths.py <TASK_DIR>
   (must be 0 violations)
5. Do NOT write instruction.md. Leave an un-prescriptive draft for the human to rewrite
   (e.g. instruction.draft.md that states only symptom, contract, invariant, and bar —
   never the fix strategy or hidden edge cases). The final instruction.md is human-authored.
6. On success, set status=oracle-passed with scaffold notes (task dir, base commit, proof commands, rewards). On failure, set status=rejected with the concrete failed gate.

Source: wiki Prompts — Scaffold and Prove.
```

**What you should get back:** A proven scaffold at `oracle-passed` (or a clean `rejected`), plus `instruction.draft.md` that the human rewrites. No final `instruction.md`, no test assertions authored beyond the hidden suite harness.

