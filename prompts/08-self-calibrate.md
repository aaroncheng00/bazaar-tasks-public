# 08 — Self-calibrate

**Purpose:** Run the calibration panel locally and read the signal, not the hope.

**When to run:** After scaffold is `oracle-passed` and before the human writes the final spec.

**Prompt — copy everything below into your model:**

```
You are calibrating for <TRACK>. Read CORE_STANDARDS.md § Difficulty Gate.

Task: on the built image for <TASK_DIR>, run:
- codimango bench run -p <TASK_DIR> -a oracle -k 3   (expect mean 1.0)
- verifier against the unmodified base                (expect 0.0 — there is no `nop` agent)
- codimango bench run -p <TASK_DIR> -a metacode -m meta/avocado-5.14-code -k 5   (record the 1-4/5 band)
  (`-a avocado` no longer exists; the `meta/` model prefix is required. Model ids churn —
   confirm the current one against the codimango CLI docs before a calibration wave.)

Notes:
- Run one bench job at a time; concurrent jobs fabricate infra errors that read as difficulty.
- A 0/N with a crash is infra, not difficulty — re-run before judging.
- The platform is stricter than local; a local 1 does not guarantee a platform 1.

Hardening rules (1P loop only): you may tighten the spec's wording, add hidden cases, and tighten assertions — in the harder direction only. Never relax an assertion, widen a tolerance, delete a case, telegraph the trap, or move the contract (would a solution that passed before now fail, or one that failed now pass? then stop and hand back). A 3P model must not touch instruction.md or tests at any stage. The final instruction.md is human-authored regardless.

Output: a calibration memo with measured pass rates, the 1-4/5 verdict, and whether the task is in the stretch band (Avocado 1-3/5, Opus > Avocado) or needs a lever tweak.
Source: wiki Prompts — Self-Calibrate.
```

**What you should get back:** A calibration memo with real numbers and a keep / tweak / reject recommendation.

