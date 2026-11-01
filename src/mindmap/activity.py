"""Inert compatibility entry points for retired PreToolUse hooks."""
from __future__ import annotations

from typing import Any


def note_pre_tool_activity(host: str, payload: dict[str, Any]) -> None:
    return None


def run_pre_tool_hook(host: str, payload: dict[str, Any]) -> int:
    return 0
