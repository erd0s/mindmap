from __future__ import annotations

import json
import os
import re
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import MindmapError
from .paths import database_path, discover_project_root
from .store import Store


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


def _checkpoint_age_seconds(checkpointed_at: str | None) -> float | None:
    if not checkpointed_at:
        return None
    try:
        checkpointed = datetime.fromisoformat(checkpointed_at)
    except ValueError:
        return None
    if checkpointed.tzinfo is None:
        checkpointed = checkpointed.replace(tzinfo=timezone.utc)
    return max(0.0, (datetime.now(timezone.utc) - checkpointed).total_seconds())


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
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    }


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
        f"Mindmap is inactive for this session's working directory, {cwd}. "
        "Any active child project does not contain this directory and is not attached to this session. "
        "Do not change directory or set a different tool workdir to inspect, sync, stop, or claim tracking "
        "for another project. Use the explicit start action from a new agent session inside the intended "
        f"project directory. Same-directory fallback only: {start_command}",
    )


def _active_context(
    store: Store,
    project: dict[str, Any],
    host: str,
    session_id: str,
    turn_id: str,
    action: str | None,
) -> str:
    transcript_command = _command(
        "transcript", "--host", host, "--session-id", session_id, "--format", "markdown"
    )
    record_command = _command(
        "record",
        "--root",
        project["root_path"],
        "--host",
        host,
        "--session-id",
        session_id,
        "--interaction-id",
        turn_id,
        "--file",
        "-",
    )
    snapshot_command = _command("snapshot", "--root", project["root_path"])
    lines = [
        "MINDMAP_ACTIVE_V1",
        f"Mindmap is active for {project['root_path']}.",
        "Scope: this entire project directory. Other Codex or Claude sessions beneath it will also contribute until tracking is stopped.",
        f"Host/session/interaction: {host} / {session_id} / {turn_id}.",
        store.context(project["root_path"]),
        "If the durable context reports a legacy map outside compression bounds, inspect every existing id and revision with:",
        snapshot_command,
        "Use the normalized history as source evidence when this is a new or sync request:",
        transcript_command,
        "Compress the conversation into a SMALL CAUSAL TREE of concepts. Never make nodes for messages, tool calls, timestamps, or a chronological chat log.",
        "Before finishing this turn, atomically apply conceptual map changes and checkpoint it by piping JSON to:",
        record_command,
        'JSON shape: {"summary":"what changed or no map change","operations":[{"op":"upsert","id":"stable-id","title":"...","summary":"what this concept means","resume":"where to pick it up","state":"planned|open|settled","kind":"goal|thread|decision|task|question|note","parent_id":null,"expected_revision":2}]}. Omit expected_revision for a new id; use the exact current revision for any update, settle, or remove. Add "restore":true only when the user explicitly asks to restore an id listed under USER-DELETED BRANCHES.',
        "Create only meaningful concepts needed for a quick overview. Connect each child to the thought or goal that caused it. Capture explicit future intentions as planned, unresolved concepts as open, and covered/decided/completed/rejected concepts as settled. Do not invent unspoken plans.",
        'An upsert of an existing concept retains every omitted field. To clear stale frontier text, send "resume":"" explicitly; saying it is cleared in the final response is not a map change.',
        "When new evidence merely changes the state of an existing concept, update or reopen that same id. Do not add a child that only restates the symptom or evidence unless the conversation made it an independent investigation or plan. Conversely, preserve a distinct side quest, deliverable or handoff, decision, or deferred plan with its own state or re-entry point; a root summary is not a substitute for that branch.",
        "Treat the record command as the final substantive tool action: do not checkpoint while implementation, commands, tests, research, or user-requested changes remain. A later same-interaction user prompt reopens the checkpoint, but ordinary work performed after an early checkpoint may otherwise be omitted.",
    ]
    if action == "start":
        lines.append("This activation happened mid-session: RUN the transcript command, read the whole normalized history, and reconstruct its compact conceptual tree before checkpointing. Running status is not a substitute for backfill.")
    elif action == "sync":
        lines.append("RUN the transcript command and reconcile the compact conceptual tree, including earlier explicit plans not yet started. Running status is not a substitute.")
    elif action == "status":
        lines.append("Report the current map simply. Still checkpoint this turn with an empty operations list if nothing changed.")
    elif action == "stop":
        lines.append(
            "After the final record succeeds, finish the user-facing response normally. "
            "Do not run the direct stop command: the Stop hook must first capture that final response, then it will disable tracking."
        )
    if int(project.get("concept_model_version") or 1) < 2:
        lines.extend(
            [
                "LEGACY_MAP_RECONCILIATION_REQUIRED_V2",
                "This project predates causal-tree v2. RUN both the transcript and snapshot commands now, remove/merge chat-log or task-board debris, rebuild causal parentage, then include top-level \"concept_model\":\"causal-tree-v2\" in the record payload. Do this before continuing normal tracking.",
            ]
        )
    return "\n".join(lines)


