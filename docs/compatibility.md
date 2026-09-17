# Codex and Claude Code compatibility

Research checked against official product documentation and installed host behavior on 30 August 2026.

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

Codex marketplace ingestion is validated with 0.151.0. Claude Code requires 2.1.196 or later because that release introduced the per-prompt identity used for safe turn correlation; package validation targets 2.1.251. The manual release runbook covers actual lifecycle sessions in both hosts.

## Desktop means a local coding session

Mindmap works the same way in supported local desktop coding sessions as it does in the corresponding CLI: the plugin's skill decides what belongs in the map, lifecycle hooks attach exact session and turn identities, and both hosts write the same local SQLite database.

This does not include an ordinary ChatGPT or Claude conversation. It also does not turn a remote session into a local one. Claude documents that installed plugins apply to local and SSH sessions but not remote sessions. A remote machine can run its own Mindmap database, but version 0.3 does not synchronize it with the local database.

Claude Desktop exposes Claude Code through its Code tab. Run `mindmap setup claude` to configure and install the marketplace, then use Desktop's plugin manager to enable or manage it. Codex supports plugins across its desktop and CLI surfaces; Mindmap is installed from its GitHub marketplace by `mindmap setup codex`. Setup requires the corresponding host command to be visible on the shell `PATH`.

Setup also validates Python 3.10+ and saves its absolute path in Mindmap's private user configuration. Hooks and the packaged fallback command invoke a bundled `/bin/sh` launcher that checks that saved path before the desktop process's `PATH`; it also recognizes standard Homebrew, framework, pyenv, asdf, mise, Nix, MacPorts, and user-local locations. If Python moves, rerun setup. `MINDMAP_PYTHON=/absolute/path/to/python3` is an explicit host-environment override. The release runbook still requires a real Finder-launched session in each desktop host because package validation cannot prove a host's local-session environment.

## Shared lifecycle contract

Both generated plugins use these events:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `Stop`
- `PreCompact`
- `PostCompact`
- `SessionEnd`

Hook inputs share `session_id`, `cwd`, `transcript_path`, and an event name. Codex supplies `turn_id`; Claude supplies `prompt_id` on prompt and Stop events. Claude's `PreToolUse` input has no prompt identity, so Mindmap attributes it to the latest turn in that already-attached session; Codex's `PreToolUse` uses its exact `turn_id`. A missing real identity on a prompt produces a visible warning and never falls back to an unsafe session-wide checkpoint.

| Concern | Codex | Claude Code | Normalized behavior |
|---|---|---|---|
| Explicit invocation | `$mindmap:manage` or `$mindmap` | `/mindmap:manage` | Same action argument |
| Turn identity | `turn_id` | `prompt_id` | `interaction_id` |
| Plugin manifest | `.codex-plugin/plugin.json` | `.claude-plugin/plugin.json` | Generated host package |
| Hook root | `PLUGIN_ROOT` plus compatibility alias | `CLAUDE_PLUGIN_ROOT` | Shared launcher contract |
| Implicit skill use | Agent policy disables it | `disable-model-invocation: true` | Explicit-only management skill |
| Transcript caveat | Format is unstable | File can lag hook execution | Ignore unknown records; use Stop's final-message field |
| Tool activity | Local function, shell, edit, and MCP paths expose `PreToolUse`; hosted tools may not | Built-in and MCP tools expose `PreToolUse`; prompt id is absent | Count a per-turn generation before each observed tool; snapshot it at record |

The generation check detects work after a checkpoint without waiting for elapsed time. The record command's own `PreToolUse` happens before `record`, so the saved checkpoint includes that generation. Any later observed tool advances the generation and makes Stop request one reconciliation pass. The older 60-second check remains only for turns whose checkpoint generation is zero, which identifies an older hook package or direct record call.

Record JSON travels through a non-interactive pipe or heredoc. The Python
runtime rejects interactive terminal stdin because canonical pseudo-terminals
can truncate an input line at 4096 bytes. End-of-turn side effects such as audio,
clipboard writes, and notifications therefore run before the record command;
only the final textual response follows it.

Tool names differ in practice. In the Claude permission fixture, Claude used Serena's MCP shell executor when built-in `Bash` was denied. Mindmap counted that call because the hook does not assume that shell work always travels through `Bash`. The denial fixture therefore disables external MCP servers as well as built-in shell access; otherwise it tests alternate execution, not an unavailable record path.

Claude's plugin updater treats an unchanged manifest version as already current,
even when a refreshed marketplace contains different package bytes. For that
reason, `mindmap setup --refresh claude` updates the marketplace, uninstalls the
plugin with `--keep-data`, and reinstalls it. Ordinary detected version upgrades
continue to use `claude plugin update`. Codex's refresh path already removes and
re-adds the installed plugin. Neither path changes the shared Mindmap database.

The installations live in different host directories, but their runtime state does not. Plugin caches are never used as the database location.

## Execution-mode boundary

Mindmap chooses the active project by directory, so it must also decide which processes beneath that directory are coding sessions it can serve. These rules were checked against Codex 0.154.0 and Claude Code 2.1.268.

- A nonpersistent Codex run (`codex exec --ephemeral`) sends `transcript_path: null` on every hook event; a persistent `codex exec` or an interactive session sends the rollout path on every event. Mindmap does not attach, inject context into, count tools for, or require a checkpoint from a nonpersistent Codex session. There is no transcript to back-fill, no later session could reconcile a missed checkpoint, and a utility launcher constrained to a read-only sandbox and an output schema may be unable to execute the record command.
- `MINDMAP_TRACKING=off` in the host process environment opts any launcher out of automatic tracking on both hosts. `MINDMAP_TRACKING=on` opts a nonpersistent launcher in; the semantic evaluation harness sets it because it deliberately runs nonpersistent sessions.
- An explicit `$mindmap`, `$mindmap:manage`, or `/mindmap:manage` action is always honoured, and a session that is already attached keeps its full lifecycle, including tool counting and the Stop checkpoint requirement. Exclusion is decided only for sessions that are not yet attached.
- The Codex sandbox is not visible to hooks: `permission_mode` reported `bypassPermissions` for a `--sandbox read-only` exec run, so persistence is the signal, not permissions.
- Claude Code's `--no-session-persistence` still supplies a transcript path that is never written, and `claude -p` exposes `CLAUDE_CODE_ENTRYPOINT=sdk-cli` to hooks while interactive sessions expose `cli`. Mindmap does not yet act on that signal because Claude Desktop's value has not been verified; a Claude utility launcher should set `MINDMAP_TRACKING=off`.

Excluded runs leave no rows in the database, so a map cannot show that an automated run happened. Substantive delegated work that must reach the map should either persist its transcript or opt in explicitly, and the owning interactive session remains responsible for reconciling the returned result.

## Official references

- [Codex: Build plugins](https://learn.chatgpt.com/docs/build-plugins)
- [Codex: Hooks](https://learn.chatgpt.com/docs/hooks)
- [Codex: Build skills](https://learn.chatgpt.com/docs/build-skills)
- [OpenAI: Plugins in ChatGPT and Codex](https://help.openai.com/en/articles/20001256-plugins-in-codex)
- [Claude Code: Desktop application](https://code.claude.com/docs/en/desktop)
- [Claude Code: Discover and install plugins](https://code.claude.com/docs/en/discover-plugins)
- [Claude Code: Hooks reference](https://code.claude.com/docs/en/hooks)
- [Agent Skills specification](https://agentskills.io/specification)
