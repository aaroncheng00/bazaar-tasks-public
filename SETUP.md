# SETUP — Fill-in Checklist (~15 min)

Complete these steps in order. Every item is a checkbox with an exact command or edit.
When done, `pipeline/checks/run_all.sh` passes and you have your first card.

---

## 1. Fill `PROJECT.md` — the only required edit

- [ ] Open [`PROJECT.md`](PROJECT.md) and replace every placeholder (see table below).
      Each field has a comment with a worked example.
- [ ] Save and verify no placeholder remains in commands:
  ```bash
  grep -oE "<[A-Z][A-Z0-9_]+>" PROJECT.md || echo "PROJECT.md has no placeholders left — good"
  ```

Expected values: see Placeholder Reference at the bottom of this file.

---

## 2. Install the codimango CLI (internal wheel, not PyPI)

- [ ] Install via `uv` from the internal Manifold wheel:
  ```bash
  # Internal Manifold wheel, NOT on PyPI — `pip install codimango` will not find it.
  # Copy the current `uv tool install ...` command from the CLI docs (link below), run it, then:
  codimango --help   # confirms the install worked
  ```
  Docs: https://codimango.internalmeta.com/tools/cli

  Do not use `pip install codimango` — that is a different, public package.

---

## 3. Task skeletons — already included

- [ ] Verify skeletons are present:
  ```bash
  ls single_turn_template/
  ls multi_turn_template/
  # single_turn_template/ — one-shot task (see README.md inside)
  # multi_turn_template/ — 3-step cascade: 1_base_mechanism → 2_coupled_extension → 3_context_override_pivot (the pivot is the discriminator)
  ```

  The two skeletons ship in-repo so you don't need a second clone. Upstream single-turn skeletons exist at `codimango/swe-bench-pro-template` etc., but the multi-turn layout has no upstream equivalent — it's ours to maintain. See Skeletons sync status below.

- [ ] Understand the two placeholder conventions:
  - Pipeline placeholders: `<ANGLE_BRACKET_CAPS>` like `<PROJECT_REPO>`, `<TASK_SLUG>` — listed in the table below, replaced once in `PROJECT.md`.
  - Skeleton placeholders: `@@FILL:...@@` and task-internal `<...>` like `@@FILL:task-slug@@`, `@@FILL:40-hex commit...@@`, `<INPUT>`, `<WANT>` — these stay inside `single_turn_template/` and `multi_turn_template/` until you copy one to a real task dir and fill them. `grep -r "@@FILL" single_turn_template` shows everything you must replace.

- [ ] Optional upstream diff (single-turn only):
  ```bash
  # Compare vendored single-turn against upstream (example for this track)
  git clone https://github.com/codimango/swe-bench-pro-template /tmp/upstream-swe && diff -qr single_turn_template /tmp/upstream-swe/single_turn_template || true
  ```
  Replace URL with your track's upstream: `swe-bench-pro-template` | `terminal-bench-template` | `ml-bench-template`.

---

## 4. Confirm the repo is wired

- [ ] Run the local checks (stdlib only, no install):
  ```bash
  pipeline/checks/run_all.sh
  ```
  Expected: `3 checks passed, 0 failed` and exit `0`. If any check fails, fix the file it names.

---

## 5. Run the first ideation prompt

- [ ] Open [`prompts/README.md`](prompts/README.md) for the placeholder convention.
- [ ] Run the first prompt from the task repo root:
  ```bash
  cat prompts/05-ideate-commits-and-prs.md
  # copy the prompt body into your model (every lab has commits on day one;
  # the other sources need a review backlog or accepted-task corpus)
  ```
- [ ] Save the model's output as your first card (name it `<project>-<slug>-<author>.md`):
  ```bash
  cp pipeline/cards/_TEMPLATE.md pipeline/cards/example-card-alice.md
  # edit front matter: status=proposed, slug, author, etc. (see PROJECT.md)
  ```

