# PROJECT — Lab Configuration

> Fill this file in when you adopt the template. It is the **only file you must edit**
> to get started. Every other file is either shared infrastructure (`CORE_STANDARDS.md`)
> or track guidance (`GOLD_STANDARD.md`). Keep this file small — its smallness is the product.

This file holds the per-lab config surface. Replace every placeholder below with your lab's values.
Comments show worked examples. After you finish, no placeholder should remain in any command you run.

---

## Lab identity

- **Lab name:** `<LAB_NAME>` <!-- e.g. example-lab -->
- **Track:** `<TRACK>` <!-- e.g. swe-bench -->
- **Owner / contact:** `<OWNER>` <!-- e.g. alice@example.com -->

## Repos and paths

- **Product repo (the system under test):** `<PROJECT_REPO>` <!-- e.g. github.com/codimango/example-service -->
- **Task repo (where tasks live):** `<TASK_REPO>` <!-- e.g. github.com/codimango/example-bench-tasks -->
- **Task skeletons:** shipped in-repo as `single_turn_template/` and `multi_turn_template/` — see `SETUP.md` §3. Upstream single-turn reference: `<SKELETON_REPO>` <!-- e.g. github.com/codimango/swe-bench-pro-template -->
- **Local checkout path for product repo:** `<PROJECT_PATH>` <!-- e.g. ./example-service -->
- **Local checkout path for task repo:** `<TASK_PATH>` <!-- e.g. ./example-bench-tasks -->

## Task authoring knobs

- **Base commit for new tasks:** `<BASE_COMMIT>` <!-- e.g. abc1234def5678 -->
- **Task directory name for next idea:** `<TASK_SLUG>` <!-- e.g. example-schema-migration-chain -->
- **Author handle for cards:** `<AUTHOR>` <!-- e.g. alice -->
- **Token file for credless builds (gitignored):** `<GH_TOKEN_FILE>` <!-- e.g. ~/.example_gh_token -->

## Docs and roster

- **Setup doc this lab follows:** `SETUP.md` (and `PROJECT.md` — this file)
- **Task roster location:** `<ROSTER_PATH>` <!-- e.g. README.md task table in task repo -->
- **Cards board:** `pipeline/cards/` — see `pipeline/cards/README.md`

## Domain notes

Use this free-text section to frame what your product does and where its bugs live.
A lab on a game engine and a lab on a ranking service need different framing and this
is where that lives. Keep it to a short paragraph so the next teammate can orient in 2 minutes.

> _Example:_ This product is a distributed job scheduler. Bugs hide in
> retry/backoff, lease fencing, and state compaction — not in pure parsing.
> The under-tested surface is the multi-step coordination path.

Write your lab's notes below (replace this paragraph):

Your domain notes here — e.g. what the product does, which modules are under-tested,
where bugs tend to hide.

