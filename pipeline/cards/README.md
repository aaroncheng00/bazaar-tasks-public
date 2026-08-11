# Cards — Idea Board

This directory is the file-based handoff board for task authoring. Cards move
through a single lifecycle; the `status` field is the source of truth.

## Lifecycle

```
draft -> proposed -> claimed -> oracle-passed -> submitted
                         \-> rejected
                         \-> deprecated/ (moved file)
```

- `draft` — private scratch, not yet gated. You may keep it locally.
- `proposed` — gated idea, no scaffold yet. The brainstormer writes this.
- `claimed` — actively building. Set `claimed_by` and a timestamp so two workers do not collide.
- `oracle-passed` — local proof complete (base red, oracle green, no-op 0, proof stable). Hand to human for final `instruction.md`, calibration, and submission.
- `submitted` — human has submitted; keep the card as record.
- `rejected` — failed a gate. Must state the concrete reason in Rejection Notes.
- `deprecated/` — ideas tried and found to be dead ends. Move the file there; do not delete.

Ship no real cards. The only card in a fresh clone is `_TEMPLATE.md`.

## Naming

Cards are named `<project>-<slug>-<author>.md` — e.g. `example-schema-migration-chain-alice.md`.

- `<project>` is the short repo prefix or lab handle (keeps the board readable).
- `<slug>` is the short task slug (`<TASK_SLUG>` in `PROJECT.md`).
- `<author>` is the author handle (`<AUTHOR>` in `PROJECT.md`). The author suffix prevents
  collisions when two people sketch the same idea.

Example is illustrative (`example-schema-migration-chain`). Do not use a real project name.

## Who owns a harvested task

Three people can touch one card, so three fields keep them apart:

- `author` — owns the task through submission. **Gets the credit.** This is the filename suffix.
- `source_author` — wrote the commit in `base_commit`, when you harvested someone else's work.
  Attribution, and who to ask when the trap is unclear. Leave blank if it is your own commit.
- `claimed_by` — ran the scaffolder. Collision avoidance only.

Default: you card your own commits — the person who wrote the fix knows why the obvious approach
was wrong, and that is the trap. Harvesting a teammate's commit is fine; tag them for a one-line
sanity check before the card moves to `proposed`.

The pod lead owns the board, not the cards: a weekly sweep for coverage gaps, unmined seams,
duplicate shapes, and rebalancing. Authoring stays distributed.

## Claim-before-you-build

Set `status: claimed`, `claimed_by: <AUTHOR>`, and a timestamp **before** you scaffold.
If a card is already `claimed` or `oracle-passed`, do not edit it unless a human asks.

## What lives here

- `_TEMPLATE.md` — the card schema. Copy it for each new idea.
- `README.md` — this file.