---

## 6. What "done" looks like

- `PROJECT.md` has no `<...>` placeholders left (the grep above is clean).
- `pipeline/checks/run_all.sh` exits `0`.
- One real card exists in `pipeline/cards/` (named `<project>-<slug>-<author>.md`) with `status: proposed`.
- You can run `codimango bench validate --structural-only -p ./example-task-dir` on a skeleton copy and it is structural-green.

You are now ready for the four-step recipe in [`README.md`](README.md). The next gate is human: approve the levers before scaffolding.

---

## Skeletons — vendored and sync status

| Skeleton | Upstream | Synced | Diff command |
|---|---|---|---|
| `single_turn_template/` | `codimango/swe-bench-pro-template` | 2026-08-10 | `diff -qr single_turn_template /tmp/upstream/single_turn_template` |
| `multi_turn_template/` | None — ours to maintain (no upstream) | 2026-08-10 | `diff -qr multi_turn_template <candidate>` |

The single-turn skeleton is a vendored copy of the org's published template; the multi-turn cascade has no upstream and is maintained here. If upstream changes, diff and port the BuildKit secret / canary / `.gitignore` updates. Do not edit skeletons in place; copy one to a task dir and fill the `@@FILL` markers.

---

## Placeholder Reference

Every pipeline placeholder that appears in this repo is listed here with an example value.
After `PROJECT.md` is filled, no placeholder should remain in any command you run.

Skeleton placeholders (`@@FILL:...@@`, `<INPUT>`, `<WANT>`, etc.) use a separate convention inside `single_turn_template/` and `multi_turn_template/` — see §3 above. They are not listed here.

| Placeholder | Example value | Notes |
|---|---|---|
| `<LAB_NAME>` | `example-lab` | Your lab handle |
| `<TRACK>` | `swe-bench` | This track; also `t-bench` or `ml-bench` in sibling templates |
| `<OWNER>` | `alice@example.com` | Contact for this adoption |
| `<PROJECT_REPO>` | `github.com/codimango/example-service` | System under test |
| `<PROJECT_REPO_NAME>` | `example-service` | Repo name without org (de-identified) |
| `<EXAMPLE_TASK>` | `example-task` | Example task slug (de-identified) |
| `<PROJECT>` | `example-project` | Generic project prefix |
| `<TASK_REPO>` | `github.com/codimango/example-bench-tasks` | Where tasks live |
| `<SKELETON_REPO>` | `github.com/codimango/swe-bench-pro-template` | Upstream skeleton reference (skeletons now ship in-repo) |
| `<PROJECT_PATH>` | `./example-service` | Local checkout path |
| `<TASK_PATH>` | `./example-bench-tasks` | Local checkout path |
| `<BASE_COMMIT>` | `abc1234def5678` | Pinned commit where feature is absent |
| `<TASK_SLUG>` | `example-schema-migration-chain` | Illustrative generic slug |
| `<TASK_DIR>` | `./example-task-slug` | Local dir for a new task (same slug) |
| `<AUTHOR>` | `alice` | Card author handle |
| `<GH_TOKEN_FILE>` | `~/.example_gh_token` | Gitignored token file for Docker builds |
| `<ROSTER_PATH>` | `README.md` | Task roster location |
| `<NET_NEW_TEST_PATHS>` | `tests/new_suite.py` | Example net-new test file cleared by `before_repo_set_cmd` |
| `<EXISTING_PATH>` | `existing/module.py` | Example pre-existing file restored via `git checkout` |
| `<PKG>` | `solver` | Example package name |
| `<UUID>` | `123e4567-e89b-12d3-a456-426614174000` | Fresh canary GUID |
| `<YOUR NAME>` | `Jane Doe` | Placeholder for human name (skeleton de-identification) |
| `<your-unixname>` | `jdoe` | Placeholder for unix name |

If you add a new placeholder elsewhere, add it here.

