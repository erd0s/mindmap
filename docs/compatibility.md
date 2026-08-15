# Codex and Claude Code compatibility

Research checked against official product documentation on 15 August 2026.

## Supported environments

| Surface | Version 0.3 support |
|---|---|
| Codex CLI and local Codex Desktop sessions | macOS and Linux; Python 3.10+ |
| Claude Code CLI | macOS and Linux; Python 3.10+ |
| Claude Desktop Code sessions | macOS; Python 3.10+ |
| Mindmap Desktop | macOS 12+, Intel and Apple silicon |
| Mindmap terminal viewer | Darwin, FreeBSD, Linux, OpenBSD, and Windows release targets |
| Windows agent integration | Deferred |
| Remote or cloud agent sessions | Not supported by the local store |

Codex marketplace ingestion is validated with 0.147.0. Claude Code requires 2.1.196 or later because that release introduced the per-prompt identity used for safe turn correlation; package validation targets 2.1.228. The manual release runbook covers actual lifecycle sessions in both hosts.

## Desktop means a local coding session

Mindmap works the same way in supported local desktop coding sessions as it does in the corresponding CLI: the plugin's skill decides what belongs in the map, lifecycle hooks attach exact session and turn identities, and both hosts write the same local SQLite database.

This does not include an ordinary ChatGPT or Claude conversation. It also does not turn a remote session into a local one. Claude documents that installed plugins apply to local and SSH sessions but not remote sessions. A remote machine can run its own Mindmap database, but version 0.3 does not synchronize it with the local database.

Claude Desktop exposes Claude Code through its Code tab. Run `mindmap setup claude` to configure and install the marketplace, then use Desktop's plugin manager to enable or manage it. Codex supports plugins across its desktop and CLI surfaces; Mindmap is installed from its GitHub marketplace by `mindmap setup codex`. Setup requires the corresponding host command to be visible on the shell `PATH`.

Setup also validates Python 3.10+ and saves its absolute path in Mindmap's private user configuration. Hooks and the packaged fallback command invoke a bundled `/bin/sh` launcher that checks that saved path before the desktop process's `PATH`; it also recognizes standard Homebrew, framework, pyenv, asdf, mise, Nix, MacPorts, and user-local locations. If Python moves, rerun setup. `MINDMAP_PYTHON=/absolute/path/to/python3` is an explicit host-environment override. The release runbook still requires a real Finder-launched session in each desktop host because package validation cannot prove a host's local-session environment.

## Shared lifecycle contract

Both generated plugins use these events:

- `SessionStart`
- `UserPromptSubmit`
- `Stop`
- `PreCompact`
- `PostCompact`
- `SessionEnd`

Hook inputs share `session_id`, `cwd`, `transcript_path`, and an event name. Codex supplies `turn_id`; Claude supplies `prompt_id`. Mindmap stores either as `interaction_id`. A missing real identity produces a visible warning and never falls back to an unsafe session-wide checkpoint.

| Concern | Codex | Claude Code | Normalized behavior |
|---|---|---|---|
| Explicit invocation | `$mindmap:manage` or `$mindmap` | `/mindmap:manage` | Same action argument |
| Turn identity | `turn_id` | `prompt_id` | `interaction_id` |
| Plugin manifest | `.codex-plugin/plugin.json` | `.claude-plugin/plugin.json` | Generated host package |
| Hook root | `PLUGIN_ROOT` plus compatibility alias | `CLAUDE_PLUGIN_ROOT` | Shared launcher contract |
| Implicit skill use | Agent policy disables it | `disable-model-invocation: true` | Explicit-only management skill |
| Transcript caveat | Format is unstable | File can lag hook execution | Ignore unknown records; use Stop's final-message field |

The installations live in different host directories, but their runtime state does not. Plugin caches are never used as the database location.

## Official references

- [Codex: Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex: Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex: Build skills](https://learn.chatgpt.com/docs/build-skills)
- [OpenAI: Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-codex)
- [Claude Code: Desktop application](https://code.claude.com/docs/en/desktop)
- [Claude Code: Discover and install plugins](https://code.claude.com/docs/en/discover-plugins)
- [Claude Code: Hooks reference](https://code.claude.com/docs/en/hooks)
- [Agent Skills specification](https://agentskills.io/specification)
