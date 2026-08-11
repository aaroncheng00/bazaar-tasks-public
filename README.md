# swe-bench-aai-labs-pipeline-template

Files and prompts for high-quality SWE-Bench task generation in AAI Labs. For a lab pod that wants a human at both ends.

## Quickstart — first card in ~15 min

1. **Use this template** — Green button `Use this template` → create your `<TASK_REPO>`.

2. **Fill one file** — edit `PROJECT.md`. Every field is listed in [`SETUP.md`](SETUP.md).

3. **Run the first ideation prompt** — from your task repo root, after `PROJECT.md` is filled:
   ```bash
   cat prompts/05-ideate-commits-and-prs.md
   # copy the prompt body into your model (or use the brainstormer subagent)
   ```
   Start here: every lab has commits on day one. The other four sources need a review
   backlog or an accepted-task corpus you may not have yet.

4. **Save the result as your first card** in `pipeline/cards/`, copying
   `_TEMPLATE.md` and following the `<project>-<slug>-<author>.md` convention.
   Next: the scaffolder proves it (`claimed` → `oracle-passed`), then you write
   `instruction.md` and submit. See `pipeline/cards/README.md` for the lifecycle.

Full checklist: [`SETUP.md`](SETUP.md).

## The four-step recipe

| Step | Owner | What the human decides |
|---|---|---|
| 1. Ideation | Human picks the source, agent generates | Which seams to mine; what is worth testing |
| 2. Difficulty lever evaluation — **HUMAN GATE** | Human (+ brainstormer) | Which levers are real, and which to pull |
| 3. Scaffold + self-calibration | Machine (bounded, 1P) | *nothing* — the loop hardens only and flags any contract change |
| 4. Final evaluation + push — **HUMAN GATE** | Human | Whether it is actually good; spec rewritten in your own voice |

Only steps 2 and 4 require a human decision. Prompts never cross those gates.

## What you edit vs what you don't

| Tier | File | Who edits | Drift |
|---|---|---|---|
| **CORE** | `CORE_STANDARDS.md` | Nobody downstream | Byte-identical in all three templates |
| **TRACK** | `GOLD_STANDARD.md` | Track owner, rarely | Differs per bench type, by design |
| **PROJECT** | `PROJECT.md` | Your lab — the only file you must edit | Expected to differ everywhere |

If a sentence would be true for a lab on a different track, it belongs in CORE.

## Non-negotiables

- **Human authors `instruction.md`.** No model writes the prompt or test assertions.
- **No 3P model touches instruction, tests, or the code the model reads.** 1P or human only.
- **Oracle passes and no-op fails on the real chain before submit.** `codimango bench run -a oracle` must be `1`. There is no `nop` agent — prove the no-op by running the verifier against the unmodified base.
- **Difficulty is a trap, not effort.** If the obvious fix has no trap the frontier could miss, do not build it.
- **Dead ends go to `pipeline/deprecated/`.** Do not delete them; record the reason.

## Where to go deeper

- Wiki SSOT (manual): https://www.internalfb.com/wiki/AAI_Labs/Data_Generation/Automation/
- Who may author what: [Model Role in Task Creation](https://fb.workplace.com/groups/aaitaskquality/permalink/1074223732270508/)
- Track bar for this repo: [`GOLD_STANDARD.md`](GOLD_STANDARD.md)
- Prompts and cards: [`prompts/README.md`](prompts/README.md) · [`pipeline/cards/README.md`](pipeline/cards/README.md)

Checks: `pipeline/checks/run_all.sh` — the only command you need to remember.

Skeletons: `single_turn_template/` and `multi_turn_template/` — already included, see `SETUP.md` §3.

