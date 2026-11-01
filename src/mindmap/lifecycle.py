"""Inert compatibility entry points while automatic integration is paused.

Do not read stdin, open the store, import transcripts, or emit agent context.
The previous implementation is retained under review/agent_integration.
"""
from __future__ import annotations

from typing import Any


def handle_hook(host: str, payload: Any, store: Any = None) -> None:
    return None


def run_hook_payload(host: str, payload: Any) -> int:
    return 0


def run_hook(host: str) -> int:
    return 0
