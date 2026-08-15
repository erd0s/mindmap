from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mindmap.transcripts import read_transcript, render_markdown
from mindmap.transcripts import read_transcript_batch
from mindmap.errors import MindmapError


FIXTURES = Path(__file__).with_name("fixtures")


class TranscriptTests(unittest.TestCase):
    def test_codex_normalization_filters_non_conversation_records(self) -> None:
        messages, cursor = read_transcript(FIXTURES / "codex.jsonl", "codex")
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertIn("Tailnet", messages[0].content)
        self.assertGreater(cursor, 0)

    def test_claude_normalization_filters_tool_only_messages(self) -> None:
        messages, _ = read_transcript(FIXTURES / "claude.jsonl", "claude")
        self.assertEqual([message.key for message in messages], ["cl-user-1", "cl-assistant-1"])
        self.assertNotIn("tool_use", messages[1].content)

    def test_incremental_cursor_reads_only_appended_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            lines = (FIXTURES / "claude.jsonl").read_text().splitlines()
            path.write_text(lines[0] + "\n")
            first, cursor = read_transcript(path, "claude")
            with path.open("a") as stream:
                stream.write(lines[1] + "\n")
            second, new_cursor = read_transcript(path, "claude", cursor)
            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 1)
            self.assertGreater(new_cursor, cursor)

    def test_markdown_is_agent_readable(self) -> None:
        messages, _ = read_transcript(FIXTURES / "codex.jsonl", "codex")
        rendered = render_markdown([message.as_dict() for message in messages])
        self.assertIn("## User", rendered)
        self.assertIn("## Assistant", rendered)

    def test_partial_jsonl_record_is_retried_after_host_finishes_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            complete = (FIXTURES / "claude.jsonl").read_text().splitlines()[0]
            split = len(complete) // 2
            path.write_text(complete[:split])
            first, cursor = read_transcript(path, "claude")
            self.assertEqual(first, [])
            self.assertEqual(cursor, 0)
            with path.open("a") as stream:
                stream.write(complete[split:] + "\n")
            second, new_cursor = read_transcript(path, "claude", cursor)
            self.assertEqual(len(second), 1)
            self.assertGreater(new_cursor, 0)

    def test_malformed_complete_record_is_visible_and_cursor_is_not_returned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text('{"type":"user","uuid":"good","message":{"role":"user","content":"Good"}}\nnot-json\n')
            with self.assertRaisesRegex(MindmapError, "Malformed"):
                read_transcript(path, "claude")

    def test_malformed_complete_record_is_quarantined_without_blocking_later_records(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            path.write_text(
                'not-json\n'
                '{"type":"user","uuid":"later","message":{"role":"user","content":"Later"}}\n'
            )
            batch = read_transcript_batch(path, "claude")
            self.assertEqual([message.key for message in batch.messages], ["later"])
            self.assertEqual(len(batch.warnings), 1)
            self.assertEqual(batch.cursor, path.stat().st_size)

    def test_same_path_replacement_resets_cursor_using_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            first_line = '{"type":"user","uuid":"old","message":{"role":"user","content":"Old history padding padding padding"}}\n'
            path.write_text(first_line)
            first = read_transcript_batch(path, "claude")
            replacement = '{"type":"user","uuid":"new","message":{"role":"user","content":"New history padding padding padding padding"}}\n'
            # Truncate and regrow the same inode beyond the old cursor.
            with path.open("w") as stream:
                stream.write(replacement + replacement.replace('"new"', '"new-2"'))
            second = read_transcript_batch(
                path,
                "claude",
                first.cursor,
                (first.device, first.inode),
                (first.anchor_length, first.anchor_hash),
            )
            self.assertEqual([message.key for message in second.messages], ["new", "new-2"])

    def test_tail_anchor_detects_rewrite_that_preserves_first_4096_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "transcript.jsonl"
            prefix = (
                '{"type":"user","uuid":"shared","message":{"role":"user","content":"'
                + ("x" * 5000)
                + '"}}\n'
            )
            old = "".join(
                f'{{"type":"user","uuid":"old-{index}","message":{{"role":"user","content":"old {index}"}}}}\n'
                for index in range(30)
            )
            path.write_text(prefix + old)
            first = read_transcript_batch(path, "claude")
            replacement = "".join(
                f'{{"type":"user","uuid":"new-{index}","message":{{"role":"user","content":"new {index}"}}}}\n'
                for index in range(40)
            )
            path.write_text(prefix + replacement)
            second = read_transcript_batch(
                path,
                "claude",
                first.cursor,
                (first.device, first.inode),
                (first.anchor_length, first.anchor_hash),
            )
            self.assertEqual(second.messages[0].key, "shared")
            self.assertEqual([message.key for message in second.messages[-40:]], [f"new-{i}" for i in range(40)])


if __name__ == "__main__":
    unittest.main()
