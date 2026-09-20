# Architecture

## Product boundary

Mindmap has three local surfaces:

```text
Codex plugin ─┐
              ├─ bundled Python hook runtime ─┐
Claude plugin ┘                               │
                                              ▼
                                       XDG SQLite store
                                        ▲           ▲
                                        │           │
                           Go terminal/CLI     Wails desktop
                                                │
                                          React Flow UI
```

The plugins reconstruct and record causal maps. The Go command manages projects and renders the terminal UI. The Wails app renders native macOS windows around bundled frontend assets. No component requires an HTTP server, and no component exposes the database over a network.

The Python hook runtime remains bundled in each agent plugin for version 0.3. It has no third-party dependencies. The Go and Python stores share a deliberately small SQLite schema boundary and have independently tested migrations.

## The durable unit is a project

A project is identified by its resolved root path. Activation normally discovers the nearest Git root; a non-Git directory uses the supplied directory. Registry lookup chooses the deepest matching ancestor, so sessions started in subdirectories attach to the same map.

Activation belongs to the project, not one agent session. A later local Codex or Claude session beneath an active root receives the compact map. Stopping changes the project's `active` flag but retains its concepts and evidence.

The lifecycle hook's session working directory is authoritative. A command-specific `cd` or tool workdir cannot retarget a session. When activation validation fails, the hook leaves the session unattached and directs the user to start a new agent session under the intended root.

## Storage model

SQLite owns the canonical state:

- `projects` stores root identity, display route, and activation.
- `sessions` tracks host identity and transcript cursors.
- `turns` binds one agent interaction to its current checkpoint, payload digest, observed tool generation, and unresolved final output.
- `context_bindings` maps short private command files to exact project/turn identity.
- `record_requests` retains immutable prepared JSON, prompt version, correction token, and correlated commit coverage.
- `turn_prompts` preserves every distinct prompt when a host reuses an interaction identifier for a steer.
- `items` materializes the current causal tree.
- `events` retains append-only provenance, including explicit subtree deletion.
- `messages` retains normalized transcript evidence for reconstruction.

Agent writes use WAL mode, a busy timeout, immediate transactions, deferred parent validation, transcript identity anchors, optimistic item revisions, and payload-verified interaction idempotency and immutable request receipts. A map mutation and its interaction checkpoint commit together. A distinct later prompt under the same interaction identifier invalidates that checkpoint while preserving its mutations, so the agent can record an incremental correction from current revisions.

`PreToolUse` advances a turn's tool generation before each observed tool. The ordinary `record` interface saves that generation and returns a unique checkpoint token. A deliberate correction names that token with `--supersedes`; mutations, exact revision checks, replacement coverage, and provenance commit in one transaction. Ordinary divergent repeats remain rejected. Identical direct payload replays never acknowledge later work.

The injected protocol uses two commands. `prepare --file -` accepts non-interactive JSON and retains an immutable request at the observed generation. Its returned `commit_command` is run alone as the final foreground Bash/exec_command call. The fast hook recognizes only that exact registered command. It advances the request's safe generation only when every intervening event belongs to the same command. Thus retries include their own tool events without covering unrelated activity or duplicating mutations. Unknown wrappers, background calls, bundled commands, and failed ordinary tools break that chain. A new prompt also expires prepared requests for the earlier prompt version.

Stop checks freshness and invalidates stale checkpoints within one write transaction, serialized with record commits and retry coverage refreshes. It gives one bounded recovery pass, then fails open. Tools after a recovery checkpoint still invalidate it for honest unresolved diagnostics. Zero observed coverage retains the 60-second legacy fallback. Hosted activity, asynchronous completion after preparation, and commitments appearing only in final prose remain observation gaps: finish and join work before preparing.

Short command files use this runtime's interpreter and library path, bind the database explicitly, and resolve identities from SQLite. They live in a private data-directory subdirectory, with a private `/tmp/mindmap-UID` fallback for long paths. No path, identity, executable instruction, revision, or warning is sliced to meet a delivery budget. Commands and prepared requests survive process restarts; replacing runtime installations still requires stopping host processes first. See [the protocol and compatibility contract](checkpoint-protocol.md).

Automatic prompt output is capped at 8,192 UTF-8 bytes including its serialized JSON envelope; SessionStart at 4,096 and Stop recovery at 2,048. The essential decoded checkpoint contract fits within the first 1,800 bytes. JSON is serialized without ASCII-escaping Unicode. Numeric guidance comes from the validator's shared definitions in `limits.py`.

Prompt context selects deterministic whole concept records using explicit IDs, request words, the current session's recent contributions, unfinished state, recency and stable ID ties. It reserves root discovery, includes relevant settled concepts and parent IDs, and labels omissions. A relevant deep leaf is considered before its large ancestor records; fields that do not fit are explicitly omitted, never silently clipped. Unfinished leaves carry an inline frontier label without repeating their resume text. The first contract retains the incremental rule: update only what the current turn changes. The reviewed causal, parent-transition and handoff guidance has reserved space after the selected map. Historical plans are evidence to reconcile against the current request, not authorization to resume them.

