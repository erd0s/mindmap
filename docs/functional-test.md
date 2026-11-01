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

Run `build/mindmap doctor`. A missing database or desktop app may warn; the database and terminal checks must not fail.

The exported variables isolate processes launched from this shell. Finder and LaunchServices apps do not reliably inherit them. Run the Finder-launched parts of section 6 in a disposable macOS user account, recreate the test project there without these overrides, and use only that account's default Mindmap database. Do not run those scenarios against a daily account or a database containing real transcripts; remove the disposable account after retaining the release evidence.

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

## 3. Paused integration and data preservation

`make validate` includes fixture checks that retired hooks produce no output and do not change an active database or transcript. It also checks setup and refresh rejection, and installs and reinstalls a fake older binary to prove the shell installer never calls setup.

With both host CLIs available, run the negative marketplace checks:

```sh
MINDMAP_REQUIRE_HOST_VALIDATORS=1 python3 scripts/run_host_validators.py
```

Each host gets a fresh temporary home without credentials. Adding this checkout as a marketplace must fail because its manifest is absent, and no Mindmap registration may remain. Do not install an old plugin to test the current package. The former live evaluation targets exit with a pause message.

## 4. Manual record and transcript operations

Use `packages/mindmap/bin/mindmap` with the fixture home and data directory above. Explicitly attach a fixture session and transcript, record a causal tree, read its context, and export a snapshot. Confirm that the Go viewer reads the same tree. No agent process is needed. The CLI and store suites cover transcript identity, incremental import, deletion tombstones, checkpoint validation, and large non-interactive payloads.

## 5. Live terminal update and deletion

Keep the terminal viewer open while the manual Python CLI records a change.

Expected: the graph refreshes within one second and preserves the selected node when it still exists.

Select a non-leaf node, press <kbd>d</kbd>, and cancel. Repeat and confirm.

Expected: cancel changes nothing. Confirm removes the node and all descendants, but not its parent or siblings. `mindmap snapshot` agrees with the display and lists the removed ids under `user_deleted_branches`. The database contains an `item.subtree_deleted` event. A manual record must not recreate a branch from retained evidence without explicit restoration. To restore one deleted concept, the record uses `restore: true`, emits `item.restored`, and removes that id from `user_deleted_branches`.

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
9. Reopen deletion, use the manual CLI to change that branch while the dialog is open, then confirm. Expected: deletion is rejected until the changed branch is reviewed again.
10. Confirm a stable branch deletion from one window.

Expected: windows act independently; no browser or terminal appears; each graph refreshes within one second; every window sees a same-process deletion; the correct branch disappears only after confirmation; reopening the app reads the retained state.

## 7. Setup and update refusal

In a disposable profile, run `build/mindmap setup codex`, `setup claude`, `setup --all`, and `setup --refresh --all`. Each must return a pause error without starting an agent, changing client settings, or touching stored data. Installing an agent later must not change this result.

Run the maintained installer twice against fixture release assets. Both runs should install only the terminal binary. Existing released binaries are outside this source check and may still implement their old setup behavior.

## 8. Manual stop behavior

Run the standalone `stop` command against the fixture project. Confirm the activation flag is cleared and its stored map and evidence remain readable. Hook entry points must be inert before and after the flag changes.

## 9. Release evidence

Keep one release-specific qualification record while this runbook is in
progress. Separate completed evidence from waived or unavailable checks so a
later release decision does not mistake partial coverage for a pass. See the
[v0.3.1 qualification record](release-qualification-v0.3.1.md) for the current
format.

Before publishing, retain:

- `make validate` output
- race, vet, vulnerability, dependency, and history-secret scan summaries
- package contents and SHA-256 checksums
- `gh attestation verify` output for one terminal binary, the standalone Python CLI archive, and the DMG
- `codesign`, `spctl`, `notarytool`, and stapler results
- terminal/tmux capture notes
- Codex CLI/Desktop and Claude CLI/Desktop scenario results

Finish with a cold-read test: someone unfamiliar with the session should identify the root intent, settled branches, active frontier, and stated next step in ten seconds.
