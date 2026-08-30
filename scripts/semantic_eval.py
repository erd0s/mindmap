#!/usr/bin/env python3
"""Deterministic structural scoring for sanitized Mindmap semantic fixtures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VALID_STATES = {"planned", "open", "settled"}
VALID_RESUME_EXPECTATIONS = {"empty", "nonempty", "closed"}
SCORER_VERSION = 1


@dataclass(frozen=True)
class Score:
    passed: bool
    metrics: dict[str, float]
    matched: dict[str, str]
    problems: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "metrics": self.metrics,
            "matched": self.matched,
            "problems": self.problems,
        }


def load_fixture(path: str | Path) -> dict[str, Any]:
    fixture = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_fixture(fixture)
    return fixture


def validate_fixture(fixture: dict[str, Any]) -> None:
    if fixture.get("schema_version") != 1:
        raise ValueError("semantic fixture schema_version must be 1")
    for field in ("id", "description", "prompt", "seed_operations", "expected"):
        if field not in fixture:
            raise ValueError(f"semantic fixture requires {field}")
    if not isinstance(fixture["seed_operations"], list):
        raise ValueError("seed_operations must be an array")
    expected = fixture["expected"]
    nodes = expected.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("expected.nodes must be a non-empty array")
    keys: set[str] = set()
    for node in nodes:
        key = node.get("key")
        selector = node.get("selector")
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("every expected node requires a unique key")
        keys.add(key)
        if not isinstance(selector, dict) or not (
            isinstance(selector.get("id"), str)
            or (
                isinstance(selector.get("all_terms"), list)
                and selector["all_terms"]
                and all(isinstance(term, str) and term for term in selector["all_terms"])
            )
        ):
            raise ValueError(f"expected node {key} requires selector.id or selector.all_terms")
        state = node.get("state")
        if state is not None and state not in VALID_STATES:
            raise ValueError(f"expected node {key} has invalid state {state!r}")
        parent_keys = node.get("parent_keys")
        if parent_keys is not None and (
            not isinstance(parent_keys, list)
            or not parent_keys
            or not all(isinstance(parent_key, str) and parent_key for parent_key in parent_keys)
        ):
            raise ValueError(f"expected node {key} has invalid parent_keys")
        resume = node.get("resume")
        if resume is not None and resume not in VALID_RESUME_EXPECTATIONS:
            raise ValueError(f"expected node {key} has invalid resume expectation {resume!r}")
    reference = fixture.get("reference_items")
    if reference is not None and not isinstance(reference, list):
        raise ValueError("reference_items must be an array when supplied")


def _searchable(item: dict[str, Any]) -> str:
    return " ".join(
        str(item.get(field) or "")
        for field in ("id", "title", "summary", "resume")
    ).casefold()


def _match(selector: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(selector.get("id"), str):
        return [item for item in items if item.get("id") == selector["id"]]
    terms = [term.casefold() for term in selector["all_terms"]]
    return [item for item in items if all(term in _searchable(item) for term in terms)]


def _resume_satisfies(expectation: str, value: str) -> bool:
    normalized = value.strip().casefold()
    if expectation == "empty":
        return not normalized
    if expectation == "nonempty":
        return bool(normalized)
    if expectation == "closed":
        return not normalized or normalized.startswith(
            (
                "no ",
                "none",
                "nothing ",
                "reopen ",
                "complete",
                "done",
                "finished",
                "resolved",
                "settled",
            )
        )
    raise ValueError(f"unknown resume expectation {expectation!r}")


def score_fixture(
    fixture: dict[str, Any],
    before_items: list[dict[str, Any]],
    after_items: list[dict[str, Any]],
) -> Score:
    validate_fixture(fixture)
    expected = fixture["expected"]
    before = {str(item["id"]): item for item in before_items}
    after = {str(item["id"]): item for item in after_items}
    problems: list[str] = []
    matched: dict[str, str] = {}
    used_ids: set[str] = set()
    required_total = 0
    required_found = 0
    state_total = 0
    state_correct = 0
    parent_total = 0
    parent_correct = 0
    resume_total = 0
    resume_correct = 0
    transition_total = 0
    transition_correct = 0

    # Resolve semantic selectors before checking relationships so parent_key does
    # not depend on the order of expected.nodes in the fixture.
    for specification in expected["nodes"]:
        key = specification["key"]
        required = specification.get("required", True)
        required_total += int(required)
        candidates = [
            item for item in _match(specification["selector"], after_items)
            if str(item["id"]) not in used_ids
        ]
        if not candidates:
            if required:
                problems.append(f"missing required concept {key}")
            continue
        if len(candidates) > 1:
            problems.append(
                f"concept {key} matched multiple nodes: "
                + ", ".join(str(item["id"]) for item in candidates)
            )
            continue
        item = candidates[0]
        item_id = str(item["id"])
        matched[key] = item_id
        used_ids.add(item_id)
        required_found += int(required)

    for specification in expected["nodes"]:
        key = specification["key"]
        item_id = matched.get(key)
        if item_id is None:
            continue
        item = after[item_id]
        transition_ok = True
        if "from_state" in specification:
            transition_total += 1
            prior = before.get(item_id)
            if not prior or prior.get("state") != specification["from_state"]:
                transition_ok = False
                problems.append(
                    f"concept {key} did not begin {specification['from_state']}"
                )
        if "state" in specification:
            state_total += 1
            if item.get("state") == specification["state"]:
                state_correct += 1
            else:
                if "from_state" in specification:
                    transition_ok = False
                problems.append(
                    f"concept {key} state is {item.get('state')}, expected {specification['state']}"
                )
        if "from_state" in specification and transition_ok:
            transition_correct += 1
        expected_parent = specification.get("parent_id")
        parent_key = specification.get("parent_key")
        parent_keys = specification.get("parent_keys")
        if (
            expected_parent is not None
            or parent_key is not None
            or parent_keys is not None
            or specification.get("root")
        ):
            parent_total += 1
            expected_parents: list[str | None]
            if parent_keys is not None:
                expected_parents = [matched.get(value) for value in parent_keys]
                missing_parents = [
                    value
                    for value, resolved in zip(parent_keys, expected_parents)
                    if resolved is None
                ]
                if missing_parents:
                    problems.append(
                        f"concept {key} parent alternatives could not be matched: "
                        + ", ".join(missing_parents)
                    )
            elif parent_key is not None:
                expected_parents = [matched.get(parent_key)]
                if expected_parents[0] is None:
                    problems.append(f"concept {key} parent {parent_key} could not be matched")
            elif specification.get("root"):
                expected_parents = [None]
            else:
                expected_parents = [expected_parent]
            if item.get("parent_id") in expected_parents:
                parent_correct += 1
            else:
                problems.append(
                    f"concept {key} parent is {item.get('parent_id')!r}, "
                    f"expected one of {expected_parents!r}"
                )
        resume = specification.get("resume")
        if resume in VALID_RESUME_EXPECTATIONS:
            resume_total += 1
            correct = _resume_satisfies(resume, str(item.get("resume") or ""))
            if correct:
                resume_correct += 1
            else:
                problems.append(f"concept {key} resume should be {resume}")
        for forbidden in specification.get("resume_forbidden_terms", []):
            if forbidden.casefold() in str(item.get("resume") or "").casefold():
                problems.append(
                    f"concept {key} resume retained forbidden term {forbidden!r}"
                )

    unchanged_fields = ("parent_id", "title", "summary", "resume", "state", "kind")
    for item_id in expected.get("unchanged_ids", []):
        if item_id not in before or item_id not in after:
            problems.append(f"unchanged concept {item_id} is missing")
            continue
        changed_fields = [
            field for field in unchanged_fields
            if before[item_id].get(field) != after[item_id].get(field)
        ]
        if changed_fields:
            problems.append(
                f"concept {item_id} changed unexpectedly: {', '.join(changed_fields)}"
            )

    new_ids = set(after) - set(before)
    supported_new_ids = new_ids & used_ids
    minimum = int(expected.get("min_new_nodes", 0))
    maximum = expected.get("max_new_nodes")
    if len(new_ids) < minimum:
        problems.append(f"created {len(new_ids)} nodes, expected at least {minimum}")
    if maximum is not None and len(new_ids) > int(maximum):
        problems.append(f"created {len(new_ids)} nodes, expected at most {maximum}")
    if not expected.get("allow_unmatched_new_nodes", False):
        unmatched = sorted(new_ids - used_ids)
        if unmatched:
            problems.append("unsupported new concepts: " + ", ".join(unmatched))
    patterns = [re.compile(pattern, re.IGNORECASE) for pattern in expected.get("forbidden_title_patterns", [])]
    for item in after_items:
        for pattern in patterns:
            if pattern.search(str(item.get("title") or "")):
                problems.append(
                    f"concept {item['id']} has forbidden chronology-shaped title {item.get('title')!r}"
                )

    metrics = {
        "material_concept_recall": required_found / required_total if required_total else 1.0,
        "concept_precision": len(supported_new_ids) / len(new_ids) if new_ids else 1.0,
        "state_accuracy": state_correct / state_total if state_total else 1.0,
        "transition_accuracy": transition_correct / transition_total if transition_total else 1.0,
        "parent_accuracy": parent_correct / parent_total if parent_total else 1.0,
        "resume_accuracy": resume_correct / resume_total if resume_total else 1.0,
    }
    return Score(not problems, metrics, matched, problems)


def seed_items(fixture: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize fixture seed operations into snapshot-shaped items for scoring tests."""
    items = []
    for operation in fixture["seed_operations"]:
        if operation.get("op") != "upsert":
            continue
        items.append(
            {
                "id": operation["id"],
                "parent_id": operation.get("parent_id"),
                "title": operation["title"],
                "summary": operation.get("summary", ""),
                "resume": operation.get("resume", ""),
                "state": operation.get("state", "open"),
                "kind": operation.get("kind", "thread"),
                "revision": 1,
            }
        )
    return items