The bound `read` command returns pages of complete fields and revisions, roots, children, a selected ID, or warnings and deletions. Each page is capped at 16,384 serialized UTF-8 bytes and supplies an explicit continuation cursor. A content fingerprint rejects continuation after the graph or notices change. A deliberate complete `snapshot` export remains available. Context preparation reads the graph and selected provenance aggregates in a consistent transaction without loading transcript/session history or constructing the full rendered map. Storage remains complete; selection never edits concepts. PreCompact and PostCompact import evidence silently.

The fast activity path still avoids importing the store/lifecycle runtime or scanning schema. It now makes the generation update plus an indexed request-correlation update inside the same transaction. Earlier timing figures apply to the old single-update path; current qualification measurements are reported separately.

The display route is a stable, lowercased, percent-encoded form of the path beneath the user's home directory. It is an identity and command-line selector, not a URL. Case-folded collisions are rejected rather than merged.

## Lifecycle

1. An inactive global hook exits without model-visible output unless it sees an exact Mindmap invocation or finds the current directory in the small active-project registry. Beneath an active root it also exits silently for a nonpersistent Codex session (`transcript_path` null) or a process whose launcher set `MINDMAP_TRACKING=off`, unless the prompt is an explicit Mindmap action or the session is already attached. See [the execution-mode boundary](compatibility.md#execution-mode-boundary).
2. `start` activates the project, attaches the current session, and imports available history.
3. The host adapter supplies project, host, session, and interaction identity.
4. The skill compresses the session into goals, branches, questions, decisions, plans, and resume points.
5. A lightweight `PreToolUse` hook counts tools and correlates exact prepared commit commands.
6. The agent prepares non-interactive JSON and executes its returned commit command as the final tool; validation and map/checkpoint mutation are atomic.
7. The Stop hook requests one recovery pass when the current interaction has no checkpoint or has later observed tool activity, then fails open so Mindmap cannot trap the host session.
8. If an unattended record attempt still fails, the next prompt reports prior unresolved work and tells the agent to reconcile it in the current checkpoint.
9. Future local sessions read the same project map regardless of which supported host wrote it.

Transcript parsing is an adapter rather than a storage contract. Unknown JSONL records are ignored. Claude Stop input supplies the final assistant message because its transcript can lag the hook event.

Context and snapshots carry warning-only consistency checks: a settled concept with an action-like resume, an unsettled summary that claims completion, an unsettled root that calls itself superseded, a reopen that adds no summary or resume, and a planned parent whose open or settled child was recorded after the parent's last revision. The agent reconciles them from conversation evidence. Deterministic code never changes a causal parent's state.

## Viewer consistency

Each viewer reads a project and its items in one SQLite read transaction. A persistent connection polls `PRAGMA data_version`: every 200 ms in the terminal and every 250 ms in the desktop process. An external commit triggers a fresh snapshot while preserving the selected concept when possible.

The desktop process owns one watcher and emits a lightweight change event to all open windows. The coding-session picker and each graph live in separate native windows. From a graph, <kbd>⌘</kbd><kbd>O</kbd> or <kbd>⌘</kbd><kbd>N</kbd> opens another picker; the shortcuts do nothing inside a picker so they cannot multiply open dialogs. <kbd>Esc</kbd> closes only the active picker.

Subtree deletion is a deliberate user edit. Each viewer sends the exact identifier/revision set shown by its confirmation dialog. One recursive transaction rejects a changed branch, records each deleted identifier and title, removes the selected item and all descendants, and updates the project timestamp. Messages and prior events remain intact. Bounded context discloses tombstone counts and retrieval; recording still replays these events as durable tombstones, so older transcript evidence cannot recreate a deleted branch. Only an explicit `restore: true` upsert clears a tombstone; legacy later `item.created` events remain compatible.

## Why SQLite stays local

The store coordinates concurrent hook processes and preserves atomicity across map updates, checkpoints, retries, and transcript cursors. Syncing an active SQLite database with a file synchronizer would duplicate or race the database, its WAL, and its shared-memory file. Version 0.3 therefore promises one machine-local source of truth, not multi-writer replication.

## Release boundary in version 0.3

- Signed and notarized universal macOS desktop app; Windows and Linux desktop packages are deferred.
- Cross-platform terminal binaries for Darwin, FreeBSD, Linux, OpenBSD, and Windows.
- Agent integrations on macOS and Linux with Python 3.10+.
- Windows terminal viewing only; Windows agent hooks are deferred.
- Local coding-agent sessions only; remote/cloud sessions cannot share the local database.
- Wails v3 beta 8 is pinned behind the small desktop service boundary until Wails v3 stabilizes.
