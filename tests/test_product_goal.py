from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProductGoalTests(unittest.TestCase):
    def test_skill_defines_semantic_compression_not_transcript_mapping(self) -> None:
        skill = (ROOT / "core/skills/mindmap/SKILL.md").read_text(encoding="utf-8")
        self.assertIn("small causal tree", skill.lower())
        self.assertIn("Do not run `mindmap status` as a substitute", skill)
        self.assertIn("Never create nodes for individual messages", skill)
        self.assertIn("Parent means “grew out of”", skill)
        self.assertIn("use the matching frontier and its resume point", skill)
        self.assertIn("Never default a new session's concepts to the root", skill)
        self.assertIn("zero to three nodes", skill)
        self.assertIn("which project root is active", skill)
        self.assertIn("activation covers the whole project directory", skill)
        self.assertIn("MINDMAP_ACTIVATION_BLOCKED_V1", skill)
        self.assertIn("never use `cd`, change a tool call's workdir", skill)
        self.assertIn("do not retry from another directory", skill)
        self.assertIn("do not claim activation, tracking, checkpointing, or future backfill", skill)
        self.assertIn("USER-DELETED BRANCHES", skill)
        self.assertIn("restore: true", skill)

    def test_reference_fixture_is_a_small_connected_causal_tree(self) -> None:
        transcript = json.loads((ROOT / "tests/fixtures/compression-session.json").read_text())
        nodes = json.loads((ROOT / "tests/fixtures/compression-expected.json").read_text())["nodes"]
        by_id = {node["id"]: node for node in nodes}
        roots = [node for node in nodes if node["parent_id"] is None]
        self.assertEqual(len(roots), 1)
        self.assertLess(len(nodes), len(transcript["messages"]))
        self.assertEqual({node["state"] for node in nodes}, {"planned", "open", "settled"})
        for node in nodes:
            if node["parent_id"] is not None:
                self.assertIn(node["parent_id"], by_id)

    def test_desktop_product_contains_graph_and_confirmed_subtree_deletion(self) -> None:
        source = (ROOT / "desktop/frontend/src/App.jsx").read_text(encoding="utf-8")
        self.assertIn("<ReactFlow", source)
        self.assertIn("frontierCount", source)
        self.assertIn("Delete branch", source)
        self.assertIn("including every descendant", source)
        self.assertIn("backend.onChanged", source)
        self.assertIn("edgesFocusable={false}", source)
        self.assertIn("proOptions={{ hideAttribution: true }}", source)
        self.assertIn("Open a coding session", source)
        self.assertNotIn("newProjectWindow", source)
        self.assertNotIn("Local data only", source)
        self.assertNotIn("fetch(", source)


if __name__ == "__main__":
    unittest.main()
