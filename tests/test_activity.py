from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from mindmap.activity import note_pre_tool_activity, run_pre_tool_hook
from mindmap.store import Store


class ActivityHookTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.home = self.base / "home"
        self.root = self.home / "project"
        self.root.mkdir(parents=True)
        os.environ["MINDMAP_HOME_DIR"] = str(self.home)
        os.environ["MINDMAP_DATA_DIR"] = str(self.base / "data")

    def tearDown(self) -> None:
        os.environ.pop("MINDMAP_HOME_DIR", None)
        os.environ.pop("MINDMAP_DATA_DIR", None)
        self.temp.cleanup()

    def test_fast_path_advances_exact_codex_turn(self) -> None:
        store = Store()
        project = store.activate(self.root)
        session = store.register_session(project["id"], "codex", "session")
        store.begin_turn(project["id"], session["id"], "turn", "Work")

        note_pre_tool_activity("codex", {
            "cwd": str(self.root), "session_id": "session", "turn_id": "turn",
            "tool_name": "apply_patch",
        })

        turn = store.turn("codex", "session", "turn")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["last_tool_name"], "apply_patch")

    def test_fast_path_resolves_latest_claude_turn_without_prompt_id(self) -> None:
        store = Store()
        project = store.activate(self.root)
        session = store.register_session(project["id"], "claude", "session")
        store.begin_turn(project["id"], session["id"], "prompt", "Work")

        note_pre_tool_activity("claude", {
            "cwd": str(self.root), "session_id": "session",
            "tool_name": "mcp__shell__execute",
        })

        turn = store.turn("claude", "session", "prompt")
        self.assertEqual(turn["tool_activity_generation"], 1)
        self.assertEqual(turn["last_tool_name"], "mcp__shell__execute")

    def test_fast_path_is_quiet_when_database_does_not_exist(self) -> None:
        result = run_pre_tool_hook("codex", {
            "cwd": str(self.root), "session_id": "missing", "turn_id": "missing",
            "tool_name": "Bash",
        })
        self.assertEqual(result, 0)
        self.assertFalse((self.base / "data").exists())


if __name__ == "__main__":
    unittest.main()