def handle_hook(host: str, payload: dict[str, Any], store: Store | None = None) -> dict[str, Any] | None:
    event = str(payload.get("hook_event_name") or "")
    cwd = str(payload.get("cwd") or os.getcwd())
    session_id = str(payload.get("session_id") or "")
    transcript_path = payload.get("transcript_path")
    prompt = str(payload.get("prompt") or "")
    action = explicit_action(prompt)
    if store is None:
        if not action and not database_path().exists():
            return None
        store = Store()
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
            return _additional(
                event,
                "MINDMAP_RETAINED_READ_ONLY_V1\n"
                + store.context(retained["root_path"], include_inactive=True)
                + "\nTracking is stopped. Report this retained map without registering a session, changing items, or checkpointing the turn.",
            )
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
            project["id"], host, session_id, interaction_id(payload), tool_name
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
        context = _active_context(
            store, project, host, session_id, turn_id, effective_action
        )
        if turn_status["checkpoint_invalidated"]:
            context += (
                "\nMINDMAP_CHECKPOINT_REOPENED_V1\n"
                "This host supplied another user prompt for an interaction that was already "
                "checkpointed. The prior map mutations remain visible, but the checkpoint was "
                "reopened so this added work cannot be silently lost. Review the current revisions "
                "and record only the additional or corrective semantic changes before finishing; "
                "do not replay a stale replacement payload."
            )
        if prior_unresolved:
            last_tool = str(prior_unresolved.get("last_tool_name") or "unknown")
            context += (
                "\nMINDMAP_PRIOR_CHECKPOINT_MISSING_V1\n"
                f"Previous interaction {prior_unresolved['interaction_id']} produced a final "
                f"assistant response but no Mindmap checkpoint; its last observed tool was {last_tool}. "
                "An unattended host may have denied or failed the injected record command. "
                "Reconcile any missing semantic changes in this turn, ensure the host is permitted "
                "to run the exact injected Mindmap record command, and do not claim the previous "
                "interaction was checkpointed. A successful current checkpoint will cover this warning."
            )
        if transcript_warning:
            context += (
                "\nTranscript import warning: " + transcript_warning
                + " Continue using durable state and last_assistant_message; do not claim the backfill was complete."
            )
        return _additional(
            event,
            context,
        )

    if event == "SessionStart":
        context = (
            "MINDMAP_ACTIVE_V1\n"
            + store.context(project["root_path"])
            + "\nTracking persists until the explicit mindmap stop action. Every user turn must finish with a Mindmap record checkpoint."
        )
        if transcript_warning:
            context += "\nTranscript import warning: " + transcript_warning
        return _additional(
            event,
            context,
        )

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
        checkpointed = store.is_checkpointed(host, session_id, turn_id)
        turn = store.turn(host, session_id, turn_id)
        checkpoint_age = _checkpoint_age_seconds(
            str(turn.get("checkpointed_at") or "") if turn else None
        )
        tool_generation = int(turn.get("tool_activity_generation") or 0) if turn else 0
        checkpoint_tool_generation = (
            turn.get("checkpoint_tool_activity_generation") if turn else None
        )
        if (
            checkpointed
            and not bool(payload.get("stop_hook_active"))
            and checkpoint_tool_generation is not None
            and tool_generation > int(checkpoint_tool_generation)
            and store.invalidate_checkpoint(
                host,
                session_id,
                turn_id,
                "post_checkpoint_tool_activity",
                {
                    "checkpoint_generation": int(checkpoint_tool_generation),
                    "current_generation": tool_generation,
                    "last_tool_name": str(turn.get("last_tool_name") or "unknown"),
                },
            )
        ):
            context = _active_context(store, project, host, session_id, turn_id, None)
            return {
                "decision": "block",
                "reason": (
                    "Mindmap observed a tool call after this turn's checkpoint "
                    f"({turn.get('last_tool_name') or 'unknown'}; generation "
                    f"{checkpoint_tool_generation} -> {tool_generation}). Review the "
                    "post-checkpoint work, record only additional or corrective changes "
                    "(or a deliberate empty delta), then finish again.\n"
                    + context
                ),
            }
        if (
            checkpointed
            and not bool(payload.get("stop_hook_active"))
            and int(checkpoint_tool_generation or 0) == 0
            and checkpoint_age is not None
            and checkpoint_age > MAX_CHECKPOINT_TO_STOP_SECONDS
            and store.invalidate_checkpoint(
                host,
                session_id,
                turn_id,
                "long_post_checkpoint_window",
                {"elapsed_seconds": round(checkpoint_age, 3)},
            )
        ):
            context = _active_context(store, project, host, session_id, turn_id, None)
            return {
                "decision": "block",
                "reason": (
                    "Mindmap's checkpoint predates Stop by "
                    f"{checkpoint_age:.1f} seconds. The production audit found that long "
                    "post-checkpoint work can leave plans or completed state unrecorded. "
                    "Review the current map and final response, record only additional or "
                    "corrective changes (or a deliberate empty delta), then finish again.\n"
                    + context
                ),
            }
        if not checkpointed and not bool(payload.get("stop_hook_active")):
            context = _active_context(store, project, host, session_id, turn_id, None)
            return {
                "decision": "block",
                "reason": "Mindmap is active, but this turn has not been checkpointed. "
                "Review the work, record semantic changes (or an empty operation list), then finish again.\n"
                + context,
            }
        turn = store.turn(host, session_id, turn_id)
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
            print(json.dumps(output, separators=(",", ":")))
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
