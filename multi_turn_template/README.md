# Multi-Turn Task Template (copy me)

A fillable skeleton for a **3-step multi-turn** SWE-Bench task. Copy this dir to
`<project>-<name>-<author>/` and fill every `<PLACEHOLDER>`. Read
`MASTER_MULTITURN_TASK_SPEC.metacode.md` (repo root) for the full recipe; this README is the quick map.

## The one rule that matters
A multi-turn task earns its keep only if the **last step (the pivot) discriminates among the trials that
already passed step 1.** Step 3 must be a **context-override**: it reverses an assumption steps 1–2 forced the
agent to bake in, so the obvious extension of the step-1/2 code is *wrong*. If a step-1-passer also passes the
pivot every time, it's a single-turn task with padding.

## Layout
```
task.toml                      schema 1.1 · format=swe_bench_multi_turn · [[steps]] x3
tests/config.json              ROOT = INTENTIONALLY EMPTY (Eval-GT gt_resolved=0 is the known FP; do not populate)
environment/Dockerfile         bakes the shared base repo @ base_commit (rm docs, grep-guard the buggy helper)
environment/repo/pkg/          the shared base: the incomplete/buggy code the cascade builds on
steps/
  1_base_mechanism/            instruction.md · solution/solve.sh · tests/{config.json,parser.py,run_script.sh,test.sh}
  2_coupled_extension/         (same layout) — MUST have teeth (see gates)
  3_context_override_pivot/    (same layout) + tests/naive.patch   ← the discriminating step
```

## Per-step mechanics
- Each `steps/N/tests/config.json` is a **standalone** SWE-bench config. Its `patch` = **cumulative gold from
  base** (steps 1..N), applied from `base_commit`, passing that step's tests.
- `fail_to_pass` = THAT step's new tests. `pass_to_pass` = prior steps' tests (regression) + import/surface.
- `solution/solve.sh` must be **byte-identical** to that step's config `patch`.
- Instruction is **contract-only** (behavior + signatures); never name the bug, the algorithm, or the reversal.
- Instruction is **human-written before submit** (provenance). Write it **after** calibration, before submitting.

## The gates (a task ships only if all hold)
1. **Offline** (per step, no Docker): oracle all-pass · nop (test_patch only) f2p-fail.
2. **Pivot proof** (offline): `steps/3/tests/naive.patch` = an honest step-1-reuse impl (nails steps 1–2,
   extends the obvious way) — it must **fail ≥2 pivot tests across ≥2 axes**.
3. **Every-step-teeth**: for each step N≥2, step-N f2p must FAIL under step N-1's gold (not satisfiable by the
   prior step). A "too lenient" middle step is a real reviewer reject.
4. **Gold hygiene**: reference patch reads like clean production code — no busy-wait/`while True`, no private
   internals, no broad `except` swallowing in a critical path, no hard-coded magic timeouts.
5. **Difficulty (1P, the real gate)**: on a 5-trial Avocado run, the pivot's pass-rate **among step-1-passers**
   is **1–4/5** (never 0/5, never 5/5). Run local calibration from Deckhand or the codimango CLI.

## Fill order
1. Design the pivot first (pick a context-override archetype; write `naive.patch` in your head).
2. Author the base repo + steps 1→2→3 gold; prove offline gates + every-step-teeth + naive fails pivot.
3. `codimango bench run -a oracle -k 1` → mean 1.00; then `-a metacode -k 5` → check pivot among step-1-passers.
4. Only once in-band: write the human per-step instruction.md, then submit.
