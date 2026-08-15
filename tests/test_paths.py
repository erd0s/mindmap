from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from mindmap.cli import main
from mindmap.paths import discover_project_root, route_for_root


class ProjectPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.home = base / "home"
        self.home.mkdir()
        os.environ["MINDMAP_HOME_DIR"] = str(self.home)
        os.environ["MINDMAP_DATA_DIR"] = str(base / "data")

    def tearDown(self) -> None:
        for key in ("MINDMAP_HOME_DIR", "MINDMAP_DATA_DIR"):
            os.environ.pop(key, None)
        self.temp.cleanup()

    def test_route_is_a_stable_home_relative_project_identity(self) -> None:
        root = self.home / "ExampleOrg" / "kit cc"
        root.mkdir(parents=True)
        self.assertEqual(route_for_root(root), "/exampleorg/kit%20cc")

    def test_route_matches_shared_go_golden_cases(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "route-cases.json"
        for case in json.loads(fixture.read_text(encoding="utf-8")):
            with self.subTest(case["name"]):
                root = self.home / case["relative_path"]
                root.mkdir(parents=True)
                self.assertEqual(route_for_root(root), case["route"])

    def test_discovery_uses_nearest_git_root(self) -> None:
        root = self.home / "Dev" / "project"
        nested = root / "src" / "package"
        nested.mkdir(parents=True)
        (root / ".git").mkdir()
        self.assertEqual(discover_project_root(nested), root)

    def test_start_cli_returns_the_project_without_a_network_url(self) -> None:
        root = self.home / "ExampleOrg" / "kit-cc"
        root.mkdir(parents=True)
        output = StringIO()
        with redirect_stdout(output):
            result = main(["start", "--root", str(root)])
        self.assertEqual(result, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["route_path"], "/exampleorg/kit-cc")
        self.assertNotIn("public_url", payload)


if __name__ == "__main__":
    unittest.main()
