<!-- core-version: 1.2.0 -->
# CORE_STANDARDS — Platform Task Quality Bar

> **Do not edit downstream.** This file is the shared, versioned quality bar for
> every lab and every track. It must stay byte-identical in all three templates.
> Propose changes upstream; bump `core-version` on any policy change.

This file is the single source of truth for rules that are true for **every**
track and every lab. Track-specific deltas live in `GOLD_STANDARD.md`; per-lab
config lives in `PROJECT.md`.

---

## 1. Provenance and Authorship — Read First

This is the rule that gets submissions rejected most often. It is non-negotiable.

- `instruction.md`, the hidden tests, and the code the model reads are **human-authored
  or 1P**. A third-party model (3P) must never author, edit, or draft them. The governing
  reference is [Model Role in Task Creation](https://fb.workplace.com/groups/aaitaskquality/permalink/1074223732270508/) — read it before anything else.
- **The line is 1P vs 3P, not which phase you are in.** A 1P model may author the
  instruction and the tests, including tightening them during self-calibration. A 3P model
  may only gather, propose, scaffold, prove, and calibrate — never write `instruction.md`
  or test assertions, at any stage. Rewriting a 3P draft afterwards does not clear
  provenance: the check reads the edit history, not the final text.
- **Self-calibration hardens only.** The 1P loop may tighten wording, add hidden cases, and
  tighten assertions. It may never relax an assertion, widen a tolerance, delete a case,
  telegraph the trap, or move the contract.
- The human author owns the final prompt, the difficulty call, and the submission.
  Leave any model-generated draft as an un-prescriptive note (e.g. `instruction.draft.md`)
  for the human to rewrite.
- The pipeline keeps a human at both ends: a human approves the levers before
  scaffold, and a human authors the spec after proof.

If you find yourself letting a model write the task prompt to save time, stop —
that change actively lowers quality.

---

## 2. Difficulty Gate

Difficulty comes from a **reasoning trap, a coupled invariant, or a graded
behavior suite that partial solutions partially fail**. Never from raw effort or
line count.

**Current policy (tracks the platform quality guidance — a future change is a
core version bump):**

- A task is viable only if it is **Opus-hard OR Avocado-hard** after calibration
  with 5 trials (`-k 5`):
  - `1-4/5` means at least one pass and at least one fail in 5.
  - Both models `5/5` = too easy -> reject.
  - Both models `0/5` = broken or infeasible -> reject (see infra note below).
- Preferred stretch band: **Avocado `1-3/5` and Opus scores higher than Avocado**
  (a graded gap where the stronger model still separates).
- Calibrate against **measured model behavior**, not intuition. The OR-gate above
  is the floor; the stretch band is the goal.

**Infra, not difficulty:**

- Run **one bench job at a time**. Concurrent jobs fabricate infra errors that read
  as difficulty.
- A `0/N` run that coincides with an agent crash or an infra failure is **infra,
  not a difficulty signal**. Re-run before judging.
- The platform is **stricter than local validation**. A locally-green task can still
  fail on the platform due to credless builds, hermetic networks, or stricter
  graders. A local `oracle=1` does not guarantee a platform `1`.

---

## 3. Novelty Gate / Recall Test

Every idea must be original enough for training value.

- Search public PRs, issues, blog posts, StackOverflow, docs, and similar
  benchmark tasks (WebSearch) **before** proposing.
- Record a novelty risk band on the card: `low`, `medium`, or `high` with a short
  rationale. Advance only if `low` or `medium` is credible.
- A task whose solving path is recallable is low-value: if the answer is a named
  algorithm, a standard format, a public bug pattern, or a Wikipedia-page problem,
  rename it or reject it.
- Never translate a task between languages to make it look new (contamination +
  low value).
- Keep the solving path reasoning-bound: the model must **discover** the trap, not
  recall a known fix.

---

## 4. Anti-Cheat Checklist

Hidden tests and verifiers must reject shortcuts. Apply every row.

| Cheat vector | Required defense |
|---|---|
| No-op / stub solution | Verifier gives reward `0`; stub scores below any bar |
| Hardcoded outputs | Grade on held-out slices the agent never saw; no expected-output file reachable from the agent workspace (`find` the agent dir reveals no reference) |
| String / substring matching instead of real behavior | Assert behavior and invariants, not exact string equality |
| Simpler algorithm that skips the novel part | Suite includes coupled / cross-level cases that a shallow algorithm fails; single-case tasks are not graded |
| `or True`, no-assert, swallowed-exception, always-pass | Tests must have real assertions that fail on broken code; a no-assert suite is a reject |
| Ground-truth / reference file reachable | Reference stays verifier-side; images wipe history and mount only what the agent may read |

- Ship tests via `test_patch` only. Images remove git history for hermetic grading.

---

## 5. Card Status Protocol

Cards live in `pipeline/cards/` and move through one lifecycle. The file name
mirrors the track work; the status field is the source of truth.

```
draft -> proposed -> claimed -> oracle-passed -> submitted
                          \-> rejected
                          \-> deprecated/ (moved after review)
```

- `draft` — private scratch; not yet gated.
- `proposed` — gated idea, no scaffold yet. Set by the brainstormer.
- `claimed` — actively building. Set `claimed_by` and a timestamp to avoid collisions.
- `oracle-passed` — local proof complete (see §6). Hand to human for final `instruction.md`,
  calibration, and submission.
- `submitted` — human has submitted; keep the card as record.
- `rejected` — failed a gate. Must state the concrete reason so future ideation improves.
- `deprecated/` — ideas that were tried and found to be dead ends. Move the file
  there; do not delete history.

Claim-before-you-build: set `claimed` before scaffolding so two workers do not
build the same idea.

---

## 6. Local Proof Before Human Spec

The scaffolder must not mark a card `oracle-passed` until the task is proven
on a **built image over the real verifier chain**.

Required checks (all on the same built image):

- Base state (no oracle) fails the intended checks.
- Oracle solution passes all checks with reward `1` (run 3+ times for flakiness).
- Empty / no-op solution receives reward `0`.
- A plausible naive patch, when available, **partially** passes (proves the suite
  discriminates quality, not just presence).
- Repeated runs are stable; no network, wall-clock timing, unpinned randomness, or
  host-specific state affects the result.
- `solve.sh` and the reference patch are byte-identical in behavior (single source).
- No ground-truth file is reachable from the agent workspace.
- Spec and tests agree — every assertion traces to a stated requirement.

**Always confirm the real chain, not structural-only checks.** Structural-only
never catches a silent `oracle=0`.

### Two silent `oracle=0` traps — fixed once, guarded forever

Both traps silently turn a real `oracle=1` into `0` and are invisible to a
structural lint. They are the reason the checks directory exists.

1. **`before_repo_set_cmd` must be `rm -f <NET_NEW_TEST_PATHS>`**
   (single line). The verifier runs this command and then re-applies `test_patch`
   (which adds hidden tests as `new file mode`), so the command must **clear those
   net-new paths** so `test_patch` can add them cleanly.
   - Do **NOT** use `git clean` (structural check rejects it).
   - Do **NOT** use `git checkout HEAD -- <EXISTING_PATH>` — the file is not in
     `HEAD`, so git prints `pathspec did not match` then `Gold tests checkout
     failed` and the oracle scores `0.0`.
   - Use `git checkout HEAD -- <EXISTING_PATH>` **only** for a `test_patch` entry that
     **modifies** a pre-existing tracked file.
   - Source paths and test paths are disjoint, so `rm -f <NET_NEW_TEST_PATHS>` never
     touches the agent fix.
   - Keep the command single-line; a multi-line value makes the local `test.sh`
     run only its last line.
   - Preflight: `python3 pipeline/checks/check_before_repo_set_cmd.py .` must show
     `0 violations` before every push.

2. **The harness uploads only `solution/`.** Ship the reference as
   `solution/gold.patch` and read **nothing outside `solution/`** in `solve.sh`.
   The checker `check_solution_paths.py` flags any `solve.sh` that references a
   path outside `solution/`.

If either trap is present, the platform run returns `0.0` even though local
structural checks look green. Run the real oracle chain and read
`verifier/test-stdout.txt` (it prints the failing step) whenever a `0.0` appears.

---

## 7. Universal Principles

1. Make it real — a scenario a working engineer hits. One file with no context is
   usually too simple.
2. One coherent problem per task. Do not stitch unrelated bugs to hit a length.
3. Spec the model has to think about: state symptom + contract + invariant + bar.
   Never name the bug category, the fix strategy, or the hidden edge cases.
4. Spec and tests **must** agree (top revise reason). Every assertion traces to a
   stated requirement or is inferable. No hidden behavior; no over-specifying.
5. Test behavior, not output — see anti-cheat checklist.
6. Protect reference data and expected outputs. Ground truth unreachable.
7. Difficulty sweet spot — see §2.
8. Be original — see §3.
9. Do not repackage toy problems.
10. Watch for spec contradictions (prompt says X, tests expect Y -> a correct agent fails).
11. Make it reproducible: pin all deps to exact versions, no network, no
    timing/hardware-dependent assertions, no unpinned randomness, isolate state
    between runs, remove prior-run artifacts, digest-pin base images when frozen.
12. Do not translate tasks between languages.
13. Prioritize under-represented categories where they still clear the gate; span
    task types, not just one slice.

---

## 8. Known Traps and Learnings

- Performance-budget tasks false-negative under runner load. Gate on ratios,
  operation counts, or complexity, never a hard millisecond budget.
- A single pass/fail check has zero partial credit and cannot separate a shallow
  attempt from a complete one -> reviewer reject. Ship a multi-case suite or a
  mutually-exclusive mutant set.
- If every model ties at the same score with no spread, the suite has no
  discriminator -> deprecate; do not tune the threshold to force a pass.
- Difficulty is a trap, not effort. If the obvious solution has no trap the
  frontier could miss, do not build it.
- Dead ends go to `pipeline/deprecated/` with a reason. Do not delete them.
- Keep task scope to what one strong engineer can understand in a focused session.
  Two weak ideas stitched together are still weak.
- When in doubt, reject with a useful note. A clear rejection improves the next
  card more than a forced weak task.

## 9. The org quality bar (ADO north stars)

Beyond the gates above, every task is judged against three org-level north stars. Two of them the
gates already enforce; the third is on you.

- **Realistic.** A blind judge — human or agent — should not be able to tell a pipeline-produced
  task from one a person developed by hand, and it should be a problem a practicing engineer would
  actually hit. This is why every task is grounded in a real commit and never an invented scenario.
- **Diverse.** Avoid many subtle variations of the same task, reasoning, or bug. **The pipeline
  does not guard this for you** — the card board dedupes identical cards, not shape monoculture.
  Mining one project's commit stream day after day is exactly how a corpus collapses into one
  shape, so check each wave against the live taxonomy and the accepted-task corpus before you
  build.
- **Genuinely hard.** Models must fail for legitimate reasoning reasons. A task with more than one
  reasonable interpretation, an implementation cheat, or an exploitable context is **invalid**, not
  hard. Tuning difficulty by trial and error is the fastest way to produce an invalid task instead
  of a hard one — which is why the loop may only harden, never weaken, and why the contract must
  not move.

## 10. Audit trail

A task must be attributable to the pipeline and models that produced it. In `task.toml`
`[metadata]`, `tags` must contain:

- `"synthetic"` — marks the task as agent-generated
- the **pipeline name**, so the generator gets credit for the work
- **every model** used to generate the task
- `"human-reviewed"` — if a human edited or curated it after generation (in this pipeline, always
  true: a human approves the levers and writes the spec)

The skeletons ship these pre-filled and `pipeline/checks/check_audit_tags.py` fails the run if they
go missing.

**Before deploying this pipeline on a track**, or landing tasks produced by it, contact the ADO
agentic-acceleration core team. Deployment also needs a LAMA (legal) review covering licenses and
obligations for any third-party model providers.
