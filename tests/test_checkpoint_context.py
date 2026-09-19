from __future__ import annotations

import copy
import json
import os
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from mindmap import store as validator
from mindmap.activity import note_pre_tool_activity
from mindmap.context import PROMPT_CONTEXT_BYTES, SESSION_CONTEXT_BYTES, STOP_CONTEXT_BYTES
from mindmap.errors import MindmapError
from mindmap.guidance import limits_line, record_limits
from mindmap.lifecycle import _active_context, _additional, handle_hook
from mindmap.store import Store

ROOT = Path(__file__).resolve().parents[1]


class CheckpointContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home"
        self.root = self.home / "synthetic"
        self.root.mkdir(parents=True)
        self.environment = patch.dict(os.environ, {
            "MINDMAP_HOME_DIR": str(self.home), "MINDMAP_DATA_DIR": str(self.base / "data"),
            "MINDMAP_RUNNER": "/opt/mindmap/bin/mindmap", "MINDMAP_TRACKING": "on",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.store = Store()
        self.project = self.store.activate(self.root)

    def hook(self, host="codex", event="UserPromptSubmit", session="session", turn="first", **extra):
        return handle_hook(host, {
            "cwd": str(self.root), "session_id": session, "turn_id": turn, "prompt_id": turn,
            "hook_event_name": event, "prompt": "Continue synthetic validation.",
            "stop_hook_active": False, **extra,
        }, self.store)

    def record(self, payload, host="codex", session="session", turn="first"):
        return self.store.record(self.root, host, session, turn, payload)

    def seed(self, host="codex", session="session", turn="first"):
        self.hook(host, session=session, turn=turn)
        payload = {"summary": "Initial concept", "operations": [
            {"op": "upsert", "id": "root", "title": "Synthetic project", "state": "open"},
        ]}
        self.record(payload, host, session, turn)
        return payload

    def work(self, host="codex", session="session", turn="first"):
        self.hook(host, "PreToolUse", session, turn, tool_name="apply_patch", tool_input={})

    def correction(self, revision=1):
        return {"summary": "Reconciled subsequent work", "operations": [
            {"op": "upsert", "id": "root", "expected_revision": revision, "resume": "Verify the remaining acceptance."},
        ]}

    def command(self, host="codex", session="session", turn="first"):
        return shlex.join(["/opt/mindmap/bin/mindmap", "record", "--root", str(self.root),
                           "--host", host, "--session-id", session, "--interaction-id", turn, "--file", "-"])

    def own_pretool(self, command, host="codex", fast=True, session="session", turn="first"):
        payload = {"cwd": str(self.root), "session_id": session, "turn_id": turn,
                   "hook_event_name": "PreToolUse", "tool_name": "Bash" if host == "claude" else "functions.exec_command",
                   "tool_input": {"command" if host == "claude" else "cmd": command}}
        if fast:
            note_pre_tool_activity(host, payload)
        else:
            handle_hook(host, payload, self.store)

    def test_correction_before_stop_and_repeated_attempts_cannot_create_authorization(self):
        for host, fast in (("codex", True), ("claude", False)):
            with self.subTest(host=host):
                session = host
                initial = self.seed(host, session)
                command = self.command(host, session)
                before = self.store.turn(host, session, "first")
                # Both literal attempts and opaque/compound attempts fail to
                # manufacture work, however many times the model retries.
                for suffix in ("", " ; true"):
                    for _ in range(4):
                        self.own_pretool(command + suffix, host, fast, session)
                        with self.assertRaisesRegex(MindmapError, "different payload"):
                            self.record(self.correction(), host, session)
                current = self.store.turn(host, session, "first")
                self.assertEqual(current["last_non_record_tool_generation"], before["tool_activity_generation"])
                self.assertEqual(self.store.project_snapshot(self.project["id"])["items"][0]["revision"], 1)
                self.work(host, session)
                self.own_pretool(command, host, fast, session)
                result = self.record(self.correction(), host, session)
                self.assertEqual(result["changed"], ["root"])
                self.assertIsNone(self.hook(host, "Stop", session))
                # A previous payload stays idempotent after a correction. It
                # cannot reapply its old revision or acknowledge later work.
                self.work(host, session)
                replay = self.record(initial, host, session)
                self.assertTrue(replay["idempotent_replay"])
                self.assertTrue(replay["post_checkpoint_work_pending"])
                self.assertEqual(self.store.project_snapshot(self.project["id"])["items"][0]["revision"], 2)
                self.assertEqual(self.hook(host, "Stop", session)["decision"], "block")
                # Reset only this synthetic graph for the second host.
                with self.store.transaction() as connection:
                    connection.execute("DELETE FROM items")

    def test_exact_retry_after_real_work_does_not_reconcile_it(self):
        initial = self.seed()
        self.work()
        self.own_pretool(self.command())
        result = self.record(initial)
        self.assertTrue(result["post_checkpoint_work_pending"])
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["checkpoint_tool_activity_generation"], 0)
        self.assertEqual(turn["tool_activity_generation"], 2)
        self.assertEqual(turn["last_effective_tool_generation"], 1)
        self.assertEqual(self.hook(event="Stop")["decision"], "block")

    def test_literal_heredoc_retry_is_neutral_but_compound_side_effects_are_not(self):
        initial = self.seed()
        command = self.command() + " <<'JSON'\n" + json.dumps(initial) + "\nJSON"
        self.own_pretool(command)
        self.assertTrue(self.record(initial)["idempotent_replay"])
        self.assertIsNone(self.hook(event="Stop"))
        self.own_pretool(command + "\nprintf '%s' changed")
        self.assertEqual(self.hook(event="Stop")["decision"], "block")

    def test_missing_executor_input_and_failed_payloads_remain_conservative(self):
        self.seed()
        for _ in range(5):
            self.hook(event="PreToolUse", tool_name="Bash")
            with self.assertRaisesRegex(MindmapError, "different payload"):
                self.record(self.correction())
        self.work()
        too_long = self.correction()
        too_long["summary"] = "x" * (validator.MAX_CHECKPOINT_SUMMARY_LENGTH + 1)
        for _ in range(3):
            self.own_pretool(self.command())
            with self.assertRaisesRegex(MindmapError, "Checkpoint summary"):
                self.record(too_long)
        self.record(self.correction())
        self.assertIsNone(self.hook(event="Stop"))

    def test_concurrent_revision_is_protected_and_failed_delta_keeps_checkpoint(self):
        self.seed()
        self.work()
        self.record(self.correction(), session="other", turn="other")
        before = self.store.turn("codex", "session", "first")
        with self.assertRaisesRegex(MindmapError, "changed concurrently"):
            self.record(self.correction())
        self.assertEqual(self.store.turn("codex", "session", "first"), before)
        self.record(self.correction(2))
        self.assertIsNone(self.hook(event="Stop"))

    def test_activity_waiting_for_record_lock_is_not_swallowed_by_checkpoint(self):
        self.seed()
        self.work()
        entered, release, activity_started = threading.Event(), threading.Event(), threading.Event()
        original = self.store._assert_valid_graph

        def hold(connection, project_id):
            original(connection, project_id)
            entered.set()
            self.assertTrue(release.wait(5))

        def activity():
            activity_started.set()
            note_pre_tool_activity("codex", {"cwd": str(self.root), "session_id": "session", "turn_id": "first", "tool_name": "apply_patch"})

        with patch.object(self.store, "_assert_valid_graph", hold), ThreadPoolExecutor(max_workers=2) as pool:
            record = pool.submit(self.record, self.correction())
            try:
                self.assertTrue(entered.wait(5))
                tool = pool.submit(activity)
                self.assertTrue(activity_started.wait(5))
            finally:
                release.set()
            record.result(timeout=5)
            tool.result(timeout=5)
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["tool_activity_generation"], turn["checkpoint_tool_activity_generation"] + 1)
        self.assertEqual(self.hook(event="Stop")["decision"], "block")

    def test_stop_cannot_invalidate_a_new_correction_using_its_old_snapshot(self):
        self.seed()
        self.work()
        original = self.store.invalidate_checkpoint

        def interleaved(*args, **kwargs):
            self.record(self.correction())
            return original(*args, **kwargs)

        with patch.object(self.store, "invalidate_checkpoint", interleaved):
            self.assertIsNone(self.hook(event="Stop"))
        self.assertTrue(self.store.is_checkpointed("codex", "session", "first"))
        self.assertEqual(self.store.project_snapshot(self.project["id"])["items"][0]["revision"], 2)

    def test_replay_after_stop_or_new_prompt_keeps_reopened_turn_uncheckpointed(self):
        initial = self.seed()
        self.work()
        self.assertEqual(self.hook(event="Stop")["decision"], "block")
        with self.assertRaisesRegex(MindmapError, "already committed.*new truthful summary"):
            self.record(initial)
        self.assertFalse(self.store.is_checkpointed("codex", "session", "first"))
        self.record(self.correction())
        self.hook(prompt="Also verify the separate acceptance.")
        with self.assertRaisesRegex(MindmapError, "already committed.*new truthful summary"):
            self.record(self.correction())
        self.assertFalse(self.store.is_checkpointed("codex", "session", "first"))
        self.assertEqual(self.store.project_snapshot(self.project["id"])["items"][0]["revision"], 2)

    def test_own_pretool_advances_raw_counter_only(self):
        self.seed()
        self.own_pretool(self.command())
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["last_effective_tool_generation"], 0)
        self.assertEqual(turn["last_non_record_tool_generation"], 0)
        self.assertIsNone(self.hook(event="Stop"))

    def test_old_schema_fast_hook_migrates_without_inventing_work_permission(self):
        self.seed()
        with self.store.transaction() as connection:
            connection.execute("ALTER TABLE turns DROP COLUMN last_non_record_tool_generation")
            connection.execute("ALTER TABLE turns DROP COLUMN last_effective_tool_generation")
            connection.execute("ALTER TABLE turns DROP COLUMN classified_tool_activity_generation")
        # Models may already be using the new hook while the DB still has the
        # previous schema. Their activity must remain visible after migration.
        self.own_pretool(self.command())
        self.store = Store()
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["last_effective_tool_generation"], 1)
        self.assertEqual(turn["last_non_record_tool_generation"], 0)
        with self.assertRaisesRegex(MindmapError, "different payload"):
            self.record(self.correction())
        self.work()
        self.record(self.correction())
        self.assertIsNone(self.hook(event="Stop"))

    def test_previous_version_writer_remains_visible_before_and_after_own_pretool(self):
        initial = self.seed()
        with self.store.transaction() as connection:
            connection.execute("UPDATE turns SET tool_activity_generation=tool_activity_generation+1")
        self.assertTrue(self.record(initial)["post_checkpoint_work_pending"])
        self.own_pretool(self.command())
        self.assertTrue(self.record(initial)["post_checkpoint_work_pending"])
        with self.assertRaisesRegex(MindmapError, "different payload"):
            self.record(self.correction())
        self.assertEqual(self.hook(event="Stop")["decision"], "block")

    def test_two_concurrent_corrective_records_have_one_revision_winner(self):
        self.seed()
        self.work()
        barrier = threading.Barrier(2)
        def record(session):
            barrier.wait(timeout=5)
            try:
                return self.record(self.correction(), session=session)
            except MindmapError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(record, ("session", "other")))
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("changed concurrently", next(result for result in results if isinstance(result, str)))
        self.assertEqual(self.store.project_snapshot(self.project["id"])["items"][0]["revision"], 2)

    def test_record_waits_for_activity_transaction_and_captures_it(self):
        self.seed()
        started = threading.Event()
        def record():
            started.set()
            return self.record(self.correction())
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.store.transaction() as connection:
                connection.execute("UPDATE turns SET tool_activity_generation=1, last_non_record_tool_generation=1, last_effective_tool_generation=1")
                future = pool.submit(record)
                self.assertTrue(started.wait(5))
            self.assertEqual(future.result(timeout=5)["changed"], ["root"])
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["checkpoint_tool_activity_generation"], 1)
        self.assertIsNone(self.hook(event="Stop"))

    def test_heredoc_early_delimiter_and_wrong_runner_are_not_finality_neutral(self):
        self.seed()
        for command in (self.command() + " <<'JSON'\n{}\nJSON\nprintf changed\nJSON",
                        self.command().replace("/opt/mindmap/bin/mindmap", "/other/mindmap")):
            self.own_pretool(command)
        turn = self.store.turn("codex", "session", "first")
        self.assertEqual(turn["last_effective_tool_generation"], 2)
        self.assertEqual(turn["last_non_record_tool_generation"], 0)
        with self.assertRaisesRegex(MindmapError, "different payload"):
            self.record(self.correction())

    def test_large_diagnostics_never_displace_partial_map_or_causal_rules(self):
        self.large_graph()
        session, turn = "会" * 3000, "番" * 3000
        self.hook(session=session, turn=turn)
        context = _active_context(self.store, self.project, "codex", session, turn, "sync",
                                  notices=["Synthetic diagnostic " + "界" * 4000])
        output = _additional("UserPromptSubmit", context)
        self.assertLessEqual(len(json.dumps(output, ensure_ascii=False).encode()), PROMPT_CONTEXT_BYTES)
        self.assertIn("omitted", context)
        self.assertIn("snapshot", context)
        self.assertIn("A planned concept has started", context)
        self.assertIn("handoff, delegated step, or prerequisite finished elsewhere", context)
        self.assertIn("Additional diagnostic text omitted", context)
        self.assertIn("PARTIAL", context)

    def test_checkpoint_summary_and_id_unicode_boundaries(self):
        payload = {"summary": "界" * validator.MAX_CHECKPOINT_SUMMARY_LENGTH, "operations": [
            {"op": "upsert", "id": "界" * validator.MAX_ITEM_ID_LENGTH, "title": "Boundary"},
        ]}
        self.record(payload)
        for field in ("summary", "id"):
            invalid = copy.deepcopy(payload)
            if field == "summary":
                invalid["summary"] += "界"
            else:
                invalid["operations"][0]["id"] += "界"
            with self.assertRaisesRegex(MindmapError, "characters or shorter"):
                self.record(invalid, turn=field)

    def large_graph(self):
        self.seed()
        for batch in range(5):
            self.record({"summary": "Synthetic graph growth", "operations": [
                {"op": "upsert", "id": f"concept-{batch*20+i}", "parent_id": "root", "title": f"Unicode validation {batch*20+i}",
                 "summary": "界🧠\\\n" * 200, "resume": "Continue verification. " + "界" * 500,
                 "state": "open" if i % 2 else "planned"} for i in range(20)
            ]}, session="seed", turn=f"batch-{batch}")

    def test_large_unicode_graph_and_long_identity_fit_wire_and_preview_budgets(self):
        self.large_graph()
        before = self.store.project_snapshot(self.project["id"])["items"]
        for host in ("codex", "claude"):
            for session, turn in (("normal", "normal"), ("会" * 3000, "番" * 3000)):
                with self.subTest(host=host, long=len(session)>20):
                    output = self.hook(host, session=session, turn=turn)
                    context = output["hookSpecificOutput"]["additionalContext"]
                    wire = json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()
                    self.assertLessEqual(len(wire), PROMPT_CONTEXT_BYTES)
                    preview = wire[:2048].decode(errors="ignore")
                    for required in (" record ", "operations", "expected_revision", "100000", "checkpoint summary 500", "concept summary 1200"):
                        self.assertIn(required, preview)
                    self.assertIn("omitted:", context)
                    self.assertIn("not a complete tree", context)
                    self.assertIn("snapshot", context)
                    self.assertIn("schema", context)
                    self.assertIn("A planned concept has started once a child beneath it records work", context)
                    self.assertIn("do not settle broader outcomes", context)
                    self.assertIn("handoff, delegated step, or prerequisite finished elsewhere", context)
                    self.assertIn("preserve a distinct side quest", context)
                    if len(session)>20:
                        self.assertIn("--turn-ref", preview)
                        ref = self.store.turn(host, session, turn)["id"]
                        self.assertEqual(self.store.checkpoint_identity(ref)["session_id"], session)
                    stop = self.hook(host, "Stop", session, turn)
                    self.assertLessEqual(len(json.dumps(stop, ensure_ascii=False).encode()), STOP_CONTEXT_BYTES)
                    stop_preview = json.dumps(stop, ensure_ascii=False).encode()[:2048].decode(errors="ignore")
                    for required in (" record ", "operations", "expected_revision", "100000"):
                        self.assertIn(required, stop_preview)
                    self.assertNotIn("Unicode validation", stop["reason"])
                    start = self.hook(host, "SessionStart", session, turn)
                    self.assertLessEqual(len(json.dumps(start, ensure_ascii=False).encode()), SESSION_CONTEXT_BYTES)
        self.assertEqual(self.store.project_snapshot(self.project["id"])["items"], before)
        self.assertEqual(len(before), 101)

    def test_guidance_follows_validator_constants_without_relaxing_validation(self):
        names = ["MAX_CHECKPOINT_SUMMARY_LENGTH", "MAX_TITLE_LENGTH", "MAX_ITEM_SUMMARY_LENGTH", "MAX_RESUME_LENGTH",
                 "MAX_NEW_ITEMS_PER_RECORD", "MAX_ROOT_ITEMS", "MAX_TREE_DEPTH", "MAX_RECORD_PAYLOAD_BYTES", "MAX_ITEM_ID_LENGTH"]
        for number, name in enumerate(names, 321):
            with self.subTest(name=name), patch.object(validator, name, number):
                self.assertIn(str(number), limits_line())
                self.assertIn(number, record_limits().values())
                self.assertIn(str(number), self.hook()["hookSpecificOutput"]["additionalContext"])
        for field, limit in (("title", validator.MAX_TITLE_LENGTH), ("summary", validator.MAX_ITEM_SUMMARY_LENGTH), ("resume", validator.MAX_RESUME_LENGTH)):
            payload = {"summary": "Boundary", "operations": [{"op": "upsert", "id": "boundary", "title": "Boundary", field: "界" * limit}]}
            self.record(payload, turn=field)
            too_long = copy.deepcopy(payload)
            too_long["operations"][0][field] += "界"
            with self.assertRaisesRegex(MindmapError, "characters or shorter"):
                self.record(too_long, turn=field + "-long")
            with self.store.transaction() as connection:
                connection.execute("DELETE FROM items")

    def test_canonical_utf8_payload_exact_byte_boundary(self):
        self.seed()
        payload = {"summary": "Boundary", "operations": [
            {"op": "upsert", "id": f"unicode-{i}", "title": "Unicode", "parent_id": "root", "summary": "🧠" * 1200, "resume": ""}
            for i in range(20)
        ]}
        def size():
            return len(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        remaining = validator.MAX_RECORD_PAYLOAD_BYTES - size()
        self.assertGreater(remaining, 0)
        for item in payload["operations"]:
            added = min(remaining, validator.MAX_RESUME_LENGTH)
            item["resume"] = "x" * added
            remaining -= added
        self.assertEqual(remaining, 0)
        self.assertEqual(size(), validator.MAX_RECORD_PAYLOAD_BYTES)
        self.record(payload, turn="boundary")
        payload["operations"][-1]["resume"] += "x"
        with self.assertRaisesRegex(MindmapError, "bytes or smaller"):
            self.record(payload, turn="over-boundary")

    def test_supported_hosts_use_bash_command_string_for_pretool(self):
        # Codex 0.155 normalizes exec_command.cmd to Bash/command at its hook
        # boundary; Claude passes Bash's command object. Native call-log tool
        # names are not evidence of the hook-facing name.
        for host in ("codex", "claude"):
            self.hook(host, session=host)
            first = {"summary": "No map change", "operations": []}
            self.record(first, host, host)
            payload = {"cwd": str(self.root), "session_id": host, "turn_id": "first",
                       "hook_event_name": "PreToolUse", "tool_name": "Bash",
                       "tool_input": {"command": self.command(host, host)}}
            for _ in range(3):
                note_pre_tool_activity(host, payload)
                with self.assertRaisesRegex(MindmapError, "different payload"):
                    self.record({"summary": "Conflicting attempt", "operations": []}, host, host)
            self.assertIsNone(self.hook(host, "Stop", host))
            # The supported ordinary shell string establishes intervening work.
            payload["tool_input"] = {"command": "git status --short"}
            note_pre_tool_activity(host, payload)
            self.record({"summary": "Reviewed subsequent work", "operations": []}, host, host)
            self.assertIsNone(self.hook(host, "Stop", host))
            # Unverified list-form shells stay conservative. They cannot
            # manufacture correction permission from repeated attempts.
            payload["tool_input"] = {"command": ["bash", "-lc", self.command(host, host)]}
            for _ in range(3):
                note_pre_tool_activity(host, payload)
                with self.assertRaisesRegex(MindmapError, "different payload"):
                    self.record({"summary": "Another conflicting attempt", "operations": []}, host, host)

    def packaged_environment(self, **extra):
        return {"HOME": str(self.home), "PATH": os.defpath, "MINDMAP_PYTHON": sys.executable,
                "MINDMAP_HOME_DIR": str(self.home), "MINDMAP_DATA_DIR": str(self.base / "data"),
                "MINDMAP_TRACKING": "on", **extra}

    def packaged_hook(self, host, event, *, environment=None, **extra):
        package = ROOT / ("plugins/mindmap" if host == "codex" else "plugins/claude/mindmap")
        payload = {"cwd": str(self.root), "session_id": host, "turn_id": "current", "prompt_id": "current",
                   "hook_event_name": event, "prompt": "Continue verification.", "stop_hook_active": False, **extra}
        result = subprocess.run([str(package / "scripts/run_hook.sh"), "--host", host],
                                input=json.dumps(payload).encode("utf-8"), capture_output=True,
                                env=environment or self.packaged_environment(), timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(result.stderr, result.stderr)
        limit = STOP_CONTEXT_BYTES if event == "Stop" else PROMPT_CONTEXT_BYTES
        self.assertLessEqual(len(result.stdout), limit)
        return json.loads(result.stdout.decode("utf-8")) if result.stdout else None

    def test_packaged_cli_refuses_stale_empty_replay_after_stop_and_new_prompt(self):
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                self.packaged_hook(host, "UserPromptSubmit")
                ref = self.store.turn(host, host, "current")["id"]
                package = ROOT / ("plugins/mindmap" if host == "codex" else "plugins/claude/mindmap")
                payload = {"summary": "No map change", "operations": []}
                def record(value):
                    return subprocess.run([str(package / "bin/mindmap"), "record", "--turn-ref", str(ref)],
                                          input=json.dumps(value).encode(), capture_output=True,
                                          env=self.packaged_environment(), timeout=10)
                self.assertEqual(record(payload).returncode, 0)
                self.packaged_hook(host, "PreToolUse", tool_name="apply_patch", tool_input={})
                stop = self.packaged_hook(host, "Stop")
                self.assertEqual(stop["decision"], "block")
                self.assertIn("new truthful summary", stop["reason"])
                before = self.store.turn(host, host, "current")
                retry = record(payload)
                self.assertEqual(retry.returncode, 2)
                self.assertFalse(retry.stdout)
                self.assertIn(b"already committed", retry.stderr)
                self.assertIn(b"new truthful summary", retry.stderr)
                self.assertEqual(self.store.turn(host, host, "current"), before)
                payload = {"summary": "Reconciled later work; no map change", "operations": []}
                self.assertTrue(json.loads(record(payload).stdout)["checkpointed"])
                self.assertIsNone(self.packaged_hook(host, "Stop", stop_hook_active=True))
                self.packaged_hook(host, "UserPromptSubmit", prompt="Check one more acceptance.")
                retry = record(payload)
                self.assertEqual(retry.returncode, 2)
                self.assertFalse(self.store.is_checkpointed(host, host, "current"))
                self.assertIn("new truthful summary", self.packaged_hook(host, "Stop")["reason"])
                payload["summary"] = "Reviewed the added acceptance; no map change"
                self.assertTrue(json.loads(record(payload).stdout)["checkpointed"])
                self.assertIsNone(self.packaged_hook(host, "Stop", stop_hook_active=True))

    def warning_graph(self):
        self.seed()
        with patch("mindmap.store.utc_now", return_value="2025-01-01T00:00:00.000+00:00"):
            self.record({"summary": "Synthetic warning cases", "operations": [
                {"op": "upsert", "id": "root", "expected_revision": 1, "summary": "This project is superseded by a different approach."},
                {"op": "upsert", "id": "phase", "title": "Validate phase", "parent_id": "root", "state": "planned"},
                {"op": "upsert", "id": "closed", "title": "Completed deliverable", "parent_id": "root", "state": "settled", "resume": "Verify remaining work."},
                {"op": "upsert", "id": "contradiction", "title": "Acceptance", "parent_id": "root", "state": "open", "summary": "This work is complete."},
                {"op": "upsert", "id": "reopened", "title": "Reopened decision", "parent_id": "root", "state": "settled"},
            ]}, turn="warning-seed")
        with patch("mindmap.store.utc_now", return_value="2025-01-01T00:00:01.000+00:00"):
            self.record({"summary": "Later synthetic work", "operations": [
                {"op": "upsert", "id": "child", "title": "Started work", "state": "open", "parent_id": "phase"},
                {"op": "upsert", "id": "reopened", "expected_revision": 1, "state": "open"},
            ]}, turn="warning-later")

    def test_specific_warnings_survive_both_hooks_on_small_and_large_maps(self):
        self.warning_graph()
        expected = {(warning["code"], warning["item_id"]) for warning in self.store.project_snapshot(self.project["id"])["semantic_warnings"]}
        self.assertEqual({code for code, _ in expected}, {"planned_parent_after_child_activity", "settled_action_resume",
                                                       "state_summary_contradiction", "superseded_root_frontier", "reversion_without_context"})
        for large in (False, True):
            if large:
                for batch in range(6):
                    self.record({"summary": "Add unrelated settled context", "operations": [
                        {"op": "upsert", "id": f"settled-{batch}-{i}", "title": "Retained context", "parent_id": "root", "state": "settled", "summary": "界" * 1000}
                        for i in range(20)
                    ]}, turn=f"extra-{batch}")
            before = self.store.project_snapshot(self.project["id"])["items"]
            for host in ("codex", "claude"):
                for event in ("UserPromptSubmit", "SessionStart"):
                    context = self.packaged_hook(host, event)["hookSpecificOutput"]["additionalContext"]
                    actual = {tuple(json.loads(line.removeprefix("SEMANTIC WARNING: "))[key] for key in ("code", "item_id"))
                              for line in context.splitlines() if line.startswith("SEMANTIC WARNING: ")}
                    self.assertEqual(actual, expected)
                    self.assertIn("Warning details omitted: 0", context)
                    rows = [json.loads(line) for line in context.splitlines() if line.startswith('{"id":')]
                    self.assertTrue(rows)
                    self.assertIn(rows[0]["id"], {item_id for _, item_id in expected})
            self.assertEqual(self.store.project_snapshot(self.project["id"])["items"], before)

    def test_many_warnings_are_capped_and_omission_count_is_exact(self):
        self.seed()
        self.record({"summary": "Synthetic contradictions", "operations": [
            {"op": "upsert", "id": f"contradiction-{i}", "title": "Acceptance", "parent_id": "root", "state": "open", "summary": "This work is complete."}
            for i in range(20)
        ]}, turn="many-warnings")
        for host in ("codex", "claude"):
            context = self.packaged_hook(host, "UserPromptSubmit")["hookSpecificOutput"]["additionalContext"]
            self.assertEqual(context.count("SEMANTIC WARNING: "), 5)
            self.assertIn("Warnings shown: 5/20; Warning details omitted: 15", context)

    def test_packaged_hook_stdout_is_utf8_independent_of_locale(self):
        self.seed()
        self.record({"summary": "Unicode context", "operations": [
            {"op": "upsert", "id": "root", "expected_revision": 1, "title": "漢字 — 🚀", "summary": "x" * 400},
        ]}, turn="unicode")
        before = self.store.project_snapshot(self.project["id"])["items"]
        for host in ("codex", "claude"):
            for extra in ({"LC_ALL": "en_US.ISO8859-1", "LANG": "en_US.ISO8859-1"},
                          {"PYTHONIOENCODING": "cp1252"}, {"PYTHONIOENCODING": "ascii"}):
                with self.subTest(host=host, encoding=extra):
                    environment = self.packaged_environment(**extra)
                    for event in ("UserPromptSubmit", "SessionStart"):
                        output = self.packaged_hook(host, event, environment=environment)
                        context = output["hookSpecificOutput"]["additionalContext"]
                        self.assertIn("漢字 — 🚀", context)
                        self.assertIn("… [preview]", context)
                    stop = self.packaged_hook(host, "Stop", environment=environment)
                    self.assertEqual(stop["decision"], "block")
        self.assertEqual(self.store.project_snapshot(self.project["id"])["items"], before)

    def test_both_packaged_wrappers_preview_record_replay_correction_and_retrieval(self):
        self.large_graph()
        for host, relative in (("codex", "plugins/mindmap"), ("claude", "plugins/claude/mindmap")):
            package = ROOT / relative
            runner = str(package / "bin/mindmap")
            environment = {"HOME": str(self.home), "PATH": os.defpath, "MINDMAP_PYTHON": sys.executable,
                           "MINDMAP_HOME_DIR": str(self.home), "MINDMAP_DATA_DIR": str(self.base / "data"), "MINDMAP_TRACKING": "on"}
            session, turn = "会" * 1000 + host, "番" * 1000
            payload = {"cwd": str(self.root), "session_id": session, "turn_id": turn, "prompt_id": turn, "prompt": "Continue validation."}
            def hook(event, **extra):
                result = subprocess.run([str(package / "scripts/run_hook.sh"), "--host", host],
                                        input=json.dumps({**payload, "hook_event_name": event, **extra}),
                                        text=True, capture_output=True, env=environment, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(result.stderr, result.stderr)
                return result.stdout
            output = hook("UserPromptSubmit")
            self.assertLessEqual(len(output.encode()), PROMPT_CONTEXT_BYTES)
            self.assertIn("--turn-ref", output.encode()[:2048].decode(errors="ignore"))
            ref = self.store.turn(host, session, turn)["id"]
            command = shlex.join([runner, "record", "--turn-ref", str(ref), "--file", "-"])
            def record(value):
                shell = command + " <<'JSON'\n" + json.dumps(value) + "\nJSON"
                hook("PreToolUse", tool_name="Bash", tool_input={"command": shell})
                return subprocess.run(["/bin/sh", "-c", shell], capture_output=True, text=True, env=environment, timeout=10)
            first = {"summary": "No semantic changes", "operations": []}
            self.assertEqual(record(first).returncode, 0)
            for _ in range(3):
                self.assertEqual(record({"summary": "Conflicting repeat", "operations": []}).returncode, 2)
            self.assertEqual(record(first).returncode, 0)
            self.assertEqual(hook("Stop", stop_hook_active=False), "")
            hook("PreToolUse", tool_name="apply_patch", tool_input={})
            replay = record(first)
            self.assertTrue(json.loads(replay.stdout)["post_checkpoint_work_pending"])
            self.assertEqual(record({"summary": "Reviewed the later work; no map change", "operations": []}).returncode, 0)
            self.assertEqual(hook("Stop", stop_hook_active=False), "")
            for args in (("snapshot", "--turn-ref", str(ref)), ("identity", "--turn-ref", str(ref)), ("schema",)):
                result = subprocess.run([runner, *args], capture_output=True, text=True, env=environment, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                value = json.loads(result.stdout)
                if args[0] == "snapshot":
                    self.assertEqual(len(value["items"]), 101)
                elif args[0] == "identity":
                    self.assertEqual(value["session_id"], session)
                else:
                    self.assertEqual(value["limits"], record_limits())


if __name__ == "__main__":
    unittest.main()
