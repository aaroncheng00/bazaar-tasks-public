# SETUP — Onboarding Checklist (~20 min)

Complete these steps in order. Every item is a checkbox with an exact command or edit.
When done, `pipeline/checks/run_all.sh` passes and you have your first card.

> **Joining the Bazaar pod? Skip §1 — it is already done.** Start at §2.
> §1 only applies if you are standing up a *new* lab from the template.

---

## 1. Lab config — already done for Bazaar

`PROJECT.md` is filled at the pod level: lab identity, product repo, task repo, domain
notes. **A joining author does not edit it.**

- [ ] Read [`PROJECT.md`](PROJECT.md) once, for the domain notes — where Bazaar bugs
      actually hide. That is the part worth two minutes.
- [ ] Confirm it is complete:
  ```bash
  grep -oE "<[A-Z][A-Z0-9_]+>" PROJECT.md || echo "PROJECT.md has no placeholders left — good"
  ```

Per-task values (`<TASK_DIR>`, `<TASK_SLUG>`, `<AUTHOR>`, base commit) are **not** in
`PROJECT.md` — they live on your card and you supply them when you run a prompt. See the
Placeholder Reference at the bottom for which is which.

*Standing up a new lab?* Then `PROJECT.md` is your one required edit: replace every
placeholder using the same reference table.

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
  - Pipeline placeholders: `<ANGLE_BRACKET_CAPS>` like `<PROJECT_REPO>`, `<TASK_SLUG>` — listed in the table below. **Lab-level** ones are already resolved in `PROJECT.md`; **per-task** ones you substitute yourself each time you run a prompt, using the values on your card.
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
  Expected: `4 checks passed, 0 failed` and exit `0`. If any check fails, fix the file it names.

  These verify plumbing only — card schema, audit tags, `before_repo_set_cmd`, solution
  paths. **A green run says nothing about whether your task is any good.**

---

## 5. Run the first ideation prompt

- [ ] **Read the board first** — `ls pipeline/cards/`. It is the only dedupe mechanism;
      do not propose against a commit someone already claimed.
- [ ] Open [`prompts/README.md`](prompts/README.md) for the placeholder convention.
- [ ] Run the first prompt from the task repo root, pointed at **your own** commits:
  ```bash
  cat prompts/05-ideate-commits-and-prs.md
  # copy the prompt body into a 1P model. You card your own commits by default —
  # you know why the obvious approach was wrong, and that is the trap.
  ```
- [ ] Save the output as your first card, named `bazaar-<slug>-<author>.md`:
  ```bash
  cp pipeline/cards/_TEMPLATE.md pipeline/cards/bazaar-<slug>-<author>.md
  # front matter: status=proposed, slug, author (your handle), base_commit, task_dir,
  # novelty_risk, difficulty_hypothesis — state the last two BEFORE you build anything.
  ```

---

## 6. What "done" looks like

- `pipeline/checks/run_all.sh` exits `0` (4 passed).
- `codimango --help` works.
- One real card exists in `pipeline/cards/` named `bazaar-<slug>-<author>.md` with
  `status: proposed`, and its `difficulty_hypothesis` is filled in.
- You can run `codimango bench validate --structural-only -p ./<TASK_DIR>` on a skeleton
  copy and it is structural-green.

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

**Two scopes.** *Lab-level* placeholders are resolved once in `PROJECT.md` and are already
done for Bazaar. *Per-task* placeholders change with every task and every author — they
live on your card, and you substitute them by hand when you run a prompt. Do not put
per-task values in `PROJECT.md`; five authors cannot share one "current task".

Skeleton placeholders (`@@FILL:...@@`, `<INPUT>`, `<WANT>`, etc.) use a separate convention inside `single_turn_template/` and `multi_turn_template/` — see §3 above. They are not listed here.

| Placeholder | Scope | Example value | Notes |
|---|---|---|---|
| `<LAB_NAME>` | lab | `Bazaar` | Your lab handle |
| `<TRACK>` | lab | `swe-bench` | This track; also `t-bench` or `ml-bench` in sibling templates |
| `<OWNER>` | lab | `alice@example.com` | Contact for this adoption |
| `<PROJECT_REPO>` | lab | `github.com/codimango/example-service` | System under test |
| `<PROJECT_REPO_NAME>` | lab | `example-service` | Repo name without org (de-identified) |
| `<EXAMPLE_TASK>` | lab | `example-task` | Example task slug (de-identified) |
| `<PROJECT>` | lab | `example-project` | Generic project prefix |
| `<TASK_REPO>` | lab | `github.com/codimango/example-bench-tasks` | Where tasks live |
| `<SKELETON_REPO>` | lab | `github.com/codimango/swe-bench-pro-template` | Upstream skeleton reference (skeletons now ship in-repo) |
| `<PROJECT_PATH>` | local | `./example-service` | Your product-repo checkout |
| `<TASK_PATH>` | local | `./example-bench-tasks` | Your task-repo checkout |
| `<GH_TOKEN_FILE>` | local | `~/.bazaar_gh_token` | Gitignored token file for Docker builds; per-person path |
| `<BASE_COMMIT>` | **task** | `abc1234def5678` | Commit where the feature is absent — from your card's `base_commit` |
| `<TASK_SLUG>` | **task** | `example-schema-migration-chain` | Your card's `slug` |
| `<TASK_DIR>` | **task** | `./example-task-slug` | Your card's `task_dir` |
| `<AUTHOR>` | **task** | `alice` | Your handle — the card filename suffix |
| `<ROSTER_PATH>` | lab | `README.md` | Task roster location |
| `<NET_NEW_TEST_PATHS>` | `tests/new_suite.py` | Example net-new test file cleared by `before_repo_set_cmd` |
| `<EXISTING_PATH>` | `existing/module.py` | Example pre-existing file restored via `git checkout` |
| `<PKG>` | `solver` | Example package name |
| `<UUID>` | `123e4567-e89b-12d3-a456-426614174000` | Fresh canary GUID |
| `<YOUR NAME>` | `Jane Doe` | Placeholder for human name (skeleton de-identification) |
| `<your-unixname>` | `jdoe` | Placeholder for unix name |

If you add a new placeholder elsewhere, add it here.

