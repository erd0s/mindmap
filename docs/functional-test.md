# Functional test runbook

Run this after the automated validation, security scan, and adversarial review are green. Record the agent versions, host operating system, test database path, and result of each scenario.

## 1. Isolate the test

```sh
test_root="$(mktemp -d)"
export MINDMAP_DATA_DIR="$test_root/data"
export MINDMAP_HOME_DIR="$test_root/home"
mkdir -p "$MINDMAP_HOME_DIR/example/.git"
npm ci --prefix desktop/frontend
make validate
make mindmap
```

Run `build/mindmap doctor`. A missing real agent or desktop app may warn; the database and terminal checks must not fail.

The exported variables isolate processes launched from this shell. Finder and LaunchServices apps do not reliably inherit them. Run the Finder-launched parts of sections 6 and 7 in a disposable macOS user account, recreate the test project there without these overrides, and use only that account's default Mindmap database. Do not run those scenarios against a daily account or a database containing real transcripts; remove the disposable account after retaining the release evidence.

## 2. Terminal basics

Create a project map:

```sh
build/mindmap start --root "$MINDMAP_HOME_DIR/example"
build/mindmap projects
build/mindmap status --root "$MINDMAP_HOME_DIR/example"
build/mindmap snapshot --root "$MINDMAP_HOME_DIR/example"
```

Launch `build/mindmap --root "$MINDMAP_HOME_DIR/example"` in the ordinary shell, tmux, `TERM=screen-256color`, `TERM=xterm-256color`, and a non-UTF-8 locale. Also run it through a pseudo-terminal with `TERM=dumb`.

Expected: capable terminals remain interactive; limited encodings use ASCII; resize redraws cleanly; <kbd>?</kbd> opens and closes the full shortcut overlay; <kbd>q</kbd> exits. `TERM=dumb` prints one static ASCII snapshot and exits without an escape byte.

## 3. Codex backfill and persistence

Install the local marketplace/plugin, then begin a fresh Codex session inside the disposable repository. Discuss one future plan, one active thread, one settled decision, and one unresolved question. Halfway through, invoke `$mindmap:manage start`.

Expected: the first record reconstructs those concepts rather than creating one node per message. The future plan remains `planned`. Finish the session, begin another beneath the same project, and invoke `$mindmap:manage status`; the prior tree should already be present in SessionStart context.

In a host that supports steering, checkpoint a turn and then add another user prompt under the same interaction. Expected: the next injected context contains `MINDMAP_CHECKPOINT_REOPENED_V1`, preserves both prompts, retains the first mutations, and requires an incremental corrective checkpoint.

Next, let the record command run, execute another shell or edit tool immediately, and finish within one second. Expected: Stop reports `post_checkpoint_tool_activity` and requests one reconciliation pass. A long, clean final response after a generation-aware checkpoint must not reopen merely because sixty seconds passed. Also simulate an old zero-generation checkpoint more than 60 seconds before Stop. Expected: the legacy fallback still requests one reconciliation pass.

Grow the fixture beyond 24 meaningful sibling concepts across several turns. Expected: the map accepts them. A single checkpoint with 21 new concepts, a fifth independent root, a branch deeper than ten levels, and a numbered turn/message node must still fail independently.

Start a separate session outside the project and invoke start. Expected: activation is blocked for that session rather than silently retargeted through a tool workdir.

Run the opt-in behavioral handoff evaluation:

```sh
make test-frontier-handoff
```

This uses one real Codex model turn and is intentionally outside `make validate`. Expected: the fixture task completes and its decision becomes a child of the seeded target frontier, not the root or the plausible decoy.

## 4. Claude handoff

Install the local Claude plugin or launch:

```sh
claude --plugin-dir ./plugins/claude/mindmap
```

Begin a fresh local session in the same project, invoke `/mindmap:manage status`, and record one new branch.

Expected: Claude sees the Codex-created map. Codex sees Claude's update in a later turn. Neither host reports a lock error.

Run the isolated unattended-permission case:

```sh
make test-claude-permission
```

