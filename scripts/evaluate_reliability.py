#!/usr/bin/env python3
"""Compare deterministic Mindmap reliability cases with the v0.3.0 audit baseline."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from mindmap.errors import MindmapError
from mindmap.lifecycle import handle_hook
from mindmap.store import Store


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "fixtures" / "reliability-baseline.json"


@dataclass(frozen=True)
class Result:
    passed: bool
    evidence: str


@contextmanager
def isolated_store() -> Iterator[tuple[Store, Path]]:
    previous = {key: os.environ.get(key) for key in ("MINDMAP_HOME_DIR", "MINDMAP_DATA_DIR")}
    with tempfile.TemporaryDirectory(prefix="mindmap-reliability-") as temporary:
        base = Path(temporary)
        home = base / "home"
        root = home / "project"
        root.mkdir(parents=True)
        os.environ["MINDMAP_HOME_DIR"] = str(home)
        os.environ["MINDMAP_DATA_DIR"] = str(base / "data")
        try:
            yield Store(), root
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def activate(store: Store, root: Path, session_id: str = "eval") -> dict:
    project = store.activate(root)
    store.register_session(project["id"], "codex", session_id)
    return project


def strict_record_schema() -> Result:
    with isolated_store() as (store, root):
        activate(store, root)
        rejected = 0
        for turn, payload in (
            ("missing", {"summary": "Missing operations"}),
            (
                "unknown",
                {"summary": "Malformed no-op", "operations": [], "op": "upsert", "node_id": "lost"},
            ),
            (
                "operation-typo",
                {"summary": "Operation typo", "operations": [
                    {"op": "upsert", "id": "lost", "title": "Lost", "titel": "Typo"}
                ]},
            ),
        ):
            try:
                store.record(root, "codex", "eval", turn, payload)
            except MindmapError:
                rejected += 1
        return Result(rejected == 3, f"rejected {rejected}/3 malformed payloads")


def same_interaction_steer() -> Result:
    with isolated_store() as (store, root):
        first = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(root),
            "session_id": "steer",
            "turn_id": "shared-turn",
            "prompt": "$mindmap:manage start",
        }
        handle_hook("codex", first, store)
        store.record(
            root,
            "codex",
            "steer",
            "shared-turn",
            {"summary": "Initial work", "operations": [
                {"op": "upsert", "id": "main-work", "title": "Build the main result"}
            ]},
        )
        second = dict(first, prompt="Also prepare the handoff")
        output = handle_hook("codex", second, store)
        reopened = not store.is_checkpointed("codex", "steer", "shared-turn")
        prompts = [entry["prompt"] for entry in store.turn_prompts("codex", "steer", "shared-turn")]
        store.record(
            root,
            "codex",
            "steer",
            "shared-turn",
            {"summary": "Added the handoff", "operations": [
                {
                    "op": "upsert",
                    "id": "handoff",
                    "title": "Prepare the handoff",
                    "parent_id": "main-work",
                }
            ]},
        )
        items = {item["id"] for item in store.project_view(store.find_project(root)["id"])["items"]}
        context = output["hookSpecificOutput"]["additionalContext"]
        passed = (
            reopened
            and prompts == ["$mindmap:manage start", "Also prepare the handoff"]
            and items == {"main-work", "handoff"}
            and "MINDMAP_CHECKPOINT_REOPENED_V1" in context
        )
        return Result(passed, f"prompts={len(prompts)}, reopened={reopened}, nodes={len(items)}")


def post_checkpoint_work() -> Result:
    with isolated_store() as (store, root):
        prompt = {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(root),
            "session_id": "late-work",
            "turn_id": "late-turn",
            "prompt": "$mindmap:manage start",
        }
        handle_hook("codex", prompt, store)
        store.record(root, "codex", "late-work", "late-turn", {"summary": "Early", "operations": []})
        with store.transaction() as connection:
            connection.execute(
                "UPDATE turns SET checkpointed_at = datetime('now', '-2 minutes')"
            )
        output = handle_hook(
            "codex",
            {
                "hook_event_name": "Stop",
                "cwd": str(root),
                "session_id": "late-work",
                "turn_id": "late-turn",
                "stop_hook_active": False,
                "last_assistant_message": (
                    "Implementation and verification finished after the checkpoint. "
                    "A new comparison explorer is now planned."
                ),
            },
            store,
        )
        blocked = bool(output and output.get("decision") == "block")
        return Result(blocked, f"Stop reconciliation requested={blocked}")


def fast_post_checkpoint_tool_work() -> Result:
    with isolated_store() as (store, root):
        prompt = {
            "hook_event_name": "UserPromptSubmit", "cwd": str(root),
            "session_id": "fast-work", "turn_id": "fast-turn",
            "prompt": "$mindmap:manage start",
        }
        handle_hook("codex", prompt, store)
        handle_hook("codex", {
            "hook_event_name": "PreToolUse", "cwd": str(root),
            "session_id": "fast-work", "turn_id": "fast-turn", "tool_name": "Bash",
        }, store)
        store.record(
            root, "codex", "fast-work", "fast-turn",
            {"summary": "Premature checkpoint", "operations": []},
        )
        handle_hook("codex", {
            "hook_event_name": "PreToolUse", "cwd": str(root),
            "session_id": "fast-work", "turn_id": "fast-turn", "tool_name": "apply_patch",
        }, store)
        output = handle_hook("codex", {
            "hook_event_name": "Stop", "cwd": str(root),
            "session_id": "fast-work", "turn_id": "fast-turn",
            "stop_hook_active": False,
            "last_assistant_message": "Finished within one second of checkpointing.",
        }, store)
        blocked = bool(output and output.get("decision") == "block")
        return Result(blocked, f"fast Stop reconciliation requested={blocked}")


def unbounded_semantic_growth() -> Result:
    with isolated_store() as (store, root):
        project = activate(store, root)
        store.record(
            root,
            "codex",
            "eval",
            "root",
            {"summary": "Root", "operations": [
                {"op": "upsert", "id": "root", "title": "Governing goal"}
            ]},
        )
        for batch, start in enumerate((0, 20)):
            count = 20 if start == 0 else 10
            store.record(
                root,
                "codex",
                "eval",
                f"batch-{batch}",
                {"summary": "Distinct branches", "operations": [
                    {
                        "op": "upsert",
                        "id": f"branch-{index}",
                        "title": f"Meaningful branch {index}",
                        "parent_id": "root",
                    }
                    for index in range(start, start + count)
                ]},
            )
        count = len(store.project_view(project["id"])["items"])
        return Result(count == 31, f"stored {count} connected concepts")


def settle_then_reopen() -> Result:
    with isolated_store() as (store, root):
        project = activate(store, root)
        store.record(root, "codex", "eval", "create", {"summary": "Created", "operations": [
            {"op": "upsert", "id": "capture", "title": "Capture images", "state": "open"}
        ]})
        store.record(root, "codex", "eval", "settle", {"summary": "Worked", "operations": [
            {"op": "settle", "id": "capture", "expected_revision": 1}
        ]})
        store.record(root, "codex", "eval", "reopen", {"summary": "Failure found", "operations": [
            {"op": "upsert", "id": "capture", "state": "open", "expected_revision": 2}
        ]})
        item = store.project_view(project["id"])["items"][0]
        return Result(item["state"] == "open" and item["revision"] == 3, f"state={item['state']}, revision={item['revision']}")


def causal_parent_independence() -> Result:
    with isolated_store() as (store, root):
        project = activate(store, root)
        store.record(root, "codex", "eval", "tree", {"summary": "Causal tree", "operations": [
            {"op": "upsert", "id": "assessment", "title": "Complete assessment", "state": "settled"},
            {"op": "upsert", "id": "hardening", "title": "Optional hardening", "state": "open", "parent_id": "assessment"},
        ]})
        items = {item["id"]: item for item in store.project_view(project["id"])["items"]}
        context = store.context(root)
        passed = items["assessment"]["state"] == "settled" and items["hardening"]["state"] == "open" and "[hardening]" in context
        return Result(passed, "settled parent retained an open causal child")


def divergent_replay_safety() -> Result:
    with isolated_store() as (store, root):
        activate(store, root)
        store.record(root, "codex", "eval", "same", {"summary": "First", "operations": []})
        try:
            store.record(root, "codex", "eval", "same", {"summary": "Different", "operations": []})
        except MindmapError:
            return Result(True, "different payload rejected without a new prompt")
        return Result(False, "different payload was accepted")


def explicit_no_change() -> Result:
    with isolated_store() as (store, root):
        activate(store, root)
        result = store.record(root, "codex", "eval", "noop", {"summary": "No map change", "operations": []})
        return Result(bool(result["checkpointed"] and not result["changed"]), "explicit empty operations checkpoint accepted")


def stale_frontier_warnings() -> Result:
    with isolated_store() as (store, root):
        project = activate(store, root)
        store.record(root, "codex", "eval", "stale", {
            "summary": "Seeded stale frontier cases",
            "operations": [
                {
                    "op": "upsert", "id": "old-action", "title": "Old action",
                    "state": "settled", "resume": "Run the remaining migration.",
                },
                {
                    "op": "upsert", "id": "completed-open", "title": "Local install",
                    "state": "open", "summary": "The local install is complete and verified.",
                },
                {
                    "op": "upsert", "id": "conditional", "title": "Conditional review",
                    "state": "settled", "resume": "Reopen when evidence changes.",
                },
            ],
        })
        warnings = store.project_snapshot(project["id"])["semantic_warnings"]
        keys = {(warning["code"], warning["item_id"]) for warning in warnings}
        expected = {
            ("settled_action_resume", "old-action"),
            ("state_summary_contradiction", "completed-open"),
        }
        return Result(keys == expected, f"warnings={sorted(keys)}")


def claude_unattended_diagnostic() -> Result:
    with isolated_store() as (store, root):
        project = store.activate(root)
        handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(root),
            "session_id": "denied", "prompt_id": "first", "prompt": "Finish work",
        }, store)
        handle_hook("claude", {
            "hook_event_name": "PreToolUse", "cwd": str(root),
            "session_id": "denied", "tool_name": "Bash",
        }, store)
        handle_hook("claude", {
            "hook_event_name": "Stop", "cwd": str(root),
            "session_id": "denied", "prompt_id": "first", "stop_hook_active": True,
            "last_assistant_message": "Work completed, but record was denied.",
        }, store)
        output = handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(root),
            "session_id": "denied", "prompt_id": "second", "prompt": "Continue",
        }, store)
        context = output["hookSpecificOutput"]["additionalContext"]
        sessions = store.project_snapshot(project["id"])["sessions"]
        passed = (
            "MINDMAP_PRIOR_CHECKPOINT_MISSING_V1" in context
            and sessions[0]["unresolved_checkpoint_count"] == 1
        )
        return Result(passed, "missing prior checkpoint is visible and actionable")


EVALUATORS: dict[str, Callable[[], Result]] = {
    "strict-record-schema": strict_record_schema,
    "same-interaction-steer": same_interaction_steer,
    "post-checkpoint-work": post_checkpoint_work,
    "fast-post-checkpoint-tool-work": fast_post_checkpoint_tool_work,
    "unbounded-semantic-growth": unbounded_semantic_growth,
    "settle-then-reopen": settle_then_reopen,
    "causal-parent-independence": causal_parent_independence,
    "divergent-replay-safety": divergent_replay_safety,
    "explicit-no-change": explicit_no_change,
    "stale-frontier-warnings": stale_frontier_warnings,
    "claude-unattended-diagnostic": claude_unattended_diagnostic,
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Emit machine-readable results.")
    parser.add_argument("--require-targets", action="store_true", help="Fail unless every target passes.")
    args = parser.parse_args()
    fixture = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows = []
    for case in fixture["cases"]:
        result = EVALUATORS[case["id"]]()
        rows.append({**case, "candidate_passed": result.passed, "evidence": result.evidence})
    if args.json:
        print(json.dumps({"baseline": fixture["baseline"], "cases": rows}, indent=2))
    else:
        print("Mindmap reliability evaluation")
        print(f"Baseline: {fixture['baseline']['name']} ({fixture['baseline']['date']})")
        print("case\tbaseline\tcandidate\tevidence")
        for row in rows:
            baseline = "PASS" if row["baseline_passed"] else "FAIL"
            candidate = "PASS" if row["candidate_passed"] else "FAIL"
            print(f"{row['id']}\t{baseline}\t{candidate}\t{row['evidence']}")
        baseline_score = sum(case["baseline_passed"] for case in rows)
        candidate_score = sum(case["candidate_passed"] for case in rows)
        print(f"score\t{baseline_score}/{len(rows)}\t{candidate_score}/{len(rows)}")
    return 1 if args.require_targets and not all(row["candidate_passed"] for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
