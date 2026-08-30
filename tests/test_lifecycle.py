from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mindmap.lifecycle import explicit_action, handle_hook
from mindmap.store import Store


class LifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.root = self.home / "Dev" / "Tracked"
        self.root.mkdir(parents=True)
        (self.root / ".git").mkdir()
        os.environ["MINDMAP_HOME_DIR"] = str(self.home)
        os.environ["MINDMAP_DATA_DIR"] = str(self.base / "data")
        os.environ["MINDMAP_RUNNER"] = "/opt/mindmap/bin/mindmap"
        self.store = Store()

    def tearDown(self) -> None:
        for key in ("MINDMAP_HOME_DIR", "MINDMAP_DATA_DIR", "MINDMAP_RUNNER"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def codex_prompt(self, prompt: str, turn: str = "turn-1") -> dict:
        return {
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(self.root),
            "session_id": "codex-session",
            "turn_id": turn,
            "prompt": prompt,
        }

    def test_only_exact_plugin_or_skill_invocations_are_actions(self) -> None:
        self.assertEqual(explicit_action("$mindmap:manage start"), "start")
        self.assertEqual(explicit_action("$mindmap start"), "start")
        self.assertEqual(explicit_action("$MINDMAP STATUS"), "status")
        self.assertEqual(explicit_action("/mindmap:manage sync"), "sync")
        self.assertIsNone(explicit_action("Can you make a mind map?"))
        self.assertIsNone(explicit_action("Explain `$mindmap:manage stop` without running it."))
        self.assertIsNone(explicit_action("```\n/mindmap:manage sync\n```"))
        self.assertIsNone(explicit_action("$mindmap:manage start and then stop"))
        self.assertIsNone(explicit_action("$mindmap start and then stop"))

    def test_codex_skill_default_is_an_executable_exact_action(self) -> None:
        config = (
            Path(__file__).resolve().parents[1]
            / "core" / "skills" / "mindmap" / "agents" / "openai.yaml"
        ).read_text()
        default_line = next(line for line in config.splitlines() if "default_prompt:" in line)
        default_prompt = default_line.split(":", 1)[1].strip().strip('"')
        self.assertEqual(explicit_action(default_prompt), "start")

    def test_start_mid_session_activates_and_injects_exact_identity(self) -> None:
        output = handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVE_V1", context)
        self.assertIn("codex-session / turn-1", context)
        self.assertIn("/dev/tracked", context)
        self.assertIn("Scope: this entire project directory", context)
        self.assertIn('"restore":true', context)
        self.assertIn('send "resume":"" explicitly', context)
        self.assertIn("Do not add a child that only restates the symptom", context)
        self.assertIn("preserve a distinct side quest", context)
        self.assertIn("USER-DELETED BRANCHES", context)
        self.assertNotIn("http://", context)
        self.assertIsNotNone(self.store.find_project(self.root, active_only=True))

    def test_start_from_unusable_session_cwd_blocks_child_project_workaround(self) -> None:
        output = handle_hook(
            "codex",
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.home),
                "session_id": "home-session",
                "turn_id": "home-start",
                "prompt": "$mindmap:manage start",
            },
            self.store,
        )

        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVATION_BLOCKED_V1", context)
        self.assertIn(str(self.home), context)
        self.assertIn("This session is not tracked", context)
        self.assertIn("Do not change directory", context)
        self.assertIn("different tool workdir", context)
        self.assertIn("guessed child project", context)
        self.assertIn("start a new agent session", context)
        self.assertIn("Do not claim", context)
        self.assertIsNone(self.store.find_project(self.home, active_only=True))
        self.assertIsNone(self.store.session("codex", "home-session"))

        # Replay the observed adversarial workaround: an agent ignores the block
        # and activates a child project from a command-specific workdir. The next
        # lifecycle hook still resolves the original session cwd and must not
        # attach that session or begin a turn in the child project.
        child = self.store.activate(self.root)
        inactive_status = handle_hook(
            "codex",
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.home),
                "session_id": "home-session",
                "turn_id": "home-status",
                "prompt": "$mindmap:manage status",
            },
            self.store,
        )
        inactive_context = inactive_status["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_INACTIVE_V1", inactive_context)
        self.assertIn("Any active child project", inactive_context)
        self.assertIn("Do not change directory", inactive_context)
        self.assertIn("different tool workdir", inactive_context)

        follow_up = handle_hook(
            "codex",
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(self.home),
                "session_id": "home-session",
                "turn_id": "home-follow-up",
                "prompt": "Continue the project work.",
            },
            self.store,
        )
        self.assertIsNone(follow_up)
        self.assertIsNone(self.store.session("codex", "home-session"))
        snapshot = self.store.project_snapshot(child["id"])
        self.assertEqual(snapshot["sessions"], [])
        self.assertEqual(snapshot["items"], [])

    def test_activation_collision_is_blocked_without_prescribing_a_directory_change(self) -> None:
        self.store.activate(self.root)
        colliding_root = self.home / "dev" / "tracked"
        colliding_root.mkdir(parents=True)
        (colliding_root / ".git").mkdir()

        output = handle_hook(
            "claude",
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(colliding_root),
                "session_id": "collision-session",
                "prompt_id": "collision-start",
                "prompt": "/mindmap:manage start",
            },
            self.store,
        )

        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVATION_BLOCKED_V1", context)
        self.assertIn("already owned", context)
        self.assertIn("Resolve the reported validation error", context)
        self.assertIsNone(self.store.session("claude", "collision-session"))

    def test_fresh_session_continues_the_matching_frontier_parent(self) -> None:
        fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "frontier-handoff.json").read_text()
        )
        project = self.store.activate(self.root)
        self.store.register_session(project["id"], "codex", "seed-session")
        self.store.record(
            self.root,
            "codex",
            "seed-session",
            "seed-turn",
            {
                "summary": "Seeded competing frontier branches.",
                "operations": fixture["nodes"],
            },
        )

        output = handle_hook(
            "codex",
            {
                "hook_event_name": "SessionStart",
                "cwd": str(self.root),
                "session_id": "fresh-session",
            },
            self.store,
        )
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("FRONTIER:", context)
        self.assertIn(
            "[delivery-reliability] Improve webhook delivery reliability (open)",
            context,
        )
        self.assertIn(
            "Resume: Continue by choosing and documenting a concrete retry policy.",
            context,
        )
        self.assertIn("parent it to the frontier it grew from", context)
        self.assertIn("not to the root merely because this is a new session", context)

        self.store.record(
            self.root,
            "codex",
            "fresh-session",
            "continued-turn",
            {
                "summary": "Continued the reliability frontier with its retry decision.",
                "operations": [
                    {
                        "op": "upsert",
                        "id": "retry-policy",
                        "title": "Use exponential retry backoff with jitter",
                        "summary": "A new decision produced while continuing delivery reliability.",
                        "state": "settled",
                        "kind": "decision",
                        "parent_id": fixture["target_id"],
                    }
                ],
            },
        )
        items = {
            item["id"]: item
            for item in self.store.project_snapshot(project["id"])["items"]
        }
        self.assertEqual(items["retry-policy"]["parent_id"], fixture["target_id"])
        self.assertNotEqual(items["retry-policy"]["parent_id"], fixture["decoy_id"])

    def test_codex_plugin_shorthand_starts_mid_session(self) -> None:
        output = handle_hook("codex", self.codex_prompt("$mindmap start"), self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVE_V1", context)
        self.assertIn("activation happened mid-session", context)
        self.assertIsNotNone(self.store.find_project(self.root, active_only=True))

    def test_repeated_start_is_treated_as_sync(self) -> None:
        self.store.activate(self.root)
        output = handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("RUN the transcript command and reconcile", context)
        self.assertNotIn("activation happened mid-session", context)

    def test_legacy_project_forces_causal_tree_reconciliation(self) -> None:
        project = self.store.activate(self.root)
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET concept_model_version = 1 WHERE id = ?", (project["id"],)
            )
        output = handle_hook("codex", self.codex_prompt("Continue the work"), self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("LEGACY_MAP_RECONCILIATION_REQUIRED_V2", context)
        self.assertIn("RUN both the transcript and snapshot commands", context)
        self.assertIn('"concept_model":"causal-tree-v2"', context)

    def test_missing_checkpoint_gets_one_recovery_pass(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        stop = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "session_id": "codex-session",
            "turn_id": "turn-1",
            "stop_hook_active": False,
            "last_assistant_message": "Done",
        }
        blocked = handle_hook("codex", stop, self.store)
        self.assertEqual(blocked["decision"], "block")
        stop["stop_hook_active"] = True
        stop["last_assistant_message"] = "Recovered and checkpointed nothing."
        self.assertIsNone(handle_hook("codex", stop, self.store))
        self.assertEqual(
            self.store.turn("codex", "codex-session", "turn-1")["last_assistant_message"],
            "Recovered and checkpointed nothing.",
        )

    def test_claude_unattended_record_denial_is_visible_on_next_prompt(self) -> None:
        self.store.activate(self.root)
        first_prompt = {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "claude-denied", "prompt_id": "prompt-1",
            "prompt": "Finish the implementation",
        }
        handle_hook("claude", first_prompt, self.store)
        handle_hook("claude", {
            "hook_event_name": "PreToolUse", "cwd": str(self.root),
            "session_id": "claude-denied", "tool_name": "Bash",
        }, self.store)
        stop = {
            "hook_event_name": "Stop", "cwd": str(self.root),
            "session_id": "claude-denied", "prompt_id": "prompt-1",
            "stop_hook_active": False,
            "last_assistant_message": "Implementation is complete, but record was denied.",
        }
        self.assertEqual(handle_hook("claude", stop, self.store)["decision"], "block")
        stop["stop_hook_active"] = True
        self.assertIsNone(handle_hook("claude", stop, self.store))

        next_prompt = handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "claude-denied", "prompt_id": "prompt-2",
            "prompt": "Continue",
        }, self.store)
        context = next_prompt["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_PRIOR_CHECKPOINT_MISSING_V1", context)
        self.assertIn("prompt-1", context)
        self.assertIn("last observed tool was Bash", context)
        self.assertIn("permitted", context)
        project = self.store.find_project(self.root)
        session = self.store.project_snapshot(project["id"])["sessions"][0]
        self.assertEqual(session["unresolved_checkpoint_count"], 1)

        self.store.record(
            self.root, "claude", "claude-denied", "prompt-2",
            {"summary": "Reconciled the denied checkpoint", "operations": []},
        )
        final_prompt = handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "claude-denied", "prompt_id": "prompt-3",
            "prompt": "One more turn",
        }, self.store)
        self.assertNotIn(
            "MINDMAP_PRIOR_CHECKPOINT_MISSING_V1",
            final_prompt["hookSpecificOutput"]["additionalContext"],
        )
        session = self.store.project_snapshot(project["id"])["sessions"][0]
        self.assertEqual(session["unresolved_checkpoint_count"], 0)

    def test_checkpoint_allows_stop_and_captures_last_message(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        self.store.record(
            self.root,
            "codex",
            "codex-session",
            "turn-1",
            {"summary": "Initial map", "operations": []},
        )
        output = handle_hook(
            "codex",
            {
                "hook_event_name": "Stop",
                "cwd": str(self.root),
                "session_id": "codex-session",
                "turn_id": "turn-1",
                "stop_hook_active": False,
                "last_assistant_message": "Initial map is ready.",
            },
            self.store,
        )
        self.assertIsNone(output)
        self.assertIn(
            "Initial map is ready",
            self.store.turn("codex", "codex-session", "turn-1")["last_assistant_message"],
        )

    def test_record_tool_activity_is_included_in_checkpoint_generation(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        self.assertIsNone(handle_hook("codex", {
            "hook_event_name": "PreToolUse", "cwd": str(self.root),
            "session_id": "codex-session", "turn_id": "turn-1",
            "tool_name": "Bash",
        }, self.store))
        self.store.record(
            self.root, "codex", "codex-session", "turn-1",
            {"summary": "Record was the final tool", "operations": []},
        )
        turn = self.store.turn("codex", "codex-session", "turn-1")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["checkpoint_tool_activity_generation"], 1)
        self.assertIsNone(handle_hook("codex", {
            "hook_event_name": "Stop", "cwd": str(self.root),
            "session_id": "codex-session", "turn_id": "turn-1",
            "stop_hook_active": False, "last_assistant_message": "Done.",
        }, self.store))

    def test_fast_post_checkpoint_tool_activity_reopens_codex_turn(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        handle_hook("codex", {
            "hook_event_name": "PreToolUse", "cwd": str(self.root),
            "session_id": "codex-session", "turn_id": "turn-1",
            "tool_name": "Bash",
        }, self.store)
        self.store.record(
            self.root, "codex", "codex-session", "turn-1",
            {"summary": "Checkpointed early", "operations": []},
        )
        handle_hook("codex", {
            "hook_event_name": "PreToolUse", "cwd": str(self.root),
            "session_id": "codex-session", "turn_id": "turn-1",
            "tool_name": "apply_patch",
        }, self.store)
        blocked = handle_hook("codex", {
            "hook_event_name": "Stop", "cwd": str(self.root),
            "session_id": "codex-session", "turn_id": "turn-1",
            "stop_hook_active": False,
            "last_assistant_message": "Finished immediately after checkpointing.",
        }, self.store)
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("apply_patch", blocked["reason"])
        self.assertIn("generation 1 -> 2", blocked["reason"])
        self.assertFalse(self.store.is_checkpointed("codex", "codex-session", "turn-1"))

    def test_claude_pre_tool_use_resolves_latest_turn_without_prompt_id(self) -> None:
        self.store.activate(self.root)
        handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "claude-session", "prompt_id": "prompt-1",
            "prompt": "Implement the fix",
        }, self.store)
        handle_hook("claude", {
            "hook_event_name": "PreToolUse", "cwd": str(self.root),
            "session_id": "claude-session", "tool_name": "Bash",
        }, self.store)
        turn = self.store.turn("claude", "claude-session", "prompt-1")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["last_tool_name"], "Bash")

    def test_same_interaction_steer_reopens_checkpoint_and_explains_delta(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        self.store.record(
            self.root,
            "codex",
            "codex-session",
            "turn-1",
            {"summary": "Initial branch", "operations": [{
                "op": "upsert", "id": "initial", "title": "Initial branch",
            }]},
        )
        output = handle_hook(
            "codex",
            self.codex_prompt("Also capture the handoff", turn="turn-1"),
            self.store,
        )
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_CHECKPOINT_REOPENED_V1", context)
        self.assertIn("record only the additional or corrective semantic changes", context)
        self.assertFalse(self.store.is_checkpointed("codex", "codex-session", "turn-1"))
        self.assertEqual(
            [entry["prompt"] for entry in self.store.turn_prompts(
                "codex", "codex-session", "turn-1"
            )],
            ["$mindmap:manage start", "Also capture the handoff"],
        )

    def test_long_post_checkpoint_window_gets_one_reconciliation_pass(self) -> None:
        handle_hook("codex", self.codex_prompt("$mindmap:manage start"), self.store)
        self.store.record(
            self.root,
            "codex",
            "codex-session",
            "turn-1",
            {"summary": "Checkpointed too early", "operations": []},
        )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE turns SET checkpointed_at = datetime('now', '-2 minutes')"
            )
        stop = {
            "hook_event_name": "Stop",
            "cwd": str(self.root),
            "session_id": "codex-session",
            "turn_id": "turn-1",
            "stop_hook_active": False,
            "last_assistant_message": "Substantive implementation finished after the checkpoint.",
        }
        blocked = handle_hook("codex", stop, self.store)
        self.assertEqual(blocked["decision"], "block")
        self.assertIn("long post-checkpoint work", blocked["reason"])
        self.assertFalse(self.store.is_checkpointed("codex", "codex-session", "turn-1"))
        self.store.record(
            self.root,
            "codex",
            "codex-session",
            "turn-1",
            {"summary": "Reconciled the completed work", "operations": []},
        )
        stop["stop_hook_active"] = True
        self.assertIsNone(handle_hook("codex", stop, self.store))

    def test_explicit_stop_deactivates_after_final_checkpoint(self) -> None:
        self.store.activate(self.root)
        handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "claude-session", "prompt_id": "prompt-1",
            "prompt": "/mindmap:manage stop"
        }, self.store)
        self.store.record(
            self.root, "claude", "claude-session", "prompt-1",
            {"summary": "Final sync", "operations": []}
        )
        handle_hook("claude", {
            "hook_event_name": "Stop", "cwd": str(self.root),
            "session_id": "claude-session", "prompt_id": "prompt-1",
            "stop_hook_active": False, "last_assistant_message": "Stopped."
        }, self.store)
        self.assertIsNone(self.store.find_project(self.root, active_only=True))
        self.assertEqual(
            self.store.turn("claude", "claude-session", "prompt-1")["last_assistant_message"],
            "Stopped.",
        )

    def test_missing_turn_identity_never_collapses_prompts(self) -> None:
        self.store.activate(self.root)
        prompt = {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "old-claude", "prompt": "ordinary work"
        }
        first = handle_hook("claude", prompt, self.store)
        second = handle_hook("claude", prompt, self.store)
        self.assertIn("MINDMAP_IDENTITY_UNAVAILABLE_V1", first["hookSpecificOutput"]["additionalContext"])
        self.assertIn("MINDMAP_IDENTITY_UNAVAILABLE_V1", second["hookSpecificOutput"]["additionalContext"])
        session = self.store.session("claude", "old-claude")
        with self.store.read_connection() as connection:
            turn_count = connection.execute(
                "SELECT count(*) FROM turns WHERE session_pk = ?", (session["id"],)
            ).fetchone()[0]
        self.assertEqual(turn_count, 0)

    def test_status_reads_retained_map_without_reactivating(self) -> None:
        project = self.store.activate(self.root)
        self.store.register_session(project["id"], "codex", "old-session")
        self.store.record(
            self.root, "codex", "old-session", "old-turn",
            {"summary": "Retained", "operations": [{"op": "upsert", "id": "kept", "title": "Kept work", "state": "planned"}]},
        )
        self.store.deactivate(self.root)
        output = handle_hook("codex", self.codex_prompt("$mindmap:manage status"), self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_RETAINED_READ_ONLY_V1", context)
        self.assertIn("Kept work", context)
        self.assertIsNone(self.store.find_project(self.root, active_only=True))
        self.assertIsNone(self.store.session("codex", "codex-session"))

    def test_compaction_events_are_side_effect_only_and_do_not_reopen_session(self) -> None:
        project = self.store.activate(self.root)
        self.store.register_session(project["id"], "codex", "compact", reopen=True)
        self.store.end_session("codex", "compact")
        output = handle_hook("codex", {
            "hook_event_name": "PostCompact", "cwd": str(self.root),
            "session_id": "compact", "turn_id": "turn-compact"
        }, self.store)
        self.assertIsNone(output)
        self.assertIsNotNone(self.store.session("codex", "compact")["ended_at"])

    def test_first_inactive_hook_does_not_create_storage(self) -> None:
        isolated_data = self.base / "never-used"
        previous = os.environ["MINDMAP_DATA_DIR"]
        os.environ["MINDMAP_DATA_DIR"] = str(isolated_data)
        try:
            output = handle_hook("codex", {
                "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
                "session_id": "ordinary", "turn_id": "ordinary-turn",
                "prompt": "Do ordinary work without Mindmap."
            })
            self.assertIsNone(output)
            self.assertFalse(isolated_data.exists())
        finally:
            os.environ["MINDMAP_DATA_DIR"] = previous

    def test_malformed_transcript_warns_without_disabling_active_context(self) -> None:
        self.store.activate(self.root)
        transcript = self.base / "corrupt.jsonl"
        transcript.write_text("not-json\n")
        output = handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "corrupt", "prompt_id": "corrupt-prompt",
            "prompt": "Continue work", "transcript_path": str(transcript),
        }, self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVE_V1", context)
        self.assertIn("Transcript import warning", context)
        self.assertIn("backfill", context)

    def test_transcript_os_error_warns_without_disabling_active_context(self) -> None:
        self.store.activate(self.root)
        with patch.object(self.store, "import_transcript", side_effect=PermissionError("denied")):
            output = handle_hook("claude", {
                "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
                "session_id": "unreadable", "prompt_id": "unreadable-prompt",
                "prompt": "Continue work", "transcript_path": str(self.base / "denied.jsonl"),
            }, self.store)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("MINDMAP_ACTIVE_V1", context)
        self.assertIn("Transcript import warning: denied", context)

    def test_prompt_after_session_end_authoritatively_reopens_session(self) -> None:
        project = self.store.activate(self.root)
        self.store.register_session(project["id"], "claude", "resumed", reopen=True)
        self.store.end_session("claude", "resumed")
        output = handle_hook("claude", {
            "hook_event_name": "UserPromptSubmit", "cwd": str(self.root),
            "session_id": "resumed", "prompt_id": "after-end", "prompt": "More work",
        }, self.store)
        self.assertIn("MINDMAP_ACTIVE_V1", output["hookSpecificOutput"]["additionalContext"])
        self.assertIsNone(self.store.session("claude", "resumed")["ended_at"])
        self.store.record(
            self.root, "claude", "resumed", "after-end",
            {"summary": "Resumed safely", "operations": []},
        )


if __name__ == "__main__":
    unittest.main()
