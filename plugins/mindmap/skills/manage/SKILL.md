---
name: manage
description: Explicitly start, sync, inspect, or stop a durable visual map that compresses project conversations into a small causal tree across Codex and Claude Code sessions. Use only when the user directly invokes this skill with start, sync, status, or stop; once started, lifecycle hooks keep the active project map current until stopped.
---

# Mindmap

Mindmap compresses a project conversation into a small causal tree. Each node is a meaningful thought, goal, question, decision, or explicitly discussed task. The parent relationship explains which thought caused the branch. The result must let someone recover the shape of the work in about ten seconds.

This is not a transcript viewer, chronological activity feed, meeting summary, or ordinary task board. The transcript is source evidence only. Never create nodes for individual messages, turns, tool calls, files touched, timestamps, or routine implementation steps unless one is itself a concept the user needs to remember.

Never activate it implicitly. The user must invoke this skill with exactly one action: `start`, `sync`, `status`, or `stop`.

## Use the injected runtime context

Look first for `MINDMAP_ACTIVE_V1` in the current context. Lifecycle hooks put the exact project root, session id, interaction id, transcript command, and atomic record command there. Use those commands exactly; they avoid ambiguity when several tabs are working in the same directory.

If no runtime context was injected, find `mindmap` on `PATH`. In a packaged plugin the fallback executable is also available at `../../bin/mindmap` relative to this skill directory. A fallback command is valid only in the agent session's existing working directory: never use `cd`, change a tool call's workdir, or substitute a guessed parent or child project directory. For `start`, run `mindmap start --root "$PWD"`. If it succeeds, report activation once and explain that transcript backfill begins on the next hook event. If it fails, or injected context contains `MINDMAP_ACTIVATION_BLOCKED_V1`, do not retry from another directory and do not claim activation, tracking, checkpointing, or future backfill; explain that the user must start a new agent session inside the intended project directory and invoke `start` there. For `status`, run `mindmap snapshot --root "$PWD"` and give a read-only playback of its project and items. For `stop`, run `mindmap stop --root "$PWD"`. A fallback `sync` requires a later hooked turn, so ask the user to invoke sync again after the plugin hooks are loaded.

## Actions

### start

1. Confirm that the hook activated the project. If it did not, use the same-directory fallback above only when activation was not explicitly blocked.
2. Run the injected transcript command and read its output. This is the mid-session backfill. Do not run `mindmap status` as a substitute.
3. Compress the whole relevant conversation, not just the last exchange, into one root seed and the smallest useful set of causal branches.
4. Use the injected record command to apply the map and checkpoint this interaction.
5. Tell the user which project root is active and that tracking will persist across future Codex and Claude sessions until `stop`. Explain that activation covers the whole project directory, so unrelated parallel sessions there would also contribute.

If the project was already active, treat `start` as `sync`.

### sync

1. Run the injected transcript command, then read the current durable context. Do not substitute `mindmap status` for the transcript command.
2. Reconcile missing, stale, duplicated, or overly granular concepts. Use `remove` to merge nodes that are merely transcript/task-board debris, while preserving meaningful settled concepts. Never recreate an id listed under `USER-DELETED BRANCHES` from older transcript evidence.
3. Record the changes and checkpoint the interaction.
4. Briefly explain what changed in the map.

### status

1. Read the injected durable context or run `mindmap snapshot --root "$PWD"`.
2. Play it back simply as a causal tree: root intent, explored branches, open frontier, explicit future branches, settled conclusions, and the best resume point.
3. Use the injected record command with an empty `operations` array and a truthful no-change summary unless the status review itself exposed stale state.

### stop

1. Perform one final sync so the last train of thought is not lost.
2. Use the injected record command to checkpoint it.
3. Confirm in the final user-facing response that tracking is stopping and the existing map remains browsable.
4. Do not run `mindmap stop` when runtime context is present. The Stop hook must capture the final response before it deactivates the project. Use the direct command only for the no-hook fallback described above.

## Compress into a causal tree

Start from the user's seed thought or governing goal. Add a child only when the conversation materially branched, narrowed, answered, rejected, or explicitly deferred something. A coding task may be a node when it represents a meaningful intended outcome; routine edits and command execution are not nodes.

Keep the map aggressively small:

