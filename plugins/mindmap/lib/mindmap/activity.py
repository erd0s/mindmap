from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .checkpoint_tools import checkpoint_tool_kind


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
    # The fast path never attaches a session. An excluded run has no session
    # row and therefore no turn to advance, while any attached session keeps
    # counting its tools regardless of the launcher policy, so no eligibility
    # check is needed here.
    cwd = Path(str(payload.get("cwd") or os.getcwd())).expanduser().resolve(strict=False)
    interaction_id = payload.get("turn_id") or payload.get("prompt_id")
    if not isinstance(interaction_id, str) or not interaction_id:
        interaction_id = None
    tool_name = str(payload.get("tool_name") or "unknown")[:200]
    now = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with closing(sqlite3.connect(database, timeout=10)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        project = next(
            (
                row
                for row in connection.execute(
                    "SELECT id, root_path FROM projects WHERE active = 1 ORDER BY length(root_path) DESC"
                )
                if _is_within(cwd, row["root_path"])
            ),
            None,
        )
        if project is None:
            return
        connection.execute("BEGIN IMMEDIATE")
        session = connection.execute(
            """
            SELECT id FROM sessions
            WHERE project_id = ? AND host = ? AND session_id = ?
            """,
            (project["id"], host, session_id),
        ).fetchone()
        if not session:
            return
        if interaction_id:
            turn = connection.execute(
                "SELECT id, interaction_id FROM turns WHERE session_pk = ? AND interaction_id = ?",
                (session["id"], interaction_id),
            ).fetchone()
        else:
            turn = connection.execute(
                "SELECT id, interaction_id FROM turns WHERE session_pk = ? ORDER BY id DESC LIMIT 1",
                (session["id"],),
            ).fetchone()
        if not turn:
            return
        kind = checkpoint_tool_kind(payload, host=host, session_id=session_id,
                                    interaction_id=turn["interaction_id"], turn_pk=turn["id"],
                                    root=project["root_path"])
        advance_tool_activity(connection, turn["id"], tool_name, now, kind)


def advance_tool_activity(connection, turn_pk: int, tool_name: str, now: str, kind: str) -> None:
    # Ambiguous record commands still make Stop stale, but repeated attempts
    # cannot manufacture the intervening-work authorization for a correction.
    try:
        connection.execute(
            """
            UPDATE turns SET tool_activity_generation = tool_activity_generation + 1,
              classified_tool_activity_generation = tool_activity_generation + 1,
              last_non_record_tool_generation = CASE WHEN ? = 'work'
                THEN tool_activity_generation + 1 ELSE last_non_record_tool_generation END,
              last_effective_tool_generation = CASE WHEN ? <> 'record'
                THEN tool_activity_generation + 1
                WHEN tool_activity_generation > classified_tool_activity_generation
                THEN tool_activity_generation ELSE last_effective_tool_generation END,
              last_tool_name = CASE WHEN ? <> 'record' THEN ? ELSE last_tool_name END,
              last_tool_at = CASE WHEN ? <> 'record' THEN ? ELSE last_tool_at END WHERE id = ?
            """, (kind, kind, kind, tool_name[:200], kind, now, turn_pk),
        )
    except sqlite3.OperationalError as exc:
        if not any(f"no such column: {name}" in str(exc) for name in ("last_non_record_tool_generation", "last_effective_tool_generation", "classified_tool_activity_generation")):
            raise
        # A hot-updated hook may run before the next full lifecycle migration.
        # Preserve finality on old schemas; migration treats old activity as
        # unclassified rather than inventing corrective-record authorization.
        connection.execute(
            "UPDATE turns SET tool_activity_generation=tool_activity_generation+1, "
            "last_tool_name=?, last_tool_at=? WHERE id=?", (tool_name[:200], now, turn_pk),
        )


def run_pre_tool_hook(host: str, payload: dict[str, Any]) -> int:
    try:
        note_pre_tool_activity(host, payload)
    except Exception as exc:
        # This path is a finality signal, not an enforcement boundary. The host
        # must never strand a tool call because activity tracking failed.
        print(f"Mindmap hook warning: {exc}", file=sys.stderr)
    return 0
