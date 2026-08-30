from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import json
import stat
from unittest.mock import patch

import mindmap.store as store_module
from pathlib import Path

from mindmap.errors import MindmapError, RouteCollisionError
from mindmap.store import Store


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home" / "Tester"
        self.home.mkdir(parents=True)
        os.environ["MINDMAP_HOME_DIR"] = str(self.home)
        os.environ["MINDMAP_DATA_DIR"] = str(self.base / "data")
        self.project_root = self.home / "Dev" / "ExampleProject"
        self.project_root.mkdir(parents=True)
        self.store = Store()

    def tearDown(self) -> None:
        os.environ.pop("MINDMAP_HOME_DIR", None)
        os.environ.pop("MINDMAP_DATA_DIR", None)
        self.temp.cleanup()

    def activate(self) -> dict:
        return self.store.activate(self.project_root)

    def test_package_disables_bytecode_for_immutable_plugin_trees(self) -> None:
        import mindmap

        self.assertTrue(sys.dont_write_bytecode)

    def test_home_relative_route_preserves_depth_and_lowercases(self) -> None:
        project = self.activate()
        self.assertEqual(project["route_path"], "/dev/exampleproject")
        nested = self.project_root / "src"
        nested.mkdir()
        self.assertEqual(self.store.find_project(nested, active_only=True)["id"], project["id"])

    def test_route_collision_is_explicit(self) -> None:
        self.activate()
        collision = self.home / "dev" / "exampleproject"
        collision.mkdir(parents=True)
        with self.assertRaises(RouteCollisionError):
            self.store.activate(collision)

    def test_record_builds_parent_graph_and_is_idempotent(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "s1")
        payload = {
            "summary": "Captured the project and its future deployment.",
            "operations": [
                {"op": "upsert", "id": "deploy", "title": "Deploy hub", "state": "planned", "kind": "task", "parent_id": "hub"},
                {"op": "upsert", "id": "hub", "title": "Build project hub", "state": "open", "kind": "goal", "parent_id": None},
            ],
        }
        first = self.store.record(self.project_root, "codex", "s1", "t1", payload)
        replay = self.store.record(self.project_root, "codex", "s1", "t1", payload)
        snapshot = self.store.project_snapshot(project["id"])
        self.assertEqual(set(first["changed"]), {"deploy", "hub"})
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(snapshot["items"]), 2)
        self.assertTrue(self.store.is_checkpointed("codex", "s1", "t1"))

    def test_divergent_idempotency_replay_is_rejected(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "replay")
        self.store.record(
            self.project_root, "codex", "replay", "same-turn",
            {"summary": "First", "operations": []},
        )
        with self.assertRaisesRegex(MindmapError, "different payload"):
            self.store.record(
                self.project_root, "codex", "replay", "same-turn",
                {"summary": "Second", "operations": [{"op": "upsert", "id": "lost", "title": "Must not vanish"}]},
            )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_invalid_batch_rolls_back_every_operation(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "claude", "s2")
        with self.assertRaises(MindmapError):
            self.store.record(
                self.project_root,
                "claude",
                "s2",
                "p1",
                {
                    "summary": "This should fail.",
                    "operations": [
                        {"op": "upsert", "id": "valid", "title": "Valid", "state": "open"},
                        {"op": "settle", "id": "missing"},
                    ],
                },
            )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_parent_cycles_are_rejected_atomically(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "cycle-session")
        with self.assertRaisesRegex(MindmapError, "cycle"):
            self.store.record(
                self.project_root, "codex", "cycle-session", "cycle-turn",
                {
                    "summary": "Invalid cycle",
                    "operations": [
                        {"op": "upsert", "id": "a", "title": "A", "parent_id": "b"},
                        {"op": "upsert", "id": "b", "title": "B", "parent_id": "a"},
                    ],
                },
            )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_old_web_api_prefix_is_an_ordinary_project_path(self) -> None:
        project_root = self.home / "_mindmap" / "project"
        project_root.mkdir(parents=True)
        project = self.store.activate(project_root)
        self.assertEqual(project["route_path"], "/_mindmap/project")

    def test_parallel_sessions_do_not_lose_updates(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "root-session")
        self.store.record(
            self.project_root, "codex", "root-session", "root-turn",
            {"summary": "Shared root", "operations": [{
                "op": "upsert", "id": "shared-root", "title": "Shared project goal",
                "state": "open", "kind": "goal", "parent_id": None,
            }]},
        )
        errors: list[Exception] = []

        def writer(index: int) -> None:
            try:
                host = "codex" if index % 2 == 0 else "claude"
                session_id = f"session-{index}"
                self.store.register_session(project["id"], host, session_id)
                self.store.record(
                    self.project_root,
                    host,
                    session_id,
                    f"turn-{index}",
                    {
                        "summary": f"Writer {index}",
                        "operations": [{"op": "upsert", "id": f"item-{index}", "title": f"Item {index}", "state": "open", "parent_id": "shared-root"}],
                    },
                )
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(index,)) for index in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(self.store.project_snapshot(project["id"])["items"]), 13)

    def test_stop_retains_history(self) -> None:
        project = self.activate()
        stopped = self.store.deactivate(self.project_root)
        self.assertEqual(stopped["active"], 0)
        self.assertIsNone(self.store.find_project(self.project_root, active_only=True))
        self.assertEqual(self.store.get_project(project["id"])["route_path"], "/dev/exampleproject")

    def test_changed_transcript_path_resets_incremental_cursor(self) -> None:
        project = self.activate()
        first_path = self.base / "first.jsonl"
        second_path = self.base / "second.jsonl"
        first_path.write_text(json.dumps({
            "type": "user", "uuid": "first", "message": {"role": "user", "content": "First"}
        }) + "\n")
        second_path.write_text(json.dumps({
            "type": "user", "uuid": "second", "message": {"role": "user", "content": "Second"}
        }) + "\n")
        self.store.register_session(project["id"], "claude", "moving", str(first_path))
        self.store.import_transcript("claude", "moving")
        self.store.register_session(project["id"], "claude", "moving", str(second_path))
        self.store.import_transcript("claude", "moving")
        self.assertEqual(
            [message["content"] for message in self.store.messages("claude", "moving")],
            ["First", "Second"],
        )

    def test_transcript_path_cursor_compare_and_swap_survives_race(self) -> None:
        project = self.activate()
        old_path = self.base / "race-old.jsonl"
        new_path = self.base / "race-new.jsonl"
        old_path.write_text(json.dumps({
            "type": "user", "uuid": "old-race", "message": {"role": "user", "content": "Old"}
        }) + "\n")
        new_path.write_text(json.dumps({
            "type": "user", "uuid": "new-race", "message": {"role": "user", "content": "New"}
        }) + "\n")
        self.store.register_session(project["id"], "claude", "racing", str(old_path))
        read_old = threading.Event()
        release_old = threading.Event()
        errors: list[Exception] = []
        original_read = store_module.read_transcript_batch

        def delayed_read(path, *args, **kwargs):
            result = original_read(path, *args, **kwargs)
            if Path(path) == old_path and threading.current_thread().name == "old-import":
                read_old.set()
                release_old.wait(timeout=5)
            return result

        def old_import() -> None:
            try:
                self.store.import_transcript("claude", "racing")
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        with patch.object(store_module, "read_transcript_batch", delayed_read):
            thread = threading.Thread(target=old_import, name="old-import")
            thread.start()
            self.assertTrue(read_old.wait(timeout=5))
            self.store.register_session(project["id"], "claude", "racing", str(new_path))
            self.store.import_transcript("claude", "racing")
            release_old.set()
            thread.join(timeout=5)
        self.assertEqual(errors, [])
        session = self.store.session("claude", "racing")
        self.assertEqual(session["transcript_cursor"], new_path.stat().st_size)
        self.assertEqual(
            [message["content"] for message in self.store.messages("claude", "racing")],
            ["New"],
        )

    def test_database_and_data_directory_are_private(self) -> None:
        directory_mode = stat.S_IMODE(self.store.path.parent.stat().st_mode)
        database_mode = stat.S_IMODE(self.store.path.stat().st_mode)
        self.assertEqual(directory_mode, 0o700)
        self.assertEqual(database_mode, 0o600)
        connection = self.store.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            wal = Path(str(self.store.path) + "-wal")
            shm = Path(str(self.store.path) + "-shm")
            self.assertEqual(stat.S_IMODE(wal.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(shm.stat().st_mode), 0o600)
            connection.rollback()
        finally:
            connection.close()

    def test_explicit_database_path_does_not_chmod_parent_directory(self) -> None:
        shared = self.base / "shared"
        shared.mkdir(mode=0o755)
        Store(shared / "explicit.sqlite3")
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o755)

    def test_record_rechecks_activation_inside_write_transaction(self) -> None:
        project = self.activate()
        original = self.store.find_project
        triggered = False

        def stop_between_lookup_and_commit(path, active_only=False):
            nonlocal triggered
            found = original(path, active_only)
            if active_only and found and not triggered:
                triggered = True
                self.store.deactivate(self.project_root)
            return found

        self.store.find_project = stop_between_lookup_and_commit  # type: ignore[method-assign]
        with self.assertRaisesRegex(MindmapError, "stopped"):
            self.store.record(
                self.project_root, "codex", "late", "late-turn",
                {"summary": "Too late", "operations": [{"op": "upsert", "id": "late", "title": "Late"}]},
            )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_nullable_and_unbounded_operation_fields_fail_cleanly(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "invalid-fields")
        invalid_operations = [
            {"op": "upsert", "id": "a", "title": "A", "summary": None},
            {"op": "upsert", "id": "a", "title": "A", "resume": None},
            {"op": "upsert", "id": "a", "title": "A", "state": None},
            {"op": "upsert", "id": "a", "title": "A", "kind": None},
            {"op": "upsert", "id": "a", "title": "A", "sort_order": {}},
            {"op": "upsert", "id": "a", "title": "A", "sort_order": 2**100},
            {"op": "upsert", "id": "a", "title": "A", "parent_id": "  "},
            {"op": "upsert", "id": "a", "title": "A", "parent_id": "missing"},
            {"op": [], "id": "a", "title": "A"},
            {"op": "upsert", "id": "a", "title": "A", "state": []},
            {"op": "upsert", "id": "a", "title": "A", "kind": []},
        ]
        for index, operation in enumerate(invalid_operations):
            with self.subTest(operation=operation), self.assertRaises(MindmapError):
                self.store.record(
                    self.project_root, "codex", "invalid-fields", f"bad-{index}",
                    {"summary": "Invalid", "operations": [operation]},
                )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_concept_resume_is_stored_and_retained_on_update(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "concepts")
        self.store.record(
            self.project_root, "codex", "concepts", "concept-1",
            {
                "summary": "Captured the unresolved frontier.",
                "operations": [{
                    "op": "upsert", "id": "causal-tree", "title": "Build the causal tree",
                    "summary": "Compress the conversation into connected concepts.",
                    "resume": "Test whether a cold reader can recover the open branch in ten seconds.",
                    "state": "open", "kind": "goal", "parent_id": None,
                }],
            },
        )
        self.store.record(
            self.project_root, "codex", "concepts", "concept-2",
            {"summary": "Clarified the concept.", "operations": [{
                "op": "upsert", "id": "causal-tree", "summary": "A small causal tree, not a chat log.",
                "expected_revision": 1,
            }]},
        )
        item = self.store.project_snapshot(project["id"])["items"][0]
        self.assertEqual(item["resume"], "Test whether a cold reader can recover the open branch in ten seconds.")
        context = self.store.context(self.project_root)
        self.assertIn("CAUSAL TREE:", context)
        self.assertIn("FRONTIER:", context)
        self.assertIn("Resume:", context)

    def test_semantic_warnings_flag_stale_frontiers_without_changing_state(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "warnings")
        self.store.record(
            self.project_root, "codex", "warnings", "seed",
            {"summary": "Seed warning and counterexample cases", "operations": [
                {
                    "op": "upsert", "id": "settled-action", "title": "Old delivery",
                    "state": "settled", "resume": "Run the final migration.",
                },
                {
                    "op": "upsert", "id": "conditional", "title": "Verified capture",
                    "state": "settled", "resume": "Run the check if evidence changes.",
                    "parent_id": "settled-action",
                },
                {
                    "op": "upsert", "id": "contradiction", "title": "Local install",
                    "state": "open", "summary": "The local installation is complete and verified.",
                    "parent_id": "settled-action",
                },
                {
                    "op": "upsert", "id": "superseded", "title": "Old direction",
                    "state": "planned", "summary": "This direction was superseded by the replacement.",
                },
                {
                    "op": "upsert", "id": "reopened", "title": "Capture images",
                    "state": "settled", "summary": "Capture originally worked.",
                    "parent_id": "settled-action",
                },
                {
                    "op": "upsert", "id": "explained-reopen", "title": "Upload images",
                    "state": "settled", "summary": "Upload originally worked.",
                    "parent_id": "settled-action",
                },
            ]},
        )
        self.store.record(
            self.project_root, "codex", "warnings", "reopen",
            {"summary": "Contradictory evidence reopened capture", "operations": [
                {
                    "op": "upsert", "id": "reopened", "state": "open",
                    "expected_revision": 1,
                },
                {
                    "op": "upsert", "id": "explained-reopen", "state": "open",
                    "summary": "Broader testing exposed an upload failure.",
                    "resume": "Fix the broader upload failure.", "expected_revision": 1,
                },
            ]},
        )
        snapshot = self.store.project_snapshot(project["id"])
        warning_keys = {
            (warning["code"], warning["item_id"])
            for warning in snapshot["semantic_warnings"]
        }
        self.assertEqual(warning_keys, {
            ("settled_action_resume", "settled-action"),
            ("state_summary_contradiction", "contradiction"),
            ("superseded_root_frontier", "superseded"),
            ("reversion_without_context", "reopened"),
        })
        states = {item["id"]: item["state"] for item in snapshot["items"]}
        self.assertEqual(states["contradiction"], "open")
        self.assertEqual(states["superseded"], "planned")
        context = self.store.context(self.project_root)
        self.assertIn("MINDMAP_SEMANTIC_WARNINGS_V1", context)
        self.assertIn("do not auto-settle causal parents", context)

    def test_semantic_warning_counterexamples_remain_quiet(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "quiet-warnings")
        self.store.record(
            self.project_root, "codex", "quiet-warnings", "seed",
            {"summary": "Valid closure and maintenance guidance", "operations": [
                {
                    "op": "upsert", "id": "none", "title": "Closed work",
                    "state": "settled", "resume": "No follow-up remains.",
                    "parent_id": "unfinished",
                },
                {
                    "op": "upsert", "id": "reopen-when", "title": "Conditional work",
                    "state": "settled", "resume": "Reopen when the upstream API changes.",
                    "parent_id": "unfinished",
                },
                {
                    "op": "upsert", "id": "maintenance", "title": "Maintenance",
                    "state": "settled", "resume": "Monitor the release channel for regressions.",
                    "parent_id": "unfinished",
                },
                {
                    "op": "upsert", "id": "unfinished", "title": "Unfinished work",
                    "state": "open", "summary": "The implementation is not complete.",
                    "resume": "Finish the implementation.",
                },
                {
                    "op": "upsert", "id": "backlog", "title": "Finish the backlog",
                    "state": "open", "summary": "Phase one is complete. Phase two remains.",
                    "resume": "Implement phase two.", "parent_id": "unfinished",
                },
                {
                    "op": "upsert", "id": "future", "title": "Later quality review",
                    "state": "planned",
                    "summary": "Apply this review only after the current companion is complete.",
                    "resume": "Review the next goal.", "parent_id": "unfinished",
                },
                {
                    "op": "upsert", "id": "active-root", "title": "Active workflow",
                    "state": "open", "summary": "The workflow remains active.",
                    "resume": "Delete the superseded private repository, then run the pilot.",
                },
            ]},
        )
        self.assertEqual(
            self.store.project_snapshot(project["id"])["semantic_warnings"], []
        )
        self.assertNotIn("MINDMAP_SEMANTIC_WARNINGS_V1", self.store.context(self.project_root))

    def test_user_deleted_branch_requires_explicit_restore(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "restore-session")
        self.store.record(
            self.project_root,
            "codex",
            "restore-session",
            "create-abandoned",
            {
                "summary": "Created an explored branch.",
                "operations": [
                    {
                        "op": "upsert",
                        "id": "abandoned-path",
                        "title": "Abandoned path",
                        "state": "open",
                    }
                ],
            },
        )
        with self.store.transaction() as connection:
            self.store._event(
                connection,
                project["id"],
                "item.subtree_deleted",
                {
                    "root_id": "abandoned-path",
                    "deleted": ["abandoned-path"],
                    "deleted_items": [
                        {"id": "abandoned-path", "title": "Abandoned path"}
                    ],
                    "source": "user",
                },
                item_id="abandoned-path",
            )
            connection.execute(
                "DELETE FROM items WHERE project_id = ? AND item_id = ?",
                (project["id"], "abandoned-path"),
            )

        context = self.store.context(self.project_root)
        self.assertIn("USER-DELETED BRANCHES:", context)
        self.assertIn("[abandoned-path] Abandoned path", context)
        self.assertIn("Do not recreate", context)
        with self.assertRaisesRegex(MindmapError, "explicitly deleted by the user"):
            self.store.record(
                self.project_root,
                "codex",
                "restore-session",
                "accidental-recreation",
                {
                    "summary": "Must not recreate retained evidence.",
                    "operations": [
                        {
                            "op": "upsert",
                            "id": "abandoned-path",
                            "title": "Abandoned path",
                        }
                    ],
                },
            )
        with self.assertRaisesRegex(MindmapError, "not a user-deleted concept"):
            self.store.record(
                self.project_root,
                "codex",
                "restore-session",
                "invalid-restore",
                {
                    "summary": "Invalid restore.",
                    "operations": [
                        {
                            "op": "upsert",
                            "id": "never-deleted",
                            "title": "Never deleted",
                            "restore": True,
                        }
                    ],
                },
            )
        self.store.record(
            self.project_root,
            "codex",
            "restore-session",
            "explicit-restore",
            {
                "summary": "The user explicitly restored the path.",
                "operations": [
                    {
                        "op": "upsert",
                        "id": "abandoned-path",
                        "title": "Abandoned path",
                        "restore": True,
                    }
                ],
            },
        )
        snapshot = self.store.project_snapshot(project["id"])
        self.assertEqual(snapshot["user_deleted_branches"], [])
        restored = [
            event
            for event in snapshot["events"]
            if event["event_type"] == "item.restored"
        ]
        self.assertEqual(len(restored), 1)
        self.assertNotIn("USER-DELETED BRANCHES:", self.store.context(self.project_root))

    def test_restore_field_and_legacy_created_event_are_strict(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "legacy-restore")
        for operation, message in (
            ({"op": "upsert", "id": "x", "title": "X", "restore": False}, "must be true"),
            ({"op": "settle", "id": "x", "restore": True}, "only for an upsert"),
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(MindmapError, message):
                self.store.record(
                    self.project_root,
                    "codex",
                    "legacy-restore",
                    f"invalid-{message}",
                    {"summary": "Invalid restore field.", "operations": [operation]},
                )
        with self.store.transaction() as connection:
            self.store._event(
                connection,
                project["id"],
                "item.subtree_deleted",
                {"deleted": ["legacy-id"], "source": "user"},
                item_id="legacy-id",
            )
            self.store._event(
                connection,
                project["id"],
                "item.created",
                {"operation": {"id": "legacy-id"}},
                item_id="legacy-id",
            )
        self.assertEqual(
            self.store.project_snapshot(project["id"])["user_deleted_branches"], []
        )

    def test_deletion_replay_matches_go_json_compatibility(self) -> None:
        project = self.activate()
        with self.store.transaction() as connection:
            self.store._event(
                connection,
                project["id"],
                "item.subtree_deleted",
                {
                    "DELETED": ["compat-id"],
                    "DELETED_ITEMS": [
                        {"ID": "compat-id", "TITLE": None},
                    ],
                    "source": "user",
                },
                item_id="compat-id",
            )
        self.assertEqual(
            self.store.project_snapshot(project["id"])["user_deleted_branches"],
            [{"id": "compat-id", "title": "compat-id"}],
        )

    def test_malformed_deletion_event_has_a_clear_read_error(self) -> None:
        project = self.activate()
        with self.store.transaction() as connection:
            connection.execute(
                """
                INSERT INTO events
                  (project_id, event_type, item_id, payload_json, created_at)
                VALUES (?, 'item.subtree_deleted', 'broken', '{', ?)
                """,
                (project["id"], store_module.utc_now()),
            )
        with self.assertRaisesRegex(
            MindmapError, "Invalid item.subtree_deleted event .* malformed JSON payload"
        ):
            self.store.project_snapshot(project["id"])

    def test_existing_items_schema_gains_resume_column(self) -> None:
        database = self.base / "old-items.sqlite3"
        Store(database)
        with sqlite3.connect(database) as connection:
            connection.execute("ALTER TABLE items DROP COLUMN resume")
        Store(database)
        with sqlite3.connect(database) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(items)")}
        self.assertIn("resume", columns)

    def test_new_project_on_upgraded_database_uses_causal_tree_v2(self) -> None:
        database = self.base / "upgraded-projects.sqlite3"
        legacy_store = Store(database)
        with sqlite3.connect(database) as connection:
            connection.execute("ALTER TABLE projects DROP COLUMN concept_model_version")
        upgraded = Store(database)
        root = self.home / "Dev" / "NewAfterUpgrade"
        root.mkdir()
        project = upgraded.activate(root)
        self.assertEqual(project["concept_model_version"], 2)

    def test_session_end_is_idempotent_and_delayed_events_do_not_reopen(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "claude", "ended", reopen=True)
        self.store.end_session("claude", "ended")
        ended_at = self.store.session("claude", "ended")["ended_at"]
        self.store.end_session("claude", "ended")
        self.store.register_session(project["id"], "claude", "ended", reopen=False)
        self.assertEqual(self.store.session("claude", "ended")["ended_at"], ended_at)
        events = self.store.project_snapshot(project["id"])["events"]
        self.assertEqual(sum(event["event_type"] == "session.ended" for event in events), 1)
        self.store.register_session(project["id"], "claude", "ended", reopen=True)
        self.assertIsNone(self.store.session("claude", "ended")["ended_at"])

    def test_settlement_timestamp_survives_later_summary_edits(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "settled")
        self.store.record(
            self.project_root, "codex", "settled", "settle-1",
            {"summary": "Settled", "operations": [{"op": "upsert", "id": "decision", "title": "Decision", "state": "settled"}]},
        )
        first = self.store.project_snapshot(project["id"])["items"][0]["settled_at"]
        self.store.record(
            self.project_root, "codex", "settled", "settle-2",
            {"summary": "Clarified", "operations": [{"op": "upsert", "id": "decision", "summary": "Clarification", "state": "settled", "expected_revision": 1}]},
        )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"][0]["settled_at"], first)

    def test_settle_clears_stale_resume_unless_replaced_explicitly(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "settle-resume")
        self.store.record(
            self.project_root, "codex", "settle-resume", "open",
            {"summary": "Open", "operations": [{
                "op": "upsert", "id": "choice", "title": "Choose storage",
                "resume": "Compare SQLite and Postgres", "state": "open",
            }]},
        )
        self.store.record(
            self.project_root, "codex", "settle-resume", "settled",
            {"summary": "Decided", "operations": [{
                "op": "settle", "id": "choice", "expected_revision": 1,
            }]},
        )
        item = self.store.project_snapshot(project["id"])["items"][0]
        self.assertEqual(item["resume"], "")
        self.assertNotIn("Compare SQLite", self.store.context(self.project_root))

    def test_compactness_bounds_reject_message_lists_and_deep_chronology(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "bounds")
        with self.assertRaisesRegex(MindmapError, "at most 20 concepts"):
            self.store.record(
                self.project_root, "codex", "bounds", "too-many",
                {"summary": "Message list", "operations": [
                    {"op": "upsert", "id": f"node-{index}", "title": f"Node {index}"}
                    for index in range(21)
                ]},
            )
        chain = [
            {
                "op": "upsert", "id": f"depth-{index}", "title": f"Depth {index}",
                "parent_id": f"depth-{index - 1}" if index else None,
            }
            for index in range(17)
        ]
        with self.assertRaisesRegex(MindmapError, "at most 10 concepts deep"):
            self.store.record(
                self.project_root, "codex", "bounds", "too-deep",
                {"summary": "Chronological chain", "operations": chain},
            )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_cumulative_semantic_growth_is_not_capped_at_24_concepts(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "cumulative")
        self.store.record(
            self.project_root, "codex", "cumulative", "root",
            {"summary": "Root", "operations": [{
                "op": "upsert", "id": "root", "title": "Governing idea", "parent_id": None,
            }]},
        )
        for batch in range(2):
            start = batch * 11
            self.store.record(
                self.project_root, "codex", "cumulative", f"batch-{batch}",
                {"summary": "Concept batch", "operations": [{
                    "op": "upsert", "id": f"concept-{index}", "title": f"Concept {index}",
                    "parent_id": "root",
                } for index in range(start, start + 11)]},
            )
        self.store.record(
            self.project_root, "codex", "cumulative", "beyond-old-cap",
            {"summary": "Preserved two more meaningful branches", "operations": [
                {"op": "upsert", "id": "concept-22", "title": "One more", "parent_id": "root"},
                {"op": "upsert", "id": "concept-23", "title": "Another concept", "parent_id": "root"},
            ]},
        )
        self.assertEqual(len(self.store.project_snapshot(project["id"])["items"]), 25)

    def test_record_schema_requires_operations_and_rejects_unknown_fields(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "strict-schema")
        invalid_payloads = [
            {"summary": "Missing operations"},
            {"summary": "Misspelled shape", "operations": [], "op": "upsert", "node_id": "lost"},
            {"summary": "Unknown operation field", "operations": [
                {"op": "upsert", "id": "node", "title": "Node", "titel": "Typo"},
            ]},
        ]
        for index, payload in enumerate(invalid_payloads):
            with self.subTest(payload=payload), self.assertRaises(MindmapError):
                self.store.record(
                    self.project_root, "codex", "strict-schema", f"invalid-{index}", payload
                )
        self.assertEqual(self.store.project_snapshot(project["id"])["items"], [])

    def test_additional_prompt_preserves_history_and_reopens_checkpoint(self) -> None:
        project = self.activate()
        session = self.store.register_session(project["id"], "codex", "steered")
        first = self.store.begin_turn(
            project["id"], session["id"], "same-interaction", "Build the comparison site"
        )
        self.assertFalse(first["checkpoint_invalidated"])
        self.store.record(
            self.project_root, "codex", "steered", "same-interaction",
            {"summary": "Captured the initial branch", "operations": [{
                "op": "upsert", "id": "comparison-site", "title": "Build the comparison site",
            }]},
        )
        steered = self.store.begin_turn(
            project["id"], session["id"], "same-interaction", "Also prepare the handoff"
        )
        self.assertTrue(steered["checkpoint_invalidated"])
        self.assertFalse(self.store.is_checkpointed("codex", "steered", "same-interaction"))
        self.assertEqual(
            [entry["prompt"] for entry in self.store.turn_prompts(
                "codex", "steered", "same-interaction"
            )],
            ["Build the comparison site", "Also prepare the handoff"],
        )
        self.assertEqual(
            self.store.turn("codex", "steered", "same-interaction")["prompt_excerpt"],
            "Build the comparison site",
        )
        self.store.record(
            self.project_root, "codex", "steered", "same-interaction",
            {"summary": "Captured the added handoff", "operations": [{
                "op": "upsert", "id": "handoff", "title": "Prepare the handoff",
                "parent_id": "comparison-site",
            }]},
        )
        self.assertTrue(self.store.is_checkpointed("codex", "steered", "same-interaction"))
        self.assertEqual(
            {item["id"] for item in self.store.project_snapshot(project["id"])["items"]},
            {"comparison-site", "handoff"},
        )

    def test_text_limits_reject_transcript_scale_nodes(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "text-limits")
        for field, value, message in (
            ("title", "t" * 161, "title must be 160"),
            ("summary", "s" * 1201, "summary must be 1200"),
            ("resume", "r" * 601, "resume must be 600"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(MindmapError, message):
                self.store.record(
                    self.project_root, "codex", "text-limits", f"bad-{field}",
                    {"summary": "Invalid", "operations": [{
                        "op": "upsert", "id": field, "title": "Concept", field: value,
                    }]},
                )
        with self.assertRaisesRegex(MindmapError, "Checkpoint summary must be 500"):
            self.store.record(
                self.project_root, "codex", "text-limits", "bad-checkpoint",
                {"summary": "x" * 501, "operations": []},
            )

    def test_numbered_chronology_nodes_are_rejected(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "chronology")
        for operation in (
            {"op": "upsert", "id": "message-17", "title": "A concept"},
            {"op": "upsert", "id": "idea", "title": "Turn 42"},
            {"op": "upsert", "id": "event_8", "title": "An event"},
        ):
            with self.subTest(operation=operation), self.assertRaisesRegex(
                MindmapError, "not numbered messages"
            ):
                self.store.record(
                    self.project_root, "codex", "chronology", operation["id"],
                    {"summary": "Chronology", "operations": [operation]},
                )

    def test_remove_can_merge_legacy_nodes_and_reparent_children(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "merge")
        self.store.record(
            self.project_root, "codex", "merge", "seed",
            {"summary": "Legacy graph root", "operations": [
                {"op": "upsert", "id": "goal", "title": "Goal", "parent_id": None},
            ]},
        )
        # Simulate rows written by the pre-v2 task/chat model, bypassing the v2
        # creation guard so the public remove operation proves they are cleanable.
        now = store_module.utc_now()
        with self.store.transaction() as connection:
            for item_id, parent_id, title in (
                ("message-1", "goal", "Message-shaped debris"),
                ("concept", "message-1", "Actual concept"),
            ):
                connection.execute(
                    """
                    INSERT INTO items
                      (project_id, item_id, parent_id, title, summary, resume, state,
                       kind, sort_order, created_at, updated_at, settled_at, revision)
                    VALUES (?, ?, ?, ?, '', '', 'open', 'thread', 0, ?, ?, NULL, 1)
                    """,
                    (project["id"], item_id, parent_id, title, now, now),
                )
        self.store.record(
            self.project_root, "codex", "merge", "cleanup",
            {"summary": "Merged transcript debris", "operations": [{
                "op": "remove", "id": "message-1", "expected_revision": 1,
                "reparent_to": "goal",
            }]},
        )
        items = {item["id"]: item for item in self.store.project_snapshot(project["id"])["items"]}
        self.assertNotIn("message-1", items)
        self.assertEqual(items["concept"]["parent_id"], "goal")
        self.assertEqual(items["concept"]["revision"], 2)

    def test_revision_check_prevents_cross_session_overwrite(self) -> None:
        project = self.activate()
        for host, session in (("codex", "writer-a"), ("claude", "writer-b")):
            self.store.register_session(project["id"], host, session)
        self.store.record(
            self.project_root, "codex", "writer-a", "create",
            {"summary": "Created design", "operations": [{
                "op": "upsert", "id": "design", "title": "Choose the design",
            }]},
        )
        self.store.record(
            self.project_root, "codex", "writer-a", "first-update",
            {"summary": "First writer", "operations": [{
                "op": "upsert", "id": "design", "summary": "Codex branch",
                "expected_revision": 1,
            }]},
        )
        with self.assertRaisesRegex(MindmapError, "changed concurrently"):
            self.store.record(
                self.project_root, "claude", "writer-b", "stale-update",
                {"summary": "Stale writer", "operations": [{
                    "op": "upsert", "id": "design", "summary": "Claude branch",
                    "expected_revision": 1,
                }]},
            )
        item = self.store.project_snapshot(project["id"])["items"][0]
        self.assertEqual(item["summary"], "Codex branch")
        self.assertEqual(item["revision"], 2)

    def test_remove_and_child_update_are_order_independent(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "ordered-merge")
        self.store.record(
            self.project_root, "codex", "ordered-merge", "seed",
            {"summary": "Seed", "operations": [
                {"op": "upsert", "id": "goal", "title": "Goal"},
                {"op": "upsert", "id": "debris", "title": "Debris", "parent_id": "goal"},
                {"op": "upsert", "id": "child", "title": "Child", "parent_id": "debris"},
            ]},
        )
        self.store.record(
            self.project_root, "codex", "ordered-merge", "cleanup",
            {"summary": "Cleaned", "operations": [
                {"op": "remove", "id": "debris", "expected_revision": 1, "reparent_to": "goal"},
                {"op": "upsert", "id": "child", "expected_revision": 1, "summary": "Kept meaning"},
            ]},
        )
        child = {item["id"]: item for item in self.store.project_snapshot(project["id"])["items"]}["child"]
        self.assertEqual(child["parent_id"], "goal")
        self.assertEqual(child["revision"], 2)

    def test_legacy_map_can_checkpoint_then_reconcile_to_v2(self) -> None:
        project = self.activate()
        self.store.register_session(project["id"], "codex", "legacy")
        with patch.object(store_module, "MAX_ROOT_ITEMS", 6):
            self.store.record(
                self.project_root, "codex", "legacy", "legacy-seed",
                {"summary": "Old board", "operations": [
                    {"op": "upsert", "id": f"root-{index}", "title": f"Old root {index}"}
                    for index in range(5)
                ]},
            )
        with self.store.transaction() as connection:
            connection.execute(
                "UPDATE projects SET concept_model_version = 1 WHERE id = ?", (project["id"],)
            )
        context = self.store.context(self.project_root)
        self.assertIn("LEGACY MAP OUTSIDE COMPRESSION BOUNDS", context)
        self.store.record(
            self.project_root, "codex", "legacy", "no-change",
            {"summary": "Legacy reconciliation pending", "operations": []},
        )
        self.store.record(
            self.project_root, "codex", "legacy", "reconciled",
            {"concept_model": "causal-tree-v2", "summary": "Merged old roots", "operations": [{
                "op": "remove", "id": "root-4", "expected_revision": 1,
            }]},
        )
        self.assertEqual(self.store.get_project(project["id"])["concept_model_version"], 2)

    def test_url_routes_encode_reserved_characters_and_sessions_directory(self) -> None:
        special = self.home / "Dev" / "sessions" / "why? #100%"
        special.mkdir(parents=True)
        project = self.store.activate(special)
        self.assertEqual(project["route_path"], "/dev/sessions/why%3F%20%23100%25")

    def test_concurrent_first_run_store_creation_has_no_toctou_failure(self) -> None:
        new_database = self.base / "race" / "mindmap.sqlite3"
        errors: list[Exception] = []

        def create() -> None:
            try:
                Store(new_database)
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [threading.Thread(target=create) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])

    def test_concurrent_old_schema_upgrade_is_serialized_between_processes(self) -> None:
        database = self.base / "upgrade" / "mindmap.sqlite3"
        database.parent.mkdir()
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE sessions (
                    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
                    host TEXT NOT NULL, session_id TEXT NOT NULL,
                    transcript_path TEXT, transcript_cursor INTEGER NOT NULL DEFAULT 0,
                    started_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, ended_at TEXT,
                    UNIQUE(host, session_id)
                );
                CREATE TABLE turns (
                    id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
                    session_pk INTEGER NOT NULL, interaction_id TEXT NOT NULL,
                    prompt_excerpt TEXT, started_at TEXT NOT NULL,
                    checkpointed_at TEXT, checkpoint_summary TEXT,
                    last_assistant_message TEXT,
                    UNIQUE(session_pk, interaction_id)
                );
                """
            )
        environment = os.environ.copy()
        source = str(Path(__file__).resolve().parents[1] / "src")
        environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
        code = f"from mindmap.store import Store; Store({str(database)!r})"
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", code],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(24)
        ]
        failures = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            if process.returncode:
                failures.append((process.returncode, stdout, stderr))
        self.assertEqual(failures, [])
        with sqlite3.connect(database) as connection:
            session_columns = {row[1] for row in connection.execute("PRAGMA table_info(sessions)")}
            turn_columns = {row[1] for row in connection.execute("PRAGMA table_info(turns)")}
        self.assertIn("transcript_anchor_hash", session_columns)
        self.assertIn("checkpoint_payload_hash", turn_columns)
        self.assertIn("tool_activity_generation", turn_columns)
        self.assertIn("checkpoint_tool_activity_generation", turn_columns)
        self.assertIn("last_tool_name", turn_columns)
        self.assertIn("last_tool_at", turn_columns)

    def test_missing_transcript_preserves_rotation_identity_and_anchor(self) -> None:
        project = self.activate()
        transcript = self.base / "temporary.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "uuid": "first", "message": {"role": "user", "content": "First"}}) + "\n"
        )
        self.store.register_session(project["id"], "claude", "temporary", str(transcript))
        self.store.import_transcript("claude", "temporary")
        before = self.store.session("claude", "temporary")
        held = transcript.with_suffix(".held")
        transcript.rename(held)
        result = self.store.import_transcript("claude", "temporary")
        after = self.store.session("claude", "temporary")
        self.assertTrue(result["warnings"])
        self.assertEqual(after["transcript_cursor"], before["transcript_cursor"])
        self.assertEqual(after["transcript_device"], before["transcript_device"])
        self.assertEqual(after["transcript_inode"], before["transcript_inode"])
        self.assertEqual(after["transcript_anchor_hash"], before["transcript_anchor_hash"])

    def test_context_uses_activation_state_from_its_consistent_snapshot(self) -> None:
        self.activate()
        original_snapshot = self.store.project_snapshot

        def deactivate_then_snapshot(project_id):
            self.store.deactivate(self.project_root)
            return original_snapshot(project_id)

        self.store.project_snapshot = deactivate_then_snapshot  # type: ignore[method-assign]
        context = self.store.context(self.project_root)
        self.assertIn("tracking is stopped", context)
        self.assertNotIn("Mindmap is active", context)

    def test_stop_fallback_is_visible_without_duplicate_persisted_messages(self) -> None:
        project = self.activate()
        transcript = self.base / "lagging.jsonl"
        transcript.write_text("")
        session = self.store.register_session(
            project["id"], "claude", "lagging", str(transcript)
        )
        self.store.begin_turn(project["id"], session["id"], "lag-turn", "Do work")
        self.store.add_last_assistant_message(
            "claude", "lagging", "lag-turn", "Finished the work."
        )
        self.assertEqual(
            [message["content"] for message in self.store.normalized_history("claude", "lagging")],
            ["Finished the work."],
        )
        transcript.write_text(
            json.dumps({"type": "user", "uuid": "lag-user", "timestamp": "2026-01-01T00:00:00Z", "message": {"role": "user", "content": "Do work"}}) + "\n" +
            json.dumps({"type": "assistant", "uuid": "lag-assistant", "timestamp": "2026-01-01T00:00:01Z", "message": {"role": "assistant", "content": "Finished the work."}}) + "\n"
        )
        self.store.import_transcript("claude", "lagging")
        history = self.store.normalized_history("claude", "lagging")
        self.assertEqual([message["role"] for message in history], ["user", "assistant"])
        self.assertEqual(sum(message["content"] == "Finished the work." for message in history), 1)


if __name__ == "__main__":
    unittest.main()
