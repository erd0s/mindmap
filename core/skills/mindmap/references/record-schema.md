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

The durable graph has no lifetime node-count ceiling. The validator-derived [record-limits.md](record-limits.md) gives every numeric bound, including IDs and canonical UTF-8 payload bytes. These are ceilings, not targets. Numbered message/turn/prompt/response/tool-call/event IDs and titles remain rejected. Each normalized ID may appear at most once in a payload.

The injected `prepare --file -` accepts this same JSON and returns an immutable `commit_command`. Run that command alone as the final foreground Bash/exec_command tool. Retry that exact command on transport failure; intervening ordinary activity requires preparing again. Preparation retains JSON privately in the database until the request is committed or abandoned. It does not change the map.

After further work, use `prepare --supersedes TOKEN` with an incremental correction against current revisions. The token names the checkpoint being replaced; it is not inferred from tool counts. Empty corrections may reuse the same summary and still produce distinct checkpoint history. A competing correction, new prompt, stale item revision or invalid operation rejects the entire attempt. The direct `record` interface also accepts `--supersedes TOKEN`; its identical-payload compatibility replay never refreshes observed tool coverage.

Use the bound `read` command for complete fields and revisions. `--roots`, `--parent ID`, `--id ID` and `--notices` select discovery, children, a concept, or warnings/deletions. Follow `next_cursor` using the same selector and `--cursor VALUE`; a changed map requires refreshing. Full `snapshot` export remains available for deliberate inspection.
