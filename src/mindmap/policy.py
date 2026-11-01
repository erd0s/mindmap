"""Execution-mode eligibility for automatic Mindmap tracking.

Directory-based activation must not attach every process that happens to run
beneath an active root. Some launches use an execution contract that Mindmap
cannot honour: a nonpersistent run keeps no transcript to reconstruct, and an
automated utility run may forbid extra tool calls or file writes, so the record
command can never succeed. This module keeps that decision small, dependency
free, and shared by the full lifecycle hook and the fast PreToolUse path.
"""

from __future__ import annotations

import os
from typing import Any

TRACKING_ENV = "MINDMAP_TRACKING"
_OFF_VALUES = {"off", "0", "false", "no", "disabled"}
_ON_VALUES = {"on", "1", "true", "yes", "enabled"}


def tracking_policy() -> str | None:
    """Return the explicit launcher policy: "off", "on", or None when unset."""
    value = os.environ.get(TRACKING_ENV, "").strip().lower()
    if value in _OFF_VALUES:
        return "off"
    if value in _ON_VALUES:
        return "on"
    return None


def tracking_exclusion(host: str, payload: dict[str, Any]) -> str | None:
    """Explain why automatic tracking must skip this hook, or return None.

    An explicit ``MINDMAP_TRACKING=off`` in the host process environment always
    wins, and ``MINDMAP_TRACKING=on`` always opts a launcher in. Otherwise a
    Codex payload whose ``transcript_path`` is present but null identifies a
    nonpersistent run such as ``codex exec --ephemeral``: the host keeps no
    rollout, so there is nothing to back-fill and nothing a later session could
    reconcile. A payload without the key at all is left alone because only the
    host contract, not a missing field, establishes nonpersistence.
    """
    policy = tracking_policy()
    if policy == "off":
        return f"{TRACKING_ENV} is off for this process"
    if policy == "on":
        return None
    if (
        host == "codex"
        and "transcript_path" in payload
        and payload.get("transcript_path") in (None, "")
    ):
        return "nonpersistent Codex session: the host supplied no transcript path"
    return None
