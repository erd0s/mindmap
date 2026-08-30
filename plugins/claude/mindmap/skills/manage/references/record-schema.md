# Record schema

`mindmap record` accepts a JSON object with a required non-empty `summary` and a required `operations` array. The only other allowed top-level field is `concept_model`; unknown or misspelled fields are rejected rather than treated as a no-change checkpoint.

When runtime context reports a legacy-map reconciliation, the payload must also include `"concept_model":"causal-tree-v2"` after the old map has been compressed. That marker upgrades the project only if the resulting graph passes every causal-tree bound.

An `upsert` operation requires `id` and `title` for a new item. It may include `summary`, `resume`, `state`, `kind`, `parent_id`, and `sort_order`. Omitted fields retain their existing values when updating.

A user-deleted id is tombstoned so retained transcript evidence cannot silently recreate it. Restore it only when the user explicitly asks: send a new-item `upsert` with `"restore":true`. The id must appear under `USER-DELETED BRANCHES`; `restore` is rejected on other ids and operation types.

`summary` explains the concept and why it exists. `resume` records the concrete point from which unfinished thinking should continue; use an empty string when there is no useful resume point.

A `settle` operation requires an existing `id`. It may include a final `summary` or revised `title`.

Updating or settling an existing item requires `expected_revision` from the latest durable context. New items omit it. A stale revision fails the whole transaction so concurrent tabs cannot silently overwrite one another.

A `remove` operation requires an existing `id` and `expected_revision`. Use it only for duplicates or wrongly granular legacy nodes. When the item has children, `reparent_to` is required and may be another existing id or `null` for genuinely independent roots.

Allowed states: `planned`, `open`, `settled`.

Allowed kinds: `goal`, `thread`, `decision`, `task`, `question`, `note`.

The whole payload is applied in one immediate SQLite transaction. Parent relationships are deferred until commit so a child may appear before its new parent in the same batch. Invalid operations roll back the full batch.

The payload is a compressed conceptual tree, not a transcript. Do not create one item per message, turn, tool call, file, or chronological event.

One checkpoint may add at most 20 concepts. The durable graph has no lifetime node-count ceiling: a complex project may retain as many distinct concepts as its history requires. It remains limited to 4 roots and 10 levels of depth, and numbered message/turn/prompt/response/tool-call/event ids and titles are rejected. These structural rules preserve causal resolution without forcing unrelated ideas together.

Titles are limited to 160 characters, concept summaries to 1,200, resume points to 600, and checkpoint summaries to 500. These are ceilings, not targets: write the shortest cold-readable text that preserves the idea.
