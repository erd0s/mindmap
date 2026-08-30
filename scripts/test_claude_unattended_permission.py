#!/usr/bin/env python3
"""Exercise Claude's unattended denial of the Mindmap record command."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "claude" / "mindmap"


def run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    input_text: str | None = None,
    timeout: int = 600,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def require_success(completed: subprocess.CompletedProcess[str], action: str) -> str:
    if completed.returncode != 0:
        raise RuntimeError(
            f"{action} failed with exit {completed.returncode}:\n"
            + completed.stdout
            + completed.stderr
        )
    return completed.stdout


def main() -> int:
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("claude executable is unavailable")
    if not (PLUGIN / ".mindmap-generated").is_file():
        raise SystemExit("Claude plugin package is stale or missing; run make package")
    with tempfile.TemporaryDirectory(prefix="mindmap-claude-permission-") as temporary:
        base = Path(temporary)
        home = base / "home"
        project = home / "permission-case"
        data = base / "mindmap-data"
        project.mkdir(parents=True)
        data.mkdir()
        environment = os.environ.copy()
        environment.update({
            "MINDMAP_HOME_DIR": str(home),
            "MINDMAP_DATA_DIR": str(data),
        })
        require_success(
            run(["git", "init", "--quiet"], cwd=project, environment=environment),
            "git init",
        )
        mindmap = str(PLUGIN / "bin" / "mindmap")
        require_success(
            run([mindmap, "start", "--root", str(project)], cwd=project, environment=environment),
            "Mindmap activation",
        )
        session_id = str(uuid.uuid4())
        completed = run(
            [
                claude,
                "--print",
                "--output-format", "json",
                "--no-session-persistence",
                "--model", "haiku",
                "--permission-mode", "manual",
                "--tools", "Read",
                "--disallowedTools", "Bash",
                "--settings", json.dumps({"permissions": {"deny": ["Bash"]}}),
                "--mcp-config", json.dumps({"mcpServers": {}}),
                "--strict-mcp-config",
                "--plugin-dir", str(PLUGIN),
                "--add-dir", str(data),
                "--session-id", session_id,
                (
                    "Reply briefly that the requested work is complete. Follow all injected "
                    "Mindmap lifecycle instructions, including its final checkpoint."
                ),
            ],
            cwd=project,
            environment=environment,
        )
        snapshot_output = require_success(
            run([mindmap, "snapshot", "--root", str(project)], cwd=project, environment=environment),
            "Mindmap snapshot",
        )
        snapshot = json.loads(snapshot_output)
        sessions = [
            session for session in snapshot["sessions"]
            if session["host"] == "claude" and session["session_id"] == session_id
        ]
        if not sessions:
            raise RuntimeError("Claude did not attach the permission-case session")
        session = sessions[0]
        if int(session["turn_count"]) != 0:
            with sqlite3.connect(data / "mindmap.sqlite3") as connection:
                connection.row_factory = sqlite3.Row
                turns = [
                    dict(row) for row in connection.execute(
                        """
                        SELECT interaction_id, last_tool_name, tool_activity_generation,
                               checkpoint_tool_activity_generation
                        FROM turns ORDER BY id
                        """
                    )
                ]
            checkpoint_events = [
                event for event in snapshot.get("events", [])
                if event.get("event_type") == "turn.checkpointed"
                and event.get("session_id") == session_id
            ]
            raise RuntimeError(
                "denied record command unexpectedly produced a checkpoint:\n"
                + json.dumps({
                    "claude_stdout": completed.stdout,
                    "claude_stderr": completed.stderr,
                    "session": session,
                    "turns": turns,
                    "checkpoint_events": checkpoint_events,
                }, indent=2, sort_keys=True)
            )
        if int(session.get("unresolved_checkpoint_count") or 0) != 1:
            raise RuntimeError("denied record command was not retained as an unresolved checkpoint")

        next_prompt = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(project),
            "session_id": session_id,
            "prompt_id": str(uuid.uuid4()),
            "prompt": "Continue after the unattended run.",
        }
        hook = run(
            [str(PLUGIN / "scripts" / "run_hook.sh"), "--host", "claude"],
            cwd=project,
            environment=environment,
            input_text=json.dumps(next_prompt),
            timeout=30,
        )
        hook_output = require_success(hook, "next-prompt hook")
        marker_visible = "MINDMAP_PRIOR_CHECKPOINT_MISSING_V1" in hook_output
        result = {
            "passed": marker_visible,
            "claude_returncode": completed.returncode,
            "checkpoint_count": int(session["turn_count"]),
            "unresolved_checkpoint_count": int(session["unresolved_checkpoint_count"]),
            "next_prompt_diagnostic": marker_visible,
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        if not marker_visible:
            raise RuntimeError("next prompt did not receive the missing-checkpoint diagnostic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