Expected: built-in shell access and external MCP servers are unavailable, Claude completes without a checkpoint, the snapshot reports one unresolved checkpoint, and a synthetic next prompt receives `MINDMAP_PRIOR_CHECKPOINT_MISSING_V1`. Repeat once with the normal MCP configuration and built-in `Bash` denied. Record the actual tool name used; an MCP shell executor is a valid alternate path and must still advance the tool generation.

## 5. Live terminal update and deletion

Keep the terminal viewer open while the agent records a change.

Expected: the graph refreshes within one second and preserves the selected node when it still exists.

Select a non-leaf node, press <kbd>d</kbd>, and cancel. Repeat and confirm.

Expected: cancel changes nothing. Confirm removes the node and all descendants, but not its parent or siblings. `mindmap snapshot` agrees with the display and lists the removed ids under `user_deleted_branches`. The database contains an `item.subtree_deleted` event. Ask the agent to sync: it must not recreate the branch from retained transcript evidence. Then explicitly ask it to restore one deleted concept; the record uses `restore: true`, emits `item.restored`, and removes that id from `user_deleted_branches`.

## 6. macOS desktop

In the disposable macOS user account described above, recreate a test project and map using the account's default Mindmap data directory. Then test on both Apple silicon and Intel hardware when available:

1. Download the release DMG and verify its SHA-256 entry in `checksums.txt`.
2. Confirm Gatekeeper accepts the app and `spctl --assess --type execute -vv /Applications/Mindmap.app` reports an accepted, notarized build.
3. Open the project picker and choose a map.
4. Press <kbd>⌘</kbd><kbd>O</kbd> and <kbd>⌘</kbd><kbd>N</kbd>, open a second project, and also open the first project in another window. In a picker, confirm those shortcuts open no additional windows and <kbd>Esc</kbd> closes only that picker.
5. While Mindmap is running, execute `mindmap open --root /path/to/project` twice. Confirm that one app process owns the resulting windows.
6. Pan and zoom the second project's graph, then record a change in the first project. Confirm that the second window keeps its viewport.
7. Use Tab and Enter or Space to open a node. Confirm that long, multiline, and Unicode titles stay inside their pills.
8. Open the delete dialog. Confirm that Cancel receives focus, Tab remains inside the dialog, Escape cancels, and focus returns to the invoking control.
9. Reopen deletion, let an agent change that branch while the dialog is open, then confirm. Expected: deletion is rejected until the changed branch is reviewed again.
10. Confirm a stable branch deletion from one window.

Expected: windows act independently; no browser or terminal appears; each graph refreshes within one second; every window sees a same-process deletion; the correct branch disappears only after confirmation; reopening the app reads the retained state.

## 7. Late agent installation

In a clean user profile, install `mindmap` before either agent. The installer should finish with a clear setup notice. Install Codex and run:

```sh
mindmap setup codex
mindmap integrations
```

Install Claude later and run:

```sh
mindmap setup claude
mindmap setup --all
mindmap setup --refresh --all
mindmap doctor
```

Expected: setup is idempotent, refresh updates existing installations, each integration is detected independently, and a new local desktop or CLI session can invoke the management skill. Repeat once from Finder-launched Codex Desktop and Claude Desktop, and confirm a lifecycle hook runs without a Python-not-found warning. If either host command is absent from the shell `PATH`, record the host-specific marketplace setup needed before rerunning `mindmap setup`. If the configured interpreter later moves, rerun setup or set `MINDMAP_PYTHON` to an absolute Python 3.10+ path in the host's local environment.

## 8. Stop behavior

Invoke the host's Mindmap stop action and complete its final checkpoint. Begin another session beneath the project.

Expected: the map stays viewable, the project is marked paused, and hooks inject no Mindmap context until another explicit start.

## 9. Release evidence

Before publishing, retain:

- `make validate` output
- race, vet, vulnerability, dependency, and history-secret scan summaries
- package contents and SHA-256 checksums
- `gh attestation verify` output for one terminal binary, each plugin, and the DMG
- `codesign`, `spctl`, `notarytool`, and stapler results
- terminal/tmux capture notes
- Codex CLI/Desktop and Claude CLI/Desktop scenario results

Finish with a cold-read test: someone unfamiliar with the session should identify the root intent, settled branches, active frontier, and stated next step in ten seconds.
