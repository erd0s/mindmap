#!/usr/bin/env python3
"""Create a blinded human-review packet from two semantic-evaluation reports."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path
from typing import Any

from scripts.run_semantic_evals import FIXTURES
from scripts.semantic_eval import load_fixture


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or not isinstance(report.get("results"), list):
        raise ValueError(f"{path} is not a semantic evaluation report")
    return report


def _selected_results(report: dict[str, Any], trial: int) -> list[dict[str, Any]]:
    selected = [result for result in report["results"] if result.get("trial") == trial]
    cells = {(str(result["host"]), str(result["fixture"])) for result in selected}
    expected = {
        (str(result["host"]), str(result["fixture"]))
        for result in report["results"]
    }
    if cells != expected:
        missing = sorted(expected - cells)
        raise ValueError(f"trial {trial} is missing report cells: {missing}")
    if len(selected) != len(cells):
        raise ValueError(f"trial {trial} contains duplicate host/fixture cells")
    return selected


def _one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _render_tree(items: list[dict[str, Any]]) -> str:
    by_parent: dict[str | None, list[dict[str, Any]]] = {}
    ids = {str(item["id"]) for item in items}
    for item in items:
        parent = item.get("parent_id")
        parent_key = str(parent) if parent is not None and str(parent) in ids else None
        by_parent.setdefault(parent_key, []).append(item)
    for children in by_parent.values():
        children.sort(key=lambda item: (int(item.get("sort_order") or 0), str(item["id"])))

    lines: list[str] = []

    def visit(item: dict[str, Any], depth: int) -> None:
        indent = "  " * depth
        lines.append(
            f"{indent}- [{item['id']}] {_one_line(item.get('title'))} "
            f"({item.get('state')}, {item.get('kind')})"
        )
        lines.append(f"{indent}  Summary: {_one_line(item.get('summary')) or '[empty]'}")
        lines.append(f"{indent}  Resume: {_one_line(item.get('resume')) or '[empty]'}")
        for child in by_parent.get(str(item["id"]), []):
            visit(child, depth + 1)

    for root in by_parent.get(None, []):
        visit(root, 0)
    return "\n".join(lines)


def prepare_packet(
    report_paths: list[Path], output_dir: Path, trial: int, seed: int
) -> dict[str, Any]:
    if output_dir.exists():
        raise ValueError(f"output directory already exists: {output_dir}")
    fixtures = {
        fixture["id"]: fixture
        for fixture in (load_fixture(path) for path in sorted(FIXTURES.glob("*.json")))
    }
    sources = []
    samples = []
    for path in report_paths:
        report = _load_report(path)
        source_index = len(sources)
        sources.append(
            {
                "path": str(path.resolve()),
                "sha256": _digest(path),
                "package": report.get("package"),
                "package_commit": report.get("package_commit"),
                "scorer_version": report.get("scorer_version"),
            }
        )
        for result in _selected_results(report, trial):
            fixture_id = str(result["fixture"])
            if fixture_id not in fixtures:
                raise ValueError(f"report uses unknown fixture {fixture_id!r}")
            samples.append(
                {
                    "source_index": source_index,
                    "package": report.get("package"),
                    "host": result["host"],
                    "fixture": fixture_id,
                    "trial": trial,
                    "situation": fixtures[fixture_id]["description"],
                    "items": result.get("items", []),
                }
            )

    random.Random(seed).shuffle(samples)
    output_dir.mkdir(parents=True)
    packet = [
        "# Blinded Mindmap cold-read packet",
        "",
        "Show each map for ten seconds, then hide it before collecting answers 1–4. "
        "Reveal it again for questions 5–6. Do not give the reviewer `key.json`.",
        "",
    ]
    answers = ["# Cold-read answer sheet", ""]
    key_samples = []
    for index, sample in enumerate(samples, start=1):
        code = f"MAP-{index:03d}"
        packet.extend(
            [
                f"## {code}",
                "",
                f"Situation: {sample['situation']}",
                "",
                "```text",
                _render_tree(sample["items"]),
                "```",
                "",
                "---",
                "",
            ]
        )
        answers.extend(
            [
                f"## {code}",
                "",
                "1. Governing intent:",
                "2. Settled work or decisions:",
                "3. Open or planned work:",
                "4. Re-entry point and next action:",
                "5. Confusing or contradictory element:",
                "6. Redundant, trivial, chronological, or unsupported node:",
                "",
            ]
        )
        key_samples.append(
            {
                "code": code,
                "source_index": sample["source_index"],
                "package": sample["package"],
                "host": sample["host"],
                "fixture": sample["fixture"],
                "trial": sample["trial"],
            }
        )

    (output_dir / "packet.md").write_text("\n".join(packet), encoding="utf-8")
    (output_dir / "answer-sheet.md").write_text("\n".join(answers), encoding="utf-8")
    key = {
        "schema_version": 1,
        "seed": seed,
        "trial": trial,
        "sources": sources,
        "samples": key_samples,
    }
    (output_dir / "key.json").write_text(
        json.dumps(key, indent=2) + "\n", encoding="utf-8"
    )
    return key


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs=2, type=Path, metavar="REPORT")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--trial", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260831)
    args = parser.parse_args()
    try:
        key = prepare_packet(args.reports, args.output_dir, args.trial, args.seed)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(f"Prepared {len(key['samples'])} blinded maps in {args.output_dir}")
    print(f"Reviewer packet: {args.output_dir / 'packet.md'}")
    print(f"Keep private: {args.output_dir / 'key.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
