from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import generate_notices


class GenerateNoticesTests(unittest.TestCase):
    def test_collect_downloads_modules_missing_from_the_local_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dependency = Path(directory) / "dependency"
            dependency.mkdir()
            (dependency / "LICENCE").write_text("fixture license\n", encoding="utf-8")

            packages = [
                {
                    "Module": {
                        "Path": "example.com/dependency",
                        "Version": "v1.2.3",
                    }
                }
            ]

            def command(command: list[str], _cwd: Path) -> object:
                if command[:3] == ["go", "mod", "download"]:
                    return {"Dir": str(dependency)}
                if command[:2] == ["npm", "query"]:
                    return []
                self.fail(f"unexpected command: {command}")

            with (
                mock.patch.object(generate_notices, "json_stream", return_value=packages),
                mock.patch.object(generate_notices, "command_json", side_effect=command) as commands,
            ):
                packages = generate_notices.collect()

            self.assertEqual(
                packages,
                [("Go module example.com/dependency v1.2.3", "fixture license")],
            )
            self.assertTrue(
                any(
                    call.args[0]
                    == [
                        "go",
                        "mod",
                        "download",
                        "-json",
                        "example.com/dependency@v1.2.3",
                    ]
                    for call in commands.call_args_list
                )
            )


if __name__ == "__main__":
    unittest.main()
