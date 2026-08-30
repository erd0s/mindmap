import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_cold_read import prepare_packet


class PrepareColdReadTests(unittest.TestCase):
    def _report(self, path: Path, package: str) -> None:
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "package": package,
                    "package_commit": "abc123",
                    "scorer_version": 5,
                    "results": [
                        {
                            "host": host,
                            "fixture": "local-installation-closure",
                            "trial": 1,
                            "items": [
                                {
                                    "id": "local-installation",
                                    "parent_id": None,
                                    "sort_order": 0,
                                    "title": "Refresh local installation",
                                    "summary": "The install is verified.",
                                    "resume": "",
                                    "state": "settled",
                                    "kind": "task",
                                    "created_at": "secret timestamp",
                                    "revision": 7,
                                }
                            ],
                        }
                        for host in ("codex", "claude")
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_packet_is_blinded_and_key_retains_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = root / "before.json"
            after = root / "after.json"
            self._report(before, "v0.3.0")
            self._report(after, "candidate")
            output = root / "packet"
            key = prepare_packet([before, after], output, trial=1, seed=9)

            packet = (output / "packet.md").read_text(encoding="utf-8")
            self.assertEqual(len(key["samples"]), 4)
            self.assertNotIn("v0.3.0", packet)
            self.assertNotIn("candidate", packet)
            self.assertNotIn("codex", packet)
            self.assertNotIn("claude", packet)
            self.assertNotIn("secret timestamp", packet)
            self.assertNotIn("revision", packet)
            self.assertIn("Refresh local installation", packet)
            self.assertTrue((output / "answer-sheet.md").is_file())
            self.assertEqual(json.loads((output / "key.json").read_text()), key)

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            before = root / "before.json"
            after = root / "after.json"
            self._report(before, "v0.3.0")
            self._report(after, "candidate")
            output = root / "packet"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "already exists"):
                prepare_packet([before, after], output, trial=1, seed=9)


if __name__ == "__main__":
    unittest.main()
