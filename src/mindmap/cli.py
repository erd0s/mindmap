from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .errors import MindmapError
from .lifecycle import run_hook
from .paths import discover_project_root
from .store import Store
from .transcripts import render_markdown


def _root(value: str | None, discover: bool = False) -> Path:
    candidate = Path(value or os.getcwd()).expanduser()
    return discover_project_root(candidate) if discover else candidate.resolve(strict=False)


def _emit(value: Any, human: str | None = None) -> None:
    from .diagnostics import emit
    emit("cli_result", result=value)
    if human and sys.stdout.isatty():
        print(human)
    else:
        print(json.dumps(value, indent=2, sort_keys=True))


def _payload(path: str) -> dict[str, Any]:
    if path == "-":
        if sys.stdin.isatty():
            raise MindmapError(
                "Record JSON on stdin requires a non-interactive pipe or heredoc; "
                "interactive TTY input can truncate at 4096 bytes. Do not use "
                "tty/write_stdin. Use a pipe, a heredoc, or --file PATH."
            )
        text = sys.stdin.read()
    else:
        text = Path(path).read_text(encoding="utf-8")
    value = json.loads(text)
    if not isinstance(value, dict):
        raise MindmapError("Record input must be a JSON object.")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mindmap", description="Small causal concept trees for coding-agent projects")
    parser.add_argument("--database", help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", aliases=["activate"], help="Enable persistent tracking")
    start.add_argument("--root")

    stop = sub.add_parser("stop", aliases=["deactivate"], help="Disable tracking but retain history")
    stop.add_argument("--root")

    status = sub.add_parser("status", help="Show project status")
    status.add_argument("--root")

    context = sub.add_parser("context", help="Render compact agent context")
    context.add_argument("--root")

    projects = sub.add_parser("projects", help="List all known projects")

    attach = sub.add_parser("attach", help="Attach an agent session and import its transcript")
    attach.add_argument("--root")
    attach.add_argument("--host", required=True, choices=["codex", "claude", "unknown"])
    attach.add_argument("--session-id", required=True)
    attach.add_argument("--transcript")

    transcript = sub.add_parser("transcript", help="Read normalized session history")
    transcript.add_argument("--host", required=True, choices=["codex", "claude", "unknown"])
    transcript.add_argument("--session-id", required=True)
    transcript.add_argument("--format", choices=["json", "markdown"], default="markdown")

    record = sub.add_parser("record", help="Atomically change the map and checkpoint a turn")
    record.add_argument("--root")
    record.add_argument("--supersedes", help="Explicit correction of this checkpoint token")
    record.add_argument("--host", required=True, choices=["codex", "claude", "unknown"])
    record.add_argument("--session-id", required=True)
    record.add_argument("--interaction-id", required=True)
    record.add_argument("--file", default="-", help="JSON payload path, or - for stdin")

    read = sub.add_parser("read", help="Read a bounded page of concepts or notices")
    read.add_argument("--root")
    bound = sub.add_parser("bound", help=argparse.SUPPRESS)
    bound.add_argument("binding")
    bound.add_argument("action", choices=["prepare", "commit", "record", "read", "state", "transcript", "snapshot", "help"])
    bound.add_argument("request", nargs="?")
    bound.add_argument("--file", default="-")
    bound.add_argument("--supersedes")
    for command in (read, bound):
        command.add_argument("--id", dest="item_id")
        command.add_argument("--parent")
        command.add_argument("--roots", action="store_true")
        command.add_argument("--notices", action="store_true")
        command.add_argument("--cursor")

    snapshot = sub.add_parser("snapshot", help="Export a project snapshot")
    snapshot.add_argument("--root")

    hook = sub.add_parser("hook", help=argparse.SUPPRESS)
    hook.add_argument("--host", required=True, choices=["codex", "claude"])

    return parser


def main(argv: list[str] | None = None) -> int:
    from .transport import configure_stdio
    configure_stdio()
    args = build_parser().parse_args(argv)
    if args.command == "hook":
        return run_hook(args.host)
    try:
        store = Store(args.database)
        if args.command in {"start", "activate"}:
            project = store.activate(_root(args.root, discover=True))
            _emit(project, f"Mindmap active for {project['root_path']}")
        elif args.command in {"stop", "deactivate"}:
            project = store.deactivate(_root(args.root))
            _emit(project, f"Mindmap stopped; history retained at {project['route_path']}")
        elif args.command == "status":
            project = store.find_project(_root(args.root), active_only=False)
            if not project:
                _emit({"active": False, "project": None}, "Mindmap has no project here.")
            else:
                snapshot = store.project_snapshot(project["id"])
                _emit(snapshot)
        elif args.command == "context":
            print(store.context(_root(args.root)))
        elif args.command == "projects":
            _emit(store.list_projects())
        elif args.command == "attach":
            project = store.find_project(_root(args.root), active_only=True)
            if not project:
                raise MindmapError("Mindmap is not active for this directory.")
            session = store.register_session(
                project["id"], args.host, args.session_id, args.transcript
            )
            imported = store.import_transcript(args.host, args.session_id)
            _emit({"session": session, "transcript": imported})
        elif args.command == "transcript":
            store.import_transcript(args.host, args.session_id)
            messages = store.normalized_history(args.host, args.session_id)
            print(render_markdown(messages) if args.format == "markdown" else json.dumps(messages, indent=2))
        elif args.command == "record":
            result = store.record(
                _root(args.root),
                args.host,
                args.session_id,
                args.interaction_id,
                _payload(args.file), supersedes=args.supersedes,
            )
            _emit(result)
        elif args.command in {"read", "bound"}:
            from .protocol import resolve_binding, prepare, commit
            from .retrieval import read_page, encode
            if args.command == "bound":
                with store.read_connection() as db:
                    bound = resolve_binding(db, args.binding)
                project_id = bound["project_id"]
                action = args.action
            else:
                project = store.find_project(_root(args.root), active_only=False)
                if not project:
                    raise MindmapError("No Mindmap project contains this directory.")
                project_id, action = project["id"], "read"
            if action == "read":
                page = read_page(store, project_id, item_id=args.item_id, parent=args.parent,
                                 roots=args.roots, notices=args.notices, cursor=args.cursor)
                output = encode(page)
                from .diagnostics import emit
                emit("retrieval", bytes=len(output.encode()) + 1, result=page)
                print(output)
            elif action == "prepare":
                _emit(prepare(store, args.binding, _payload(args.file), args.supersedes))
            elif action == "commit":
                _emit(commit(store, args.binding, args.request))
            elif action == "record":
                _emit(store.record(bound["root_path"], bound["host"], bound["session_id"],
                                  bound["interaction_id"], _payload(args.file), supersedes=args.supersedes))
            elif action == "state":
                turn = store.turn(bound["host"], bound["session_id"], bound["interaction_id"]) if bound['turn_id'] else None
                _emit({key: turn.get(key) if turn else None for key in
                       ("checkpoint_token", "checkpointed_at", "tool_activity_generation", "checkpoint_tool_activity_generation")})
            elif action == "transcript":
                if not bound['turn_id']:
                    raise MindmapError("No prompt identity in this binding.")
                store.import_transcript(bound["host"], bound["session_id"])
                print(render_markdown(store.normalized_history(bound["host"], bound["session_id"])))
            elif action == "snapshot":
                _emit(store.project_snapshot(project_id))
            elif action == "help":
                from .delivery import schema_help
                print(schema_help())
        elif args.command == "snapshot":
            project = store.find_project(_root(args.root), active_only=False)
            if not project:
                raise MindmapError("No Mindmap project contains this directory.")
            _emit(store.project_snapshot(project["id"]))
        return 0
    except (MindmapError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"mindmap: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
