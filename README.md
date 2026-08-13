# bazaar-swe-aai-pipeline

SWE-Bench task generation for the **Bazaar** AAI Labs pod. Tasks are harvested from real
commits in the Bazaar product repo, with a human at both ends.

> **This is the pod's shared repo, not a template.** Clone it — do **not** click
> `Use this template`. Forking gives you your own card board, which destroys the
> dedupe mechanism the whole recipe depends on. One repo, one board, many authors.

- **Product repo (system under test):** [`metainternal-aai/aai_labs_bazaar`](https://github.com/metainternal-aai/aai_labs_bazaar)
- **This repo (pipeline + tasks):** `codimango/bazaar-swe-aai-pipeline`
- **Lab config:** [`PROJECT.md`](PROJECT.md) · **Onboarding:** [`SETUP.md`](SETUP.md)

## Quickstart — first card in ~15 min

1. **Clone and get access**

   ```bash
   git clone https://github.com/codimango/bazaar-swe-aai-pipeline.git
   cd bazaar-swe-aai-pipeline
   ```

   You also need read access to the product repo and the `codimango` CLI
   (internal Manifold wheel via `uv tool install` — **not** on PyPI). See [`SETUP.md`](SETUP.md) §2.

2. **Read the board before proposing anything.** `pipeline/cards/` is the pod
   dashboard and the only dedupe mechanism. Check what is already `claimed`.

3. **Card one of your own commits.** Default: you harvest your own work — the
   person who wrote the fix knows why the obvious approach was wrong, and that
   *is* the trap. Run the ideation prompt:

   ```bash
   cat prompts/05-ideate-commits-and-prs.md
   # copy the prompt body into a 1P model (or use the brainstormer subagent)
   ```

4. **Save it as a card** — copy `pipeline/cards/_TEMPLATE.md` to
   `pipeline/cards/bazaar-<slug>-<author>.md`, set `status: proposed`.
   Then: human approves levers → scaffold → prove → you write `instruction.md` → submit.
   Lifecycle in [`pipeline/cards/README.md`](pipeline/cards/README.md).

**Claim before you build.** Set `status: claimed` and `claimed_by` *before* scaffolding
so a second person picks a different card.

Full checklist: [`SETUP.md`](SETUP.md).

## Task roster

| Task dir | Card | Author | Base | Oracle | Status |
|---|---|---|---|---|---|
| `aacheng_bazaar__r2-presign-attach-35952bf-v1` | `bazaar-r2-presign-attach-aacheng` | aacheng | `35952bf` | 3/3 @ 1.0 | `claimed` — BASE/no-op proof pending |
| `aacheng_bazaar__rls-isolation-leak-35952bf-v1` | `bazaar-rls-isolation-leak-aacheng` | aacheng | `35952bf` | 4/4 RLS @ 1.0 job 2026-08-13__14-48-16__26422e (BASE 0/4 RED) | `claimed` — oracle-passed, ready for push |

Update this table when a card changes status. `deprecated/` entries stay out of the roster
but keep their card file with a recorded reason.

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
| **PROJECT** | `PROJECT.md` | Our lab — the only file we edit | Expected to differ everywhere |

If a sentence would be true for a lab on a different track, it belongs in CORE.

## Non-negotiables

- **Three artifacts are human-or-1P only:** `instruction.md`, the hidden tests, and the
  code the model reads. A **3P model may only gather, propose, scaffold, prove, and
  calibrate** — never write `instruction.md` or test assertions, at any stage. Rewriting a
  3P draft afterwards does not clear provenance: the check reads the edit history.
  Everything else — `gold.patch`, Dockerfile, `task.toml`, compose, `solve.sh`, running
  proofs, diagnosing failures — is fair game for any model. Full rule: `CORE_STANDARDS.md` §1.
- **The human authors the final prompt** and owns the difficulty call and the submission.
- **Oracle passes and no-op fails on the real chain before submit.** `codimango bench run -a oracle`
  must be `1`. There is no `nop` agent — prove the no-op by running the verifier against
  the unmodified base. `validate.sh` in a task dir runs all three steps
  (BASE red / ORACLE green / NAIVE partial).
- **Difficulty is a trap, not effort.** If the obvious fix has no trap the frontier could
  miss, do not build it.
- **Run one bench job at a time.** Concurrent jobs manufacture `AgentInstallError`, build
  `rc=130`, and `CancelledError` — infra noise that reads exactly like difficulty.
- **Dead ends go to `pipeline/deprecated/`.** Do not delete them; record the reason.

## Bazaar-specific notes

- **The product repo is private**, so cloud builders have no git credentials and a token
  clone fails. Tasks vendor a snapshot instead: `COPY ./repo` into the image with
  `dotgit` renamed to `.git`. See [`SETUP.md`](SETUP.md).
- **Base image needs `git` built in.** `python:3.12-slim` does not have it, and
  `apt` fails in the sandbox (`deb.debian.org` DNS returns a documentation IPv6 range).
  Use the full `python:3.12` ECR mirror, pinned by digest.
- **Where Bazaar bugs hide** — RLS/tenant isolation by `app_id`, integer `price_cents`,
  cursor pagination tie-breaks, `Idempotency-Key` replay, the offer state machine, and the
  OpenAPI→SDK contract guard. Domain notes in [`PROJECT.md`](PROJECT.md).

## Where to go deeper

- Wiki SSOT (manual): https://www.internalfb.com/wiki/AAI_Labs/Data_Generation/Automation/
- Who may author what: [Model Role in Task Creation](https://fb.workplace.com/groups/aaitaskquality/permalink/1074223732270508/)
- Track bar for this repo: [`GOLD_STANDARD.md`](GOLD_STANDARD.md)
- Prompts and cards: [`prompts/README.md`](prompts/README.md) · [`pipeline/cards/README.md`](pipeline/cards/README.md)

Checks: `pipeline/checks/run_all.sh` — the only command you need to remember.

Skeletons: `single_turn_template/` and `multi_turn_template/` — already included, see `SETUP.md` §3.
