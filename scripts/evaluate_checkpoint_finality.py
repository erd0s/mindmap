#!/usr/bin/env python3
"""Compare candidate checkpoint-finality signals on frozen cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "checkpoint-finality.json"


def age_threshold(case: dict[str, Any]) -> bool:
    return float(case["elapsed_seconds"]) > 60


def normalized_transcript_activity(case: dict[str, Any]) -> bool:
    return bool(case["assistant_transcript_changed"])


def tool_generation_with_legacy_fallback(case: dict[str, Any]) -> bool:
    checkpoint = int(case["checkpoint_generation"])
    current = int(case["current_generation"])
    if checkpoint > 0:
        return current > checkpoint
    return age_threshold(case)


def always_reconcile(_case: dict[str, Any]) -> bool:
    return True


STRATEGIES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "age-threshold": age_threshold,
    "normalized-transcript-activity": normalized_transcript_activity,
    "tool-generation-with-legacy-fallback": tool_generation_with_legacy_fallback,
    "always-reconcile": always_reconcile,
}


def main() -> int:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = fixture["cases"]
    print("Checkpoint finality strategy comparison")
    print("strategy\tcorrect\tfalse-positive\tfalse-negative")
    for name, strategy in STRATEGIES.items():
        correct = false_positive = false_negative = 0
        for case in cases:
            predicted = strategy(case)
            expected = bool(case["expected_reconcile"])
            correct += predicted == expected
            false_positive += predicted and not expected
            false_negative += expected and not predicted
        print(
            f"{name}\t{correct}/{len(cases)}\t{false_positive}\t{false_negative}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
