from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mindmap.cli import _payload, main
from mindmap.errors import MindmapError
from mindmap.store import Store


class InteractiveInput(io.StringIO):
    def isatty(self) -> bool:
        return True


class CLITests(unittest.TestCase):
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

    def test_record_stdin_rejects_interactive_tty(self) -> None:
        with patch("sys.stdin", InteractiveInput('{"summary":"unsafe"}')):
            with self.assertRaisesRegex(
                MindmapError, "non-interactive pipe or heredoc"
            ):
                _payload("-")

    def test_record_accepts_large_noninteractive_stdin(self) -> None:
        store = Store()
        project = store.activate(self.root)
        session = store.register_session(project["id"], "codex", "large-pipe")
        store.begin_turn(project["id"], session["id"], "turn", "Record the map")
        payload = {
            "summary": "Record a payload larger than a canonical terminal buffer.",
            "operations": [
                {
                    "op": "upsert",
                    "id": f"branch-{index}",
                    "title": f"Branch {index}",
                    "summary": str(index) * 1100,
                    "state": "open",
                    "kind": "thread",
                    "parent_id": None,
                }
                for index in range(4)
            ],
        }
        serialized = json.dumps(payload)
        self.assertGreater(len(serialized.encode("utf-8")), 4096)

        stdout = io.StringIO()
        with patch("sys.stdin", io.StringIO(serialized)), patch("sys.stdout", stdout):
            result = main(
                [
                    "record",
                    "--root",
                    str(self.root),
                    "--host",
                    "codex",
                    "--session-id",
                    "large-pipe",
                    "--interaction-id",
                    "turn",
                    "--file",
                    "-",
                ]
            )

        self.assertEqual(result, 0)
        self.assertIn('"checkpointed": true', stdout.getvalue())
        self.assertEqual(len(store.project_snapshot(project["id"])["items"]), 4)


if __name__ == "__main__":
    unittest.main()
