from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

from .errors import MindmapError
from .paths import database_path, discover_project_root
from .policy import tracking_exclusion
from .store import Store
from .delivery import context as bounded_context, bounded_message


ACTION_PATTERN = re.compile(
    # Codex accepts both the fully-qualified skill invocation and a natural
    # plugin-level shorthand. Claude keeps its namespaced slash command.
    r"\s*(?:\$mindmap(?::manage)?|/mindmap:manage)\s+"
    r"(start|sync|status|stop)\s*",
    re.IGNORECASE,
)
MAX_CHECKPOINT_TO_STOP_SECONDS = 60.0


def explicit_action(prompt: str) -> str | None:
    match = ACTION_PATTERN.fullmatch(prompt or "")
    return match.group(1).lower() if match else None


def interaction_id(payload: dict[str, Any]) -> str | None:
    value = payload.get("turn_id") or payload.get("prompt_id")
    if isinstance(value, str) and value:
        return value
    return None


def _runner_path() -> str:
    override = os.environ.get("MINDMAP_RUNNER")
    if override:
        return str(Path(override).expanduser().resolve())
    plugin_root = os.environ.get("PLUGIN_ROOT") or os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return str(Path(plugin_root).expanduser().resolve() / "bin" / "mindmap")
    return "mindmap"


def _command(*parts: str) -> str:
    return " ".join(shlex.quote(part) for part in (_runner_path(), *parts))


def _additional(event: str, text: str) -> dict[str, Any]:
    return bounded_message(event, text.splitlines())


def _activation_blocked(event: str, cwd: str, error: MindmapError) -> dict[str, Any]:
    return _additional(
        event,
        "MINDMAP_ACTIVATION_BLOCKED_V1\n"
        f"Mindmap could not safely activate this session's working directory, {cwd}: {error}\n"
        "This session is not tracked, and no transcript backfill or turn checkpoint has been scheduled. "
        "Do not change directory, set a different tool workdir, or activate a guessed child project as a "
        "fallback: lifecycle hooks will continue to resolve the original session working directory, so "
        "that project would be active without this session being attached. Resolve the reported validation "
        "error instead. If the intended project is a different directory, start a new agent session from "
        "inside it and invoke the Mindmap start action there. Do not claim that Mindmap is active or that "
        "tracking/backfill will happen for this session.",
    )


def _inactive_action_context(event: str, cwd: str, start_command: str) -> dict[str, Any]:
    return _additional(
        event,
        "MINDMAP_INACTIVE_V1\n"
        f"Mindmap is inactive for this session's working directory, {cwd}.\n"
        "Any active child project does not contain this directory and is not attached to this session. "
        "Do not change directory or set a different tool workdir to inspect, sync, stop, or claim tracking "
        "for another project. Use the explicit start action from a new agent session inside the intended "
        f"project directory.\nSame-directory fallback only: {start_command}",
    )


