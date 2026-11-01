#!/usr/bin/env python3
"""Offline semantic-report helpers; live agent evaluation is paused."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "semantic"


def run(command, *, cwd, environment, timeout):
    return subprocess.run(command, cwd=cwd, env=environment, timeout=timeout, capture_output=True, text=True, check=False)


def package_revision(package_root: Path) -> str:
    completed = run(
        ["git", "rev-parse", "HEAD"],
        cwd=package_root,
        environment=os.environ.copy(),
        timeout=30,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


def package_is_dirty(package_root: Path) -> bool | None:
    completed = run(
        ["git", "status", "--porcelain"],
        cwd=package_root,
        environment=os.environ.copy(),
        timeout=30,
    )
    return bool(completed.stdout.strip()) if completed.returncode == 0 else None


def fixture_digest(fixture: dict[str, Any]) -> str:
    encoded = json.dumps(fixture, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def summarize(results: list[dict[str, Any]], hosts: tuple[str, ...]) -> dict[str, Any]:
    groups = {"all": results}
    groups.update(
        {host: [result for result in results if result["host"] == host] for host in hosts}
    )
    summary: dict[str, Any] = {}
    for name, group in groups.items():
        executed = [result for result in group if result.get("execution_passed")]
        checkpointed = [result for result in executed if result.get("checkpointed")]
        metrics: dict[str, dict[str, float]] = {}
        metric_names = sorted(
            {metric for result in checkpointed for metric in result.get("metrics", {})}
        )
        for metric in metric_names:
            values = [
                float(result["metrics"][metric])
                for result in checkpointed
                if metric in result.get("metrics", {})
            ]
            if values:
                metrics[metric] = {
                    "mean": sum(values) / len(values),
                    "minimum": min(values),
                }
        passed = sum(bool(result.get("passed")) for result in group)
        semantic_passed = sum(
            bool(result.get("semantic_passed")) for result in checkpointed
        )
        summary[name] = {
            "passed": passed,
            "trials": len(group),
            "pass_rate": passed / len(group) if group else 0.0,
            "executed": len(executed),
            "availability_rate": len(executed) / len(group) if group else 0.0,
            "checkpointed": len(checkpointed),
            "checkpoint_rate_given_execution": (
                len(checkpointed) / len(executed) if executed else 0.0
            ),
            "semantic_passed": semantic_passed,
            "semantic_pass_rate_given_checkpoint": (
                semantic_passed / len(checkpointed) if checkpointed else 0.0
            ),
            "metrics": metrics,
        }
    return summary


def main() -> int:
    raise SystemExit("Agent integration is paused; live plugin evaluation is disabled pending review.")


if __name__ == "__main__":
    raise SystemExit(main())
