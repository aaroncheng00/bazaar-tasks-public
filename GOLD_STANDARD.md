# GOLD_STANDARD — SWE-Bench Track

> This file is the **track delta** for SWE-Bench. Read `CORE_STANDARDS.md` first;
> that file is the shared base. This file adds only what is distinct for this bench type.

## Build vs Avoid — SWE-Bench

Difficulty must be a **reasoning trap, a coupled invariant, or a graded suite** — never
raw effort or line count.

Avoid — frontier-trivial / no gap (reject at brainstorming):

- Performance or allocation tasks where the frontier writes the optimal version on
  the first try. A budget cannot force an algorithm; graded suites only catch buggy hand-rolls.
- Mechanical consolidation refactors (deduplicating match arms, moving repeated code
  with no behavioral trap). All models do it correctly.
- Toy, textbook, LeetCode-style, language-translation, or synthetic inject-then-fix
  tasks. No gap and the fix is often publicly searchable.
- Tasks grounded in a public PR, issue, StackOverflow answer, or tutorial.

Build — shapes that actually clear the gate (per `CORE_STANDARDS.md` §2):

- **Self-defeating-fix bug**: a real bug where the obvious symptom fix is wrong on a
  coupled, sibling, or later-stage case. The model must discover the coupling, not recall it.
- **Correctness trap with a graded hidden suite** that spreads trivial, single-rule,
  and coupled cases so a shallow attempt partially fails.
- A genuinely under-tested broad module where the model must understand the loop or
  state contract rather than simulate one happy path.
- Refactor / testing / iteration tasks when they exercise real behavior and resist
  one-pass pattern matching.

Pick targets by: does the obvious solution have a trap the frontier could miss?
If no, do not build it.

## Task Layout — SWE-Bench

Start every task by copying the in-repo skeleton:

```bash
cp -r single_turn_template <TASK_DIR>
# or for a 3-step cascade:
cp -r multi_turn_template <TASK_DIR>
```

Upstream single-turn reference is `codimango/swe-bench-pro-template`; the multi-turn layout has no upstream — see `SETUP.md` § Skeletons.

Then adapt the coupled pieces together:

- `instruction.md` — **human-authored** final prompt. State symptom, contract,
  invariant, and budget; never name the bug category, the fix, or the hidden edge cases.
  The scaffolder may leave `instruction.draft.md` but must not write the final file.
- `task.toml` — include `swe-bench-pro`, `aai-labs`, and track tags. Fill placeholders,
  keep timeouts and resources realistic.
- `environment/Dockerfile` — clone/reset to the pinned `<BASE_COMMIT>` and re-init a
  clean single-commit repo. Use BuildKit secrets via `--mount=type=secret,id=gh_token`,
  never commit a token. Keep the token in a gitignored file (e.g. `<GH_TOKEN_FILE>`)
  and pass via `GH_TOKEN_FILE`. Wipe history after reset for hermetic grading.
- `tests/config.json` — **the contract**. Keep `patch`, `test_patch`, `fail_to_pass`,
  `pass_to_pass`, and `selected_test_files_to_run` in sync.
  - `before_repo_set_cmd` — see `CORE_STANDARDS.md` §6 / `pipeline/checks/`.
- `solution/solve.sh` — applies exactly the patch from `tests/config.json` (single source).
- `tests/` — harness wrapper (`test.sh`, `run_script.sh`) and JSON parser (`parser.py`)
  that emit the documented reward. Keep the README note on measured pass rates.
- `solution/gold.patch` — the only file the harness uploads; read nothing outside `solution/`.

## Track-Specific Hygiene — SWE-Bench

- Pin all deps to exact versions; digest-pin the base image when frozen.
- Keep source and test paths disjoint so clearance of net-new test files never touches the fix.
- Validate with the repo template's `validate.sh` and then with a real bench run on a
  built image (base red, oracle green reward `1`, no-op `0`) before human spec.

## Delta on Universal Principles

For this track, principle 11 (reproducibility) means: every Docker build is offline
and hermetic; no network at grade time, no wall-clock timing assertions, and seeded
randomness only. Principle 3 (spec style) for SWE means: describe the failing
behavior and the invariant the fix must preserve; the model must infer the strategy.

