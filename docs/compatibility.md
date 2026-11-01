# Compatibility during the integration pause

Automatic Codex and Claude integration is paused on every platform as of 1 November 2026. The repository no longer declares a marketplace or produces host plugins. Earlier host-version and lifecycle qualifications are historical evidence, not current support claims.

| Component | Current boundary |
|---|---|
| Go terminal viewer and CLI | Retained; uses the existing local SQLite store |
| macOS desktop app | Retained; native build and window checks require macOS |
| Standalone Python CLI | Python 3.10+; explicit manual commands only |
| Codex and Claude lifecycle hooks | Retired entry points return silently without reading input or data |
| Setup and refresh | Disabled before client discovery, subprocess execution, or configuration writes |
| Remote or cloud integration | No automatic integration or cross-machine data synchronization |

`start` retains the existing activation flag for manual records. An active flag in an old database does not enable capture in the current runtime. Manual `attach` and `transcript` commands can still import explicitly selected evidence; `context` can still render a map on request.

## Existing installations and sessions

Client uninstallation removes registrations on disk. A running CLI session or desktop client may retain hook definitions that refer to a removed executable. Save or finish the affected work, exit that client process normally, and start a fresh process before resuming. Do not interrupt unrelated work or delete session history to clear hooks.

A new `plugin list` process verifies registrations on disk; it cannot clear definitions already held by another process. Previously released binaries, old checkouts, and quarantine copies retain their historical behavior. These local source changes do not patch those copies. Do not run their setup commands during the pause.

Future adoption requires an instruction and context-injection review, changes where needed, and an explicit installation-scope decision. See [the pause record](integration-paused.md).
