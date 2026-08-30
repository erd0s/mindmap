#!/usr/bin/env python3
"""Reapply the current deterministic scorer to a retained semantic report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_semantic_evals import (
    FIXTURES,
    ROOT,
    fixture_digest,
    package_is_dirty,
    package_revision,
    summarize,
)
from scripts.semantic_eval import SCORER_VERSION, load_fixture, score_fixture, seed_items


def rescore_report(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("schema_version") != 1 or not isinstance(report.get("results"), list):
        raise ValueError("input is not a semantic evaluation report")
    fixtures = {
        fixture["id"]: fixture
        for fixture in (load_fixture(path) for path in sorted(FIXTURES.glob("*.json")))
    }
    rescored = []
    for original in report["results"]:
        result = dict(original)
        fixture_id = str(result.get("fixture") or "")
        if fixture_id not in fixtures:
            raise ValueError(f"report uses unknown fixture {fixture_id!r}")
        fixture = fixtures[fixture_id]
        score = score_fixture(fixture, seed_items(fixture), result.get("items", []))
        execution_passed = bool(
            result.get(
                "execution_passed",
                not any(" exited " in problem for problem in result.get("problems", [])),
            )
        )
        checkpointed = bool(
            result.get("checkpointed", int(result.get("checkpoint_delta") or 0) > 0)
        )
        problems = list(score.problems)
        if not execution_passed:
            returncode = result.get("returncode")
            problems.append(
                f"{result.get('host')} exited {returncode}"
                if returncode is not None
                else f"{result.get('host')} execution failed"
            )
        if not checkpointed:
            problems.append("agent produced no new Mindmap checkpoint")
        failure_classes = []
        if not execution_passed:
            failure_classes.append("execution")
        if not checkpointed:
            failure_classes.append("checkpoint")
        if not score.passed:
            failure_classes.append("semantic")
        result.update(
            {
                "fixture_digest": fixture_digest(fixture),
                "scorer_version": SCORER_VERSION,
                "passed": not problems,
                "execution_passed": execution_passed,
                "checkpointed": checkpointed,
                "semantic_passed": score.passed,
                "failure_classes": failure_classes,
                "metrics": score.metrics,
                "matched": score.matched,
                "problems": problems,
            }
        )
        rescored.append(result)
    hosts = tuple(dict.fromkeys(str(result["host"]) for result in rescored))
    updated = dict(report)
    updated.update(
        {
            "harness_commit": package_revision(ROOT),
            "harness_dirty": package_is_dirty(ROOT),
            "scorer_version": SCORER_VERSION,
            "rescored": True,
            "summary": summarize(rescored, hosts),
            "results": rescored,
        }
    )
    return updated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        rescored = rescore_report(report)
        args.output.write_text(json.dumps(rescored, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    overall = rescored["summary"]["all"]
    print(
        f"Rescored {overall['trials']} trials: overall {overall['passed']}/"
        f"{overall['trials']}; executed {overall['executed']}/{overall['trials']}; "
        f"semantic {overall['semantic_passed']}/{overall['checkpointed']} checkpointed."
    )
    print(f"JSON report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
