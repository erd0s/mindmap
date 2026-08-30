from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _database_path() -> Path:
    override = os.environ.get("MINDMAP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve() / "mindmap.sqlite3"
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "mindmap" / "mindmap.sqlite3").resolve()


def _is_within(path: Path, root: str) -> bool:
    try:
        path.relative_to(Path(root).expanduser().resolve(strict=False))
        return True
    except ValueError:
        return False


def note_pre_tool_activity(host: str, payload: dict[str, Any]) -> None:
    """Record PreToolUse with one SQLite connection and no schema scan."""
    database = _database_path()
    session_id = payload.get("session_id")
    if not database.is_file() or not isinstance(session_id, str) or not session_id:
        return
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve(strict=False)
    interaction_id = payload.get("turn_id") or payload.get("prompt_id")
    if not isinstance(interaction_id, str) or not interaction_id:
        interaction_id = None
    tool_name = str(payload.get("tool_name") or "unknown")[:200]
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with sqlite3.connect(database, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        project_id = next(
            (
                row["id"]
                for row in connection.execute(
                    "SELECT id, root_path FROM projects WHERE active = 1 ORDER BY length(root_path) DESC"
                )
                if _is_within(cwd, row["root_path"])
            ),
            None,
        )
        if project_id is None:
            return
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute(
            """
            SELECT id FROM sessions
            WHERE project_id = ? AND host = ? AND session_id = ?
            """,
            (project_id, host, session_id),
        ).fetchone()
        if not session:
            return
        if interaction_id:
            turn = connection.execute(
                "SELECT id FROM turns WHERE session_pk = ? AND interaction_id = ?",
                (session["id"], interaction_id),
            ).fetchone()
        else:
            turn = connection.execute(
                "SELECT id FROM turns WHERE session_pk = ? ORDER BY id DESC LIMIT 1",
                (session["id"],),
            ).fetchone()
        if not turn:
            return
        connection.execute(
            """
            UPDATE turns
            SET tool_activity_generation = tool_activity_generation + 1,
                last_tool_name = ?, last_tool_at = ?
            WHERE id = ?
            """,
            (tool_name, now, turn["id"]),
        )


def run_pre_tool_hook(host: str, payload: dict[str, Any]) -> int:
    try:
        note_pre_tool_activity(host, payload)
    except Exception as exc:
        # This path is a finality signal, not an enforcement boundary. The host
        # must never strand a tool call because activity tracking failed.
        print(f"Mindmap hook warning: {exc}", file=sys.stderr)
    return 0
