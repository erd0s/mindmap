"""Distinguish checkpoint attempts from work preceding a corrective checkpoint.

This is a conservative shell recognizer, not a shell interpreter. Only a single
literal record invocation (optionally fed by a quoted heredoc/literal printf)
is finality-neutral. A compound/opaque invocation mentioning record remains
visible to Stop but cannot itself authorize another conflicting checkpoint.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any


def runner_path() -> str:
    override = os.environ.get("MINDMAP_RUNNER")
    if override:
        return str(Path(override).expanduser().resolve())
    root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    return str(Path(root).expanduser().resolve() / "bin" / "mindmap") if root else "mindmap"


def checkpoint_tool_kind(
    payload: dict[str, Any], *, host: str, session_id: str, interaction_id: str,
    turn_pk: int, root: str,
) -> str:
    value = payload.get("tool_input", payload.get("input", {}))
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = {"command": value}
    command = (value.get("command") or value.get("cmd")) if isinstance(value, dict) else None
    if not isinstance(command, str):
        name = str(payload.get("tool_name") or "").rsplit(".", 1)[-1].lower()
        # With no inspectable shell command, repeated executor attempts cannot
        # establish independent work. They still count for Stop finality.
        if name in {"bash", "exec", "exec_command", "shell", "shell_command"}:
            return "ambiguous_record"
        return "work"
    possible_record = "record" in command and ("mindmap" in command or runner_path() in command or "--turn-ref" in command)
    if not possible_record:
        return "work"
    # A quoted delimiter suppresses command/variable substitution in stdin.
    heredoc = re.fullmatch(r"([^\n]+?)\s*<<\s*(['\"])([A-Za-z_][A-Za-z_0-9]*)\2\s*\n(.*)\n\3\s*", command, re.S)
    if heredoc:
        if heredoc.group(3) in heredoc.group(4).splitlines():
            return "ambiguous_record"
        command = heredoc.group(1)
    if any(c in command for c in ("$", "`", "\n", "\r")):
        return "ambiguous_record"
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
    except ValueError:
        return "ambiguous_record"
    if "|" in words:
        split = words.index("|")
        # Only literal printf input, not an arbitrary producer or another tool.
        producer = words[:split]
        if not producer or producer[0] != "printf" or len(producer) not in (3, 4):
            return "ambiguous_record"
        if producer[1] not in ("%s", "%s\\n"):
            return "ambiguous_record"
        words = words[split+1:]
    if len(words) < 2 or words[0] != runner_path() or words[1] != "record":
        return "ambiguous_record"
    args = words[2:]
    if len(args) % 2:
        return "ambiguous_record"
    options = dict(zip(args[::2], args[1::2]))
    if len(options) != len(args)//2 or set(options) - {"--root", "--host", "--session-id", "--interaction-id", "--file", "--turn-ref"}:
        return "ambiguous_record"
    if any(word in {";", "&&", "||", "&", "|", "<", ">", "<<", ">>"} for word in words):
        return "ambiguous_record"
    if "--turn-ref" in options:
        matches = options["--turn-ref"] == str(turn_pk) and set(options) <= {"--turn-ref", "--file"}
    else:
        matches = (options.get("--host") == host and options.get("--session-id") == session_id
                   and options.get("--interaction-id") == interaction_id
                   and options.get("--root") == root)
    # A record for another turn/project is real work for this turn.
    return "record" if matches else "work"
