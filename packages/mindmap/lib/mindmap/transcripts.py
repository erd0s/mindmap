from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .errors import MindmapError


@dataclass(frozen=True)
class Message:
    key: str
    role: str
    content: str
    timestamp: str | None = None
    source_offset: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp,
            "source_offset": self.source_offset,
        }


@dataclass(frozen=True)
class TranscriptBatch:
    messages: list[Message]
    cursor: int
    device: int
    inode: int
    anchor_length: int
    anchor_hash: str | None
    source_available: bool = True
    warnings: tuple[str, ...] = ()


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text", "text"}:
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _key(record: dict[str, Any], line: bytes, offset: int) -> str:
    candidates = [
        record.get("uuid"),
        record.get("id"),
        (record.get("payload") or {}).get("id") if isinstance(record.get("payload"), dict) else None,
        (record.get("message") or {}).get("id") if isinstance(record.get("message"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            return candidate
    digest = hashlib.sha256(line).hexdigest()[:20]
    return f"line-{offset}-{digest}"


def _parse_codex(record: dict[str, Any], line: bytes, offset: int) -> Message | None:
    if record.get("type") != "response_item":
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict) or payload.get("type") != "message":
        return None
    role = payload.get("role")
    if role not in {"user", "assistant"}:
        return None
    content = _text_from_content(payload.get("content"))
    if not content:
        return None
    return Message(
        key=_key(payload, line, offset),
        role=role,
        content=content,
        timestamp=record.get("timestamp"),
        source_offset=offset,
    )


def _parse_claude(record: dict[str, Any], line: bytes, offset: int) -> Message | None:
    if record.get("type") not in {"user", "assistant"}:
        return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    role = message.get("role") or record.get("type")
    if role not in {"user", "assistant"}:
        return None
    content = _text_from_content(message.get("content"))
    if not content:
        return None
    return Message(
        key=_key(record, line, offset),
        role=role,
        content=content,
        timestamp=record.get("timestamp"),
        source_offset=offset,
    )


def read_transcript(
    path: str | Path, host: str, start_offset: int = 0
) -> tuple[list[Message], int]:
    batch = read_transcript_batch(path, host, start_offset)
    if batch.warnings:
        raise MindmapError("\n".join(batch.warnings))
    return batch.messages, batch.cursor


def read_transcript_batch(
    path: str | Path,
    host: str,
    start_offset: int = 0,
    expected_identity: tuple[int, int] | None = None,
    expected_anchor: tuple[int, str] | None = None,
) -> TranscriptBatch:
    transcript = Path(path).expanduser()
    if not transcript.is_file():
        device, inode = expected_identity or (0, 0)
        anchor_length, anchor_hash = expected_anchor or (0, None)
        return TranscriptBatch(
            [], start_offset, device, inode, anchor_length, anchor_hash,
            source_available=False,
        )
    parser = _parse_codex if host == "codex" else _parse_claude
    messages: list[Message] = []
    warnings: list[str] = []
    with transcript.open("rb") as stream:
        metadata = os.fstat(stream.fileno())
        identity = (int(metadata.st_dev), int(metadata.st_ino))
        anchor_changed = False
        if expected_anchor is not None:
            expected_length, expected_hash = expected_anchor
            # Anchor the bytes immediately before the committed cursor. A prefix
            # anchor misses same-inode rewrites that preserve the file's opening.
            stream.seek(max(0, start_offset - expected_length))
            current_anchor = stream.read(expected_length)
            anchor_changed = (
                len(current_anchor) != expected_length
                or hashlib.sha256(current_anchor).hexdigest() != expected_hash
            )
        rotated = (
            (expected_identity is not None and expected_identity != identity)
            or anchor_changed
        )
        safe_offset = start_offset if not rotated and 0 <= start_offset <= metadata.st_size else 0
        stream.seek(safe_offset)
        committed_offset = safe_offset
        while True:
            offset = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.strip():
                committed_offset = stream.tell()
                continue
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError):
                if not line.endswith(b"\n"):
                    # The host may still be writing this JSONL record. Retry it next time.
                    stream.seek(offset)
                    break
                warnings.append(
                    f"Malformed {host} transcript JSON at byte {offset} in {transcript}; "
                    "this complete record was quarantined and later records were imported."
                )
                committed_offset = stream.tell()
                continue
            if not isinstance(record, dict):
                committed_offset = stream.tell()
                continue
            message = parser(record, line, offset)
            if message:
                messages.append(message)
            committed_offset = stream.tell()
        end_offset = committed_offset
        anchor_length = min(end_offset, 4096)
        stream.seek(end_offset - anchor_length)
        anchor_bytes = stream.read(anchor_length)
        anchor_hash = hashlib.sha256(anchor_bytes).hexdigest() if anchor_bytes else None
    return TranscriptBatch(
        messages, end_offset, identity[0], identity[1], anchor_length, anchor_hash,
        warnings=tuple(warnings),
    )


def render_markdown(messages: Iterable[dict[str, Any]]) -> str:
    sections = []
    for message in messages:
        role = str(message.get("role", "unknown")).capitalize()
        content = str(message.get("content", "")).strip()
        if content:
            sections.append(f"## {role}\n\n{content}")
    return "\n\n".join(sections) + ("\n" if sections else "")
