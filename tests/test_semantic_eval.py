from __future__ import annotations

import copy
import unittest
from pathlib import Path

from scripts.compare_semantic_evals import compare_reports
from scripts.rescore_semantic_report import rescore_report
from scripts.semantic_eval import load_fixture, score_fixture, seed_items


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "semantic"


class SemanticEvaluationTests(unittest.TestCase):
    def fixtures(self):
        return sorted(FIXTURES.glob("*.json"))

    def test_reference_outputs_pass_every_fixture(self) -> None:
        paths = self.fixtures()
        self.assertGreaterEqual(len(paths), 5)
        for path in paths:
            with self.subTest(fixture=path.name):
                fixture = load_fixture(path)
                score = score_fixture(
                    fixture, seed_items(fixture), fixture["reference_items"]
                )
                self.assertTrue(score.passed, score.problems)
                self.assertEqual(score.metrics["material_concept_recall"], 1.0)

    def test_wrong_state_and_parent_fail_with_specific_evidence(self) -> None:
        fixture = load_fixture(FIXTURES / "workforce-main-and-sidequest.json")
        actual = copy.deepcopy(fixture["reference_items"])
        explorer = next(item for item in actual if item["id"] == "scenario-explorer")
        explorer["state"] = "open"
        explorer["parent_id"] = None
        score = score_fixture(fixture, seed_items(fixture), actual)
        self.assertFalse(score.passed)
        self.assertTrue(any("explorer state" in problem for problem in score.problems))
        self.assertTrue(any("explorer parent" in problem for problem in score.problems))

    def test_unsupported_or_chronology_shaped_nodes_fail(self) -> None:
        fixture = load_fixture(FIXTURES / "local-installation-closure.json")
        actual = copy.deepcopy(fixture["reference_items"])
        actual.append(
            {
                "id": "turn-9",
                "parent_id": "local-installation",
                "title": "Turn 9",
                "summary": "Transcript debris",
                "resume": "",
                "state": "settled",
                "kind": "note",
            }
        )
        score = score_fixture(fixture, seed_items(fixture), actual)
        self.assertFalse(score.passed)
        self.assertTrue(any("unsupported new concepts" in problem for problem in score.problems))
        self.assertTrue(any("chronology-shaped" in problem for problem in score.problems))

    def test_closed_resume_accepts_conditional_reopen_but_not_unfinished_work(self) -> None:
        fixture = load_fixture(FIXTURES / "local-installation-closure.json")
        for resume in (
            "",
            "No follow-up required.",
            "Nothing remains. Reopen only for a later release.",
            "Resolved. No action needed.",
            "Done. Reopen if new evidence appears.",
        ):
            with self.subTest(resume=resume):
                actual = copy.deepcopy(fixture["reference_items"])
                actual[0]["resume"] = resume
                self.assertTrue(
                    score_fixture(fixture, seed_items(fixture), actual).passed
                )
        unfinished = copy.deepcopy(fixture["reference_items"])
        unfinished[0]["resume"] = "Install and verify v0.3.0."
        score = score_fixture(fixture, seed_items(fixture), unfinished)
        self.assertFalse(score.passed)
        self.assertTrue(any("resume should be closed" in problem for problem in score.problems))

    def test_parent_matching_does_not_depend_on_fixture_order(self) -> None:
        fixture = load_fixture(FIXTURES / "stale-resume-reconciliation.json")
        fixture["expected"]["nodes"].reverse()
        score = score_fixture(fixture, seed_items(fixture), fixture["reference_items"])
        self.assertTrue(score.passed, score.problems)

    def test_declared_equivalent_parent_is_accepted(self) -> None:
        fixture = load_fixture(FIXTURES / "workforce-main-and-sidequest.json")
        actual = copy.deepcopy(fixture["reference_items"])
        saas = next(item for item in actual if item["id"] == "saas-access")
        saas["parent_id"] = "avery-handoff"
        score = score_fixture(fixture, seed_items(fixture), actual)
        self.assertTrue(score.passed, score.problems)

    def test_comparison_reports_improvement_and_regression(self) -> None:
        def report(label: str, passed: bool, state_accuracy: float):
            return {
                "schema_version": 1,
                "package": label,
                "scorer_version": 1,
                "results": [
                    {
                        "host": "codex",
                        "fixture": "closure",
                        "fixture_digest": "same-fixture",
                        "passed": passed,
                        "execution_passed": True,
                        "checkpointed": True,
                        "semantic_passed": passed,
                        "metrics": {"state_accuracy": state_accuracy},
                    }
                ],
            }

        improvement = compare_reports(
            report("baseline", False, 0.0), report("candidate", True, 1.0)
        )
        self.assertTrue(improvement["comparable"])
        self.assertEqual(improvement["comparisons"]["all"]["pass_rate_delta"], 1.0)
        self.assertEqual(improvement["regressions"], [])

        regression = compare_reports(
            report("baseline", True, 1.0), report("candidate", False, 0.0)
        )
        self.assertTrue(regression["regressions"])

    def test_retained_report_can_be_rescored_without_another_model_run(self) -> None:
        fixture = load_fixture(FIXTURES / "local-installation-closure.json")
        report = {
            "schema_version": 1,
            "package": "candidate",
            "scorer_version": 1,
            "results": [
                {
                    "host": "codex",
                    "fixture": fixture["id"],
                    "trial": 1,
                    "passed": False,
                    "checkpoint_delta": 1,
                    "items": fixture["reference_items"],
                    "problems": ["old scorer failure"],
                }
            ],
        }
        rescored = rescore_report(report)
        self.assertTrue(rescored["results"][0]["passed"])
        self.assertEqual(rescored["results"][0]["problems"], [])
        self.assertEqual(rescored["summary"]["all"]["semantic_passed"], 1)


if __name__ == "__main__":
    unittest.main()
