#!/usr/bin/env python3
"""Compare two repeated Mindmap semantic-evaluation reports."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def load_report(path: str | Path) -> dict[str, Any]:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("schema_version") != 1 or not isinstance(report.get("results"), list):
        raise ValueError(f"{path} is not a semantic evaluation report")
    return report


def _groups(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {"all": results}
    for result in results:
        groups.setdefault(str(result["host"]), []).append(result)
        groups.setdefault(
            f"{result['host']}/{result['fixture']}", []
        ).append(result)
    return groups


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    passed = sum(bool(result.get("passed")) for result in results)
    metric_names = sorted(
        {name for result in results for name in result.get("metrics", {})}
    )
    metrics = {}
    for name in metric_names:
        values = [
            float(result["metrics"][name])
            for result in results
            if name in result.get("metrics", {})
        ]
        if values:
            metrics[name] = {
                "mean": sum(values) / len(values),
                "minimum": min(values),
            }
    return {
        "trials": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "metrics": metrics,
    }


def compare_reports(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    problems: list[str] = []
    regressions: list[str] = []
    if baseline.get("scorer_version") != candidate.get("scorer_version"):
        problems.append("reports use different scorer versions")

    def fixture_versions(report: dict[str, Any]) -> dict[tuple[str, str], set[str]]:
        versions: dict[tuple[str, str], set[str]] = defaultdict(set)
        for result in report["results"]:
            versions[(str(result["host"]), str(result["fixture"]))].add(
                str(result.get("fixture_digest") or "")
            )
        return versions

    if fixture_versions(baseline) != fixture_versions(candidate):
        problems.append("reports do not use the same host/fixture matrix and fixture digests")

    baseline_groups = _groups(baseline["results"])
    candidate_groups = _groups(candidate["results"])
    if set(baseline_groups) != set(candidate_groups):
        problems.append("reports do not contain the same comparison groups")

    comparisons = {}
    for group in sorted(set(baseline_groups) & set(candidate_groups)):
        before = _summary(baseline_groups[group])
        after = _summary(candidate_groups[group])
        if before["trials"] != after["trials"]:
            problems.append(
                f"{group} has {before['trials']} baseline trials and {after['trials']} candidate trials"
            )
        pass_delta = after["pass_rate"] - before["pass_rate"]
        if pass_delta < 0:
            regressions.append(f"{group} pass rate regressed by {abs(pass_delta):.3f}")
        metric_deltas = {}
        shared_metrics = set(before["metrics"]) & set(after["metrics"])
        for metric in sorted(shared_metrics):
            mean_delta = after["metrics"][metric]["mean"] - before["metrics"][metric]["mean"]
            minimum_delta = (
                after["metrics"][metric]["minimum"]
                - before["metrics"][metric]["minimum"]
            )
            metric_deltas[metric] = {
                "mean": mean_delta,
                "minimum": minimum_delta,
            }
            if mean_delta < 0:
                regressions.append(
                    f"{group} {metric} mean regressed by {abs(mean_delta):.3f}"
                )
            if minimum_delta < 0:
                regressions.append(
                    f"{group} {metric} minimum regressed by {abs(minimum_delta):.3f}"
                )
        comparisons[group] = {
            "baseline": before,
            "candidate": after,
            "pass_rate_delta": pass_delta,
            "metric_deltas": metric_deltas,
        }
    return {
        "baseline": baseline.get("package"),
        "candidate": candidate.get("package"),
        "comparable": not problems,
        "problems": problems,
        "regressions": sorted(set(regressions)),
        "comparisons": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()
    try:
        comparison = compare_reports(
            load_report(args.baseline), load_report(args.candidate)
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.json:
        print(json.dumps(comparison, indent=2))
    else:
        print(f"Baseline: {comparison['baseline']}")
        print(f"Candidate: {comparison['candidate']}")
        overall = comparison["comparisons"].get("all")
        if overall:
            print(f"Pass-rate delta: {overall['pass_rate_delta']:+.3f}")
            for metric, delta in overall["metric_deltas"].items():
                print(
                    f"{metric}: mean {delta['mean']:+.3f}, "
                    f"minimum {delta['minimum']:+.3f}"
                )
        for problem in comparison["problems"]:
            print(f"NOT COMPARABLE: {problem}")
        for regression in comparison["regressions"]:
            print(f"REGRESSION: {regression}")
    if not comparison["comparable"]:
        return 2
    if args.fail_on_regression and comparison["regressions"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