def handle_hook(host: str, payload: dict[str, Any], store: Store | None = None) -> dict[str, Any] | None:
    event = str(payload.get("hook_event_name") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    session_id = str(payload.get("session_id") or "")
    transcript_path = payload.get("transcript_path")
    prompt = str(payload.get("prompt") or "")
    action = explicit_action(prompt)
    # An explicit Mindmap invocation is always honoured. Otherwise a launcher
    # opt-out or a nonpersistent host run must not be attached, given context,
    # counted, or asked for a checkpoint. A session that is already attached
    # keeps its normal lifecycle so an explicit start is never half-tracked.
    exclusion = None if action else tracking_exclusion(host, payload)
    if store is None:
        if not action and not database_path().exists():
            return None
        store = Store()
    if exclusion and (not session_id or store.session(host, session_id) is None):
        return None
    project = store.find_project(cwd, active_only=True)
    activated_now = False

    if event == "UserPromptSubmit" and action == "start" and not project:
        try:
            project = store.activate(discover_project_root(cwd))
        except MindmapError as exc:
            return _activation_blocked(event, cwd, exc)
        activated_now = True

    if not project:
        retained = store.find_project(cwd, active_only=False)
        if event == "UserPromptSubmit" and action == "status" and retained:
            return bounded_context(store, retained, event, inactive=True, prompt=prompt)
        if event == "UserPromptSubmit" and action:
            start_command = _command("start", "--root", str(discover_project_root(cwd)))
            if action == "start":
                return _additional(event, f"Activate Mindmap with: {start_command}")
            return _inactive_action_context(event, cwd, start_command)
        return None

    if not session_id:
        return _additional(event, "Mindmap found an active project, but this hook supplied no session_id.")

    if event == "PreToolUse":
        tool_name = str(payload.get("tool_name") or "unknown")
        store.note_tool_activity(
            project["id"], host, session_id, interaction_id(payload), tool_name, payload
        )
        return None

    session = store.register_session(
        project["id"],
        host,
        session_id,
        str(transcript_path) if transcript_path else None,
        # A prompt is authoritative evidence that the host session is live. This
        # also repairs a late SessionEnd notification before creating the turn.
        reopen=event in {"SessionStart", "UserPromptSubmit"},
    )

    transcript_warning: str | None = None
    if event in {"SessionStart", "UserPromptSubmit", "PreCompact", "PostCompact", "Stop", "SessionEnd"}:
        try:
            imported = store.import_transcript(host, session_id)
            warnings = imported.get("warnings", [])
            if warnings:
                transcript_warning = " ".join(str(warning) for warning in warnings)
        except (MindmapError, OSError) as exc:
            transcript_warning = str(exc)

    turn_id = interaction_id(payload)
    if event == "UserPromptSubmit":
        if not turn_id:
            return _additional(
                event,
                "MINDMAP_IDENTITY_UNAVAILABLE_V1\n"
                "This host did not supply a per-prompt turn_id/prompt_id, so Mindmap cannot "
                "safely checkpoint this turn. Do not call record with a session-wide fallback id. "
                "Continue the user's task, warn that this turn will not be mapped, and upgrade the host.",
            )
        turn_status = store.begin_turn(project["id"], session["id"], turn_id, prompt)
        prior_unresolved = store.prior_unresolved_checkpoint(
            host, session_id, turn_id
        )
        effective_action = "sync" if action == "start" and not activated_now else action
        diagnostics = []
        if turn_status["checkpoint_invalidated"]:
            diagnostics.append("MINDMAP_CHECKPOINT_REOPENED_V1: Another user prompt reopened this interaction. Prior mutations remain; record only additional or corrective changes against current revisions.")
        if prior_unresolved:
            diagnostics.append("MINDMAP_PRIOR_CHECKPOINT_MISSING_V1: A previous final response has no checkpoint. Reconcile missing changes and ensure the host is permitted to run the bound command; do not claim prior completion.")
        if transcript_warning:
            diagnostics.append("Transcript import warning: source unavailable or incomplete. Continue from durable state and last_assistant_message; do not claim complete backfill.")
        return bounded_context(store, project, event, host=host, session_id=session_id,
                               turn_id=turn_id, prompt=prompt, action=effective_action,
                               diagnostics=diagnostics)

    if event == "SessionStart":
        diagnostics = ["Transcript import warning: source unavailable or incomplete; do not claim complete backfill."] if transcript_warning else []
        return bounded_context(store, project, event, host=host, session_id=session_id, diagnostics=diagnostics)

    if event in {"PreCompact", "PostCompact"}:
        # Import side effects are useful, but neither host documents model-visible
        # additionalContext for these events. SessionStart(compact) restores context.
        return None

    if event == "Stop":
        if not turn_id:
            return None
        last_message = payload.get("last_assistant_message")
        if isinstance(last_message, str) and last_message.strip():
            store.add_last_assistant_message(host, session_id, turn_id, last_message)
        turn, reason = store.checkpoint_for_stop(host, session_id, turn_id, MAX_CHECKPOINT_TO_STOP_SECONDS)
        if not turn:
            return None
        checkpointed = bool(turn["checkpointed_at"])
        if not checkpointed and not bool(payload.get("stop_hook_active")):
            recovery = {
                "post_checkpoint_tool_activity": "Later tools left this checkpoint stale. Review the work and record an incremental correction, then finish again.",
                "long_post_checkpoint_window": "Legacy checkpoint is over 60 seconds old with no observed tool coverage. Review later work and checkpoint again.",
            }.get(reason, "This turn has not been checkpointed. Review the work, record a delta (empty is valid), then finish again.")
            diagnostics = ["Transcript import incomplete; use durable state and the final response."] if transcript_warning else []
            return bounded_context(store, project, event, host=host, session_id=session_id,
                                   turn_id=turn_id, recovery=recovery, diagnostics=diagnostics,
                                   action=explicit_action(str(turn.get("prompt_excerpt") or "")) if turn else None)
        if checkpointed and turn and explicit_action(str(turn.get("prompt_excerpt") or "")) == "stop":
            store.deactivate(project["root_path"])
        return None

    if event == "SessionEnd":
        store.end_session(host, session_id)
    return None


def run_hook_payload(host: str, payload: Any) -> int:
    try:
        if not isinstance(payload, dict):
            raise MindmapError("Hook input must be a JSON object.")
        output = handle_hook(host, payload)
        if output is not None:
            serialized = json.dumps(output, ensure_ascii=False, separators=(",", ":"))
            from .diagnostics import emit
            context = output.get("reason") or output.get("hookSpecificOutput", {}).get("additionalContext", "")
            emit("hook", host=host, event=payload.get("hook_event_name"),
                 serialized_bytes=len(serialized.encode()) + 1, context_bytes=len(context.encode()), context=context)
            print(serialized)
        return 0
    except Exception as exc:
        # Hooks must fail open: a tracking problem should never strand the coding session.
        print(f"Mindmap hook warning: {exc}", file=__import__("sys").stderr)
        return 0


def run_hook(host: str) -> int:
    try:
        payload = json.load(__import__("sys").stdin)
    except Exception as exc:
        print(f"Mindmap hook warning: {exc}", file=__import__("sys").stderr)
        return 0
    return run_hook_payload(host, payload)
