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
from scripts.semantic_eval import (
    SCORER_VERSION,
    fixture_steps,
    load_fixture,
    score_fixture,
    seed_items,
)


def _rescore_step(
    original: dict[str, Any],
    fixture: dict[str, Any],
    before_items: list[dict[str, Any]],
    host: str,
) -> dict[str, Any]:
    score = score_fixture(fixture, before_items, original.get("items", []))
    execution_passed = bool(
        original.get(
            "execution_passed",
            not any(" exited " in problem for problem in original.get("problems", [])),
        )
    )
    checkpointed = bool(
        original.get("checkpointed", int(original.get("checkpoint_delta") or 0) > 0)
    )
    problems = list(score.problems)
    if not execution_passed:
        returncode = original.get("returncode")
        problems.append(
            f"{host} exited {returncode}"
            if returncode is not None
            else f"{host} execution failed"
        )
    if not checkpointed:
        problems.append("agent produced no new Mindmap checkpoint")
    updated = dict(original)
    updated.update(
        {
            "passed": not problems,
            "execution_passed": execution_passed,
            "checkpointed": checkpointed,
            "semantic_passed": score.passed,
            "metrics": score.metrics,
            "matched": score.matched,
            "problems": problems,
        }
    )
    return updated


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
        steps = fixture_steps(fixture)
        original_steps = result.get("steps")
        if len(steps) > 1 and (
            not isinstance(original_steps, list) or len(original_steps) != len(steps)
        ):
            raise ValueError(
                f"report fixture {fixture_id!r} lacks the {len(steps)} retained step graphs "
                "required by the current fixture"
            )
        if isinstance(original_steps, list):
            before = seed_items(fixture)
            rescored_steps = []
            for step_fixture, old_step in zip(steps, original_steps):
                new_step = _rescore_step(
                    old_step, step_fixture, before, str(result.get("host"))
                )
                rescored_steps.append(new_step)
                before = new_step.get("items", [])
        else:
            rescored_steps = [
                _rescore_step(
                    result, steps[0], seed_items(fixture), str(result.get("host"))
                )
            ]
        execution_passed = all(step["execution_passed"] for step in rescored_steps)
        checkpointed = all(step["checkpointed"] for step in rescored_steps)
        semantic_passed = all(step["semantic_passed"] for step in rescored_steps)
        problems = []
        metrics: dict[str, list[float]] = {}
        for step in rescored_steps:
            prefix = f"{step.get('id')}: " if len(rescored_steps) > 1 else ""
            problems.extend(prefix + problem for problem in step["problems"])
            for metric, value in step["metrics"].items():
                metrics.setdefault(metric, []).append(value)
        failure_classes = []
        if not execution_passed:
            failure_classes.append("execution")
        if not checkpointed:
            failure_classes.append("checkpoint")
        if not semantic_passed:
            failure_classes.append("semantic")
        result.update(
            {
                "fixture_digest": fixture_digest(fixture),
                "scorer_version": SCORER_VERSION,
                "passed": not problems,
                "execution_passed": execution_passed,
                "checkpointed": checkpointed,
                "semantic_passed": semantic_passed,
                "failure_classes": failure_classes,
                "metrics": {
                    metric: sum(values) / len(values)
                    for metric, values in metrics.items()
                },
                "matched": {
                    str(step.get("id") or f"step-{index}"): step["matched"]
                    for index, step in enumerate(rescored_steps, start=1)
                },
                "problems": problems,
                "steps": rescored_steps,
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
