# Contributing

Thanks for helping make Mindmap clearer and more reliable.

## Before opening a change

For a bug, include the operating system, terminal, tmux status, agent and Mindmap versions, expected result, and a minimal reproduction. Remove transcripts, database files, credentials, home paths, and other private data before attaching output.

For a larger design change, open an issue first. The project deliberately avoids network services, automatic cross-machine synchronization, transcript browsing, and task-manager semantics.

## Development setup

Install Python 3.10+, Go 1.25+, and Node.js 24+, then run:

```sh
npm ci --prefix desktop/frontend
make validate
```

The Python package under `src/` and launchers under `platforms/` are the maintained sources for the standalone CLI. Agent integration is paused. Edit these sources, then regenerate the package with:

```sh
make package
```

Do not hand-edit generated files under `packages/mindmap`. The generator also removes marked retired plugin trees and their ZIPs; it does not touch client homes or user data. `scripts/build_plugins.py` is a compatibility entry point for the same standalone build.

Historical lifecycle algorithms under `review/agent_integration` and the skill under `core/skills/mindmap` are review material only. Offline fixtures exercise the former; neither is shipped or installed. Live agent evaluation commands are disabled. Restoring them requires a separate decision.

The macOS application must be built on macOS with `./scripts/build_macos_app.sh`. Linux can run its frontend tests and the Wails server-tag backend tests, but it cannot validate Apple's WebKit, signing, notarization, or window behavior.

## Change standard

- Keep the database and hook contract backward compatible or add a tested migration.
- Keep retired hook entry points silent and inert, including for active projects and malformed input.
- Add deterministic tests for bug fixes.
- Test terminal changes with a limited `TERM`, tmux, resizing, and `NO_COLOR`.
- Keep the standalone Python runtime free of third-party dependencies.
- Never commit real transcripts, databases, signing material, or credentials.

By contributing, you agree that your work is licensed under the MIT License.
