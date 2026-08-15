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
- `turns` binds one agent interaction to one checkpoint and payload digest.
- `items` materializes the current causal tree.
- `events` retains append-only provenance, including explicit subtree deletion.
- `messages` retains normalized transcript evidence for reconstruction.

Agent writes use WAL mode, a busy timeout, immediate transactions, deferred parent validation, transcript identity anchors, optimistic item revisions, and payload-verified interaction idempotency. A map mutation and its interaction checkpoint commit together.

The display route is a stable, lowercased, percent-encoded form of the path beneath the user's home directory. It is an identity and command-line selector, not a URL. Case-folded collisions are rejected rather than merged.

## Lifecycle

1. An inactive global hook exits without model-visible output unless it sees an exact Mindmap invocation or finds the current directory in the small active-project registry.
2. `start` activates the project, attaches the current session, and imports available history.
3. The host adapter supplies project, host, session, and interaction identity.
4. The skill compresses the session into goals, branches, questions, decisions, plans, and resume points.
5. Deterministic code validates and atomically records the update.
6. The Stop hook requests one recovery pass when the current interaction has no checkpoint, then fails open so Mindmap cannot trap the host session.
7. Future local sessions read the same project map regardless of which supported host wrote it.

Transcript parsing is an adapter rather than a storage contract. Unknown JSONL records are ignored. Claude Stop input supplies the final assistant message because its transcript can lag the hook event.

## Viewer consistency

Each viewer reads a project and its items in one SQLite read transaction. A persistent connection polls `PRAGMA data_version`: every 200 ms in the terminal and every 250 ms in the desktop process. An external commit triggers a fresh snapshot while preserving the selected concept when possible.

The desktop process owns one watcher and emits a lightweight change event to all open windows. The coding-session picker and each graph live in separate native windows. From a graph, <kbd>⌘</kbd><kbd>O</kbd> or <kbd>⌘</kbd><kbd>N</kbd> opens another picker; the shortcuts do nothing inside a picker so they cannot multiply open dialogs. <kbd>Esc</kbd> closes only the active picker.

Subtree deletion is a deliberate user edit. Each viewer sends the exact identifier/revision set shown by its confirmation dialog. One recursive transaction rejects a changed branch, records each deleted identifier and title, removes the selected item and all descendants, and updates the project timestamp. Messages and prior events remain intact. Lifecycle context replays these events as durable tombstones, so older transcript evidence cannot recreate a deleted branch. Only an explicit `restore: true` upsert clears a tombstone; legacy later `item.created` events remain compatible.

## Why SQLite stays local

The store coordinates concurrent hook processes and preserves atomicity across map updates, checkpoints, retries, and transcript cursors. Syncing an active SQLite database with a file synchronizer would duplicate or race the database, its WAL, and its shared-memory file. Version 0.3 therefore promises one machine-local source of truth, not multi-writer replication.

## Release boundary in version 0.3

- Signed and notarized universal macOS desktop app; Windows and Linux desktop packages are deferred.
- Cross-platform terminal binaries for Darwin, FreeBSD, Linux, OpenBSD, and Windows.
- Agent integrations on macOS and Linux with Python 3.10+.
- Windows terminal viewing only; Windows agent hooks are deferred.
- Local coding-agent sessions only; remote/cloud sessions cannot share the local database.
- Wails v3 beta 8 is pinned behind the small desktop service boundary until Wails v3 stabilizes.
