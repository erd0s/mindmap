# Agent integration paused

Automatic Mindmap integration is paused as of 1 November 2026. It is not currently in use by the owner and needs changes and review before reconsideration. This source change retains the standalone viewers, manual CLI, storage schema, and transcript import tools. It does not migrate or delete user data.

## Removed entry paths

| Entry point | Previous behavior | Current behavior |
|---|---|---|
| `install.sh` | Downloaded the terminal binary, then ran `setup --all` | Downloads the binary only; never executes its setup path |
| `install.ps1` | Installed the terminal viewer | Remains standalone; reports the integration pause |
| Go `setup`, `--all`, `--source`, `--refresh` | Registered a marketplace, installed or reinstalled plugins, and saved a Python path | Returns a pause error before any discovery, subprocess, or configuration write |
| Dedicated marketplace manifests | Advertised host packages from this repository | Removed for both clients |
| `make package` and the old `build_plugins.py` command | Recreated two plugins, skills, lifecycle registrations, and release ZIPs | Generate only `packages/mindmap` and the standalone CLI ZIP; remove marked retired generated trees and old plugin ZIPs |
| CI and release packaging | Validated and published agent plugin archives | Validate and package the standalone runtime; no agent archives in the release manifest |
| Public lifecycle and activity callbacks | Captured transcripts, tracked tool activity, injected context, and requested Stop reconciliation | Silent no-ops, including on active maps and malformed input |
| Live agent evaluation commands | Installed plugins into evaluation homes and started model sessions | Exit with a pause error; offline scoring remains available |

The retired lifecycle events were `SessionStart`, `UserPromptSubmit`, `PreToolUse`, `Stop`, `PreCompact`, `PostCompact`, and `SessionEnd`. Their old algorithms remain under `review/agent_integration` for offline fixtures. The old management skill remains under `core/skills/mindmap` for instruction review. Neither is included in the standalone package. Historical installer and live-evaluation implementations remain in Git history.

The generator is the only writer of the checked-in `packages/mindmap` tree. Change `src/mindmap` or the standalone launchers in `platforms`, then run `make package`. It does not alter client homes, maps, transcripts, credentials, or quarantine records.

## Retained operations

The Go CLI and terminal viewer, macOS desktop app, and Python storage and transcript tools remain usable. Python `attach` and `transcript` can import explicitly selected evidence. `context` prints context on request. `record` applies a manual map update. `start` and `stop` retain the existing project activation flag without enabling automatic capture. Old active maps stay readable without changing that flag.

Read-only integration diagnostics remain available for identifying old installations. They do not offer a repair or update path. Existing released binaries and other checkouts retain their old behavior until separately replaced; this local change does not patch them. The maintained shell installer is safe even when it downloads an older binary because it never executes that binary, but running the older binary's setup command can still reinstall the old plugin.

## Validation and review boundary

`make validate` runs Python, Go, frontend, desktop service, package consistency, reproducibility, and notice checks. The pause fixtures verify all retired hook events against an active map and retained transcript, setup and refresh with isolated client homes, and repeat installation of a fixture release whose old binary still implements setup.

`MINDMAP_REQUIRE_HOST_VALIDATORS=1 python3 scripts/run_host_validators.py` checks that real Codex and Claude commands reject this checkout as a marketplace. Both receive fresh temporary homes without credentials; these checks do not start model sessions or change the user's registrations.

Uninstallation cannot clear hooks already held by a running client. Save or finish affected sessions, then start fresh client processes. Machine-specific findings and restart candidates belong in the owner's local handover, outside the public source tree.

Before any adoption, review the management instructions, unwanted context injection, capture scope, checkpoint demands, and effects on unrelated work. Make the required changes, select an explicit installation scope, and test that design in isolation. Re-enabling, deployment, and publication each require a separate decision. Keep Mindmap out of the shared catalogue during the pause.
