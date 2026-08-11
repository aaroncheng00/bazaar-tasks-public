# Changelog

All notable changes to the core pipeline are documented here. This file follows
Keep a Changelog and uses Semantic Versioning.

## [1.2.0] — 2026-08-10

- Moved agent definitions from `.claude/agents/` to `agents/` — the path is model-neutral, and a
  vendor-specific directory name reads as third-party authorship to a provenance or legal reviewer.
- Skeleton `task.toml` now ships the audit-trail tags (`synthetic`, pipeline name, model ids,
  `human-reviewed`), so every adopting lab is attributable by default.
- New `pipeline/checks/check_audit_tags.py`, wired into `run_all.sh`.
- `CORE_STANDARDS.md`: added the ADO north stars (realistic / diverse / genuinely hard) and the
  audit-trail + deployment rules. Bumped to `1.2.0`.

## [1.1.0] — 2026-08-10

- Vendored task skeletons: `single_turn_template/` and `multi_turn_template/` from the per-track source repo for this track. The single-turn skeleton tracks the org's published template; the multi-turn cascade has no upstream and is maintained here. See `SETUP.md` § Skeletons for sync status and diff commands.
- De-identified skeletons (longest-match substitutions, protected the word regression to avoid breaking it) and fixed `pipeline/checks/check_solution_paths.py` to skip comments/heredocs and report line numbers.
- Updated docs: `SETUP.md` §3 now shows in-repo skeletons, `GOLD_STANDARD.md` Task Layout now references `single_turn_template/`/`multi_turn_template/`, `PROJECT.md` notes skeletons ship in-repo, `README.md` lists skeletons, `prompts/07-scaffold-and-prove.md` now copies from this repo.
- `CORE_STANDARDS.md` bumped to `1.1.0`.

## [1.0.0] — 2026-08-10

- Initial release: `CORE_STANDARDS.md` (core-version 1.0.0), per-track `GOLD_STANDARD.md`,
  `PROJECT.md` template, `SETUP.md` checklist, `README.md` doorway, prompts 01–09,
  `pipeline/cards/` board with schema and lifecycle, `pipeline/checks/` guards
  (`check_before_repo_set_cmd.py`, `check_solution_paths.py`, `check_card_schema.py`,
  `run_all.sh`), and `agents/` definitions.
- Establishes the three-tier split: CORE (byte-identical), TRACK (per-bench delta),
  PROJECT (per-lab config).

