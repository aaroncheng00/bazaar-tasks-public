# AAI Labs SWE-Bench task-creation template

Parameterized template for minting new single-turn SWE-bench tasks against
`<PROJECT_REPO>`, derived from `<EXAMPLE_TASK>`. The **base
commit is the main knob**; the rest is the task contract you author.

## What's here

```
environment/Dockerfile   # builds the "before" state @ BASE_COMMIT (feature absent)
task.toml                # task metadata (fill placeholders)
instruction.md           # agent-facing prompt (fill)
solution/solve.sh        # oracle: applies the GOLD patch FROM config.json (single source)
tests/config.json        # THE task contract: gold patch, hidden tests, fail/pass_to_pass
tests/test.sh            # harness grader wrapper (verbatim from the working task)
tests/run_script.sh      # pytest runner (PYTHONPATH=/app/src)
tests/parser.py          # pytest->JSON contract parser (do not weaken)
validate.sh              # 3-step proof loop (base red / oracle green / naive partial)
.gitignore               # keeps the token + local artifacts out of git
```

## The four coupled decisions

A task is not just the base commit. Pick these together:

1. **Base commit** (`_base_commit_sha` in `config.json`, fed to the Docker `--build-arg`):
   a commit where the target feature is **absent**.
2. **Gold patch** (`config.json.patch`): the reference implementation. `solve.sh`
   applies exactly this — no separate copy (avoids the oracle/gold divergence bug).
3. **Hidden tests** (`config.json.test_patch` + `fail_to_pass`): red at base, green
   with gold, and grading **behavior/properties**, not one implementation.
4. **`pass_to_pass`**: existing tests that already **exist AND pass at your base
   commit** (regression guard). If you pick an earlier base, re-check these.

## How to create a task

1. `cp -r <project>-task-template <new-task-dir>`
2. Choose the base commit; set `_base_commit_sha` and `instance_id` in
   `tests/config.json`; fill `task.toml`, `instruction.md`.
3. Write the gold patch into `config.json.patch` and the hidden tests into
   `config.json.test_patch`; list `fail_to_pass` / `pass_to_pass` /
   `selected_test_files_to_run`.
4. Generate a fresh canary GUID in `environment/Dockerfile` (don't reuse another
   task's).
5. (Recommended) write a `tests/naive.patch` — a plausible happy-path impl that
   should only partially pass — to prove the suite discriminates quality.
6. Validate:
   ```bash
   echo 'ghp_your_pat' > ~/.<PROJECT>_gh_token   # gitignored, never committed
   GH_TOKEN_FILE=~/.<PROJECT>_gh_token ./validate.sh
   ```
   Expect: **base fail_to_pass RED, oracle all-green reward 1, naive partial.**

## Security (fixed vs the original task)

The original `<EXAMPLE_TASK>` **committed a live GitHub PAT** in
`environment/github_token.txt`. This template does NOT: the token is passed to the
build via `--mount=type=secret` (BuildKit) and never enters a layer or git history.
Keep it that way — put the PAT in a gitignored file and pass it via `GH_TOKEN_FILE`.

## Known follow-ups (same as the source task, deliberately deferred)

- Digest-pin the base image (`python:3.12-slim@sha256:...`) and hash-lock deps
  (`--require-hashes`) before treating an image as frozen.
- Prefer vendoring a pinned repo snapshot over cloning the private repo at build,
  so tasks build fully credlessly (matching how they already grade).