- Prefer roughly 5–20 nodes for an initial backfill of an ordinary session, using fewer whenever possible.
- A normal new turn should usually change zero to three nodes.
- Merge repetition and implementation chatter into the concept it advances.
- Preserve causal shape, not chronology. Parent means “grew out of”, never merely “happened before”.
- Across sessions, use the matching frontier and its resume point as the continuation anchor. Update that frontier when the thought is unchanged; parent a genuinely new concept beneath it when the work branches. Never default a new session's concepts to the root.
- Keep one root when the conversation has one governing intent. Use multiple roots only for genuinely independent trains of thought.
- Remove duplicates, message-like nodes, and obsolete task-board debris when reconciling an older map. Never remove a meaningful settled concept merely to make the current frontier look tidy.
- “Small” describes the resolution of each concept, not a fixed lifetime node count. Preserve distinct project complexity instead of merging meaningful branches merely because the project has accumulated many concepts.

Prefer stable, human-readable lowercase ids such as `release-pipeline` over turn-specific ids.

Each item has:

- `state`: `planned` for an explicit future intention not started, `open` for active work or unresolved thought, `settled` for completed work or a decision no longer in question.
- `kind`: `goal`, `thread`, `decision`, `task`, `question`, or `note`.
- `parent_id`: the larger goal or train of thought that explains why the item exists. Use `null` for a root.
- `summary`: enough context to understand what the concept means and why it exists, without replaying the conversation.
- `resume`: the concrete unresolved question or next point from which thinking should continue. Leave it empty when nothing useful remains to resume.
- `revision`: supplied by the durable context. Every update, settle, or remove of an existing concept must send it as `expected_revision`; never guess it. A new concept omits it. On a concurrent-change error, re-read context and reconcile before retrying.
- `restore`: use `true` only on an `upsert` when the user explicitly asks to restore an id listed under `USER-DELETED BRANCHES`. Omit it otherwise.

Capture plans the user or agent explicitly stated even when nobody has begun them. Do not invent likely next steps that were never discussed. Preserve disagreements and uncertainty as open questions. When a decision changes, update the existing item and explain the new result rather than creating a misleading duplicate.

## Checkpoint every active turn

After all substantive work and immediately before the final response of every active turn, use the exact injected record command. Do not checkpoint while implementation, commands, tests, research, or requested changes remain; make it the final substantive tool action. It accepts one JSON object on stdin:

```json
{
  "concept_model": "causal-tree-v2",
  "summary": "Added the shared state design and settled the URL convention.",
  "operations": [
    {
      "op": "upsert",
      "id": "shared-state",
      "title": "Share state between Codex and Claude",
      "summary": "Use one XDG SQLite store with session provenance and atomic writes.",
      "resume": "Verify both hosts converge when they update adjacent branches.",
      "state": "settled",
      "kind": "decision",
      "parent_id": "cross-agent-skill",
      "expected_revision": 2
    }
  ]
}
```

Include `concept_model` when the injected context says `LEGACY_MAP_RECONCILIATION_REQUIRED_V2`, after you have read both transcript and snapshot and reconciled the old map. Omit it on ordinary later checkpoints.

Use `op: "settle"` with an existing `id` to close an item. If the turn genuinely changes nothing, record `{"summary":"No map change; answered a status question.","operations":[]}`. The record operation is transactional and idempotent for a host/session/interaction, so never bypass it with direct database edits.

Use `op: "remove"`, an existing `id`, and its `expected_revision` only to eliminate a duplicate or wrongly granular node. If it has children, also supply `reparent_to` with another concept id, or `null` only when those children are genuinely independent roots.

An explicit viewer deletion is stronger than missing map state: retained transcripts remain evidence, but must not resurrect that branch. If the user explicitly asks to restore one of the injected `USER-DELETED BRANCHES`, recreate it with `op: "upsert"` and `restore: true`. Never infer restoration from old transcript text alone.

When a host adds another user prompt under the same interaction id, lifecycle context reports `MINDMAP_CHECKPOINT_REOPENED_V1`. The earlier map mutations remain; review their current revisions and record only additional or corrective changes rather than replaying a stale replacement payload.

The Stop hook allows one recovery pass when a checkpoint was missed, then fails open to prevent a loop.
