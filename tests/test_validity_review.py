"""The adversarial pass: findings that must be answered, not noted.

The existing approval gate asks whether a stage did its work. This asks why the
result is wrong. The tests below are mostly about the response contract, because
that is where the value is: a critique nobody had to answer is a critique that
changes nothing, and it looks identical in the run directory to one that was
never raised.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.validity_review import (
    REVIEWED_STAGE_NUMBERS,
    RESPONSE_STATUSES,
    ValidityFinding,
    ValidityReviewer,
    format_findings_for_prompt,
    load_findings,
    reviewed_stage_for,
    validate_validity_response,
    validity_response_path,
    validity_review_path,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, validate_stage_artifacts, write_text


STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


class _FakeOperator:
    fake_mode = True


class ValidityTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def write_review(self, *findings: dict, stage_slug: str = "05_experimentation") -> None:
        write_text(
            validity_review_path(self.paths, stage_slug),
            json.dumps({"reviewed_stage": stage_slug, "findings": list(findings)}),
        )

    def a_finding(self, identifier: str = "V1", **overrides) -> dict:
        payload = {
            "id": identifier,
            "category": "confound",
            "severity": "critical",
            "finding": "Both conditions were tuned on the split that reports the headline number.",
            "why_it_matters": "The gap may be selection, not the intervention.",
            "what_would_settle_it": "Re-tune on a development split and re-report.",
        }
        payload.update(overrides)
        return payload

    def write_response(self, *responses: dict, stage_slug: str = "05_experimentation") -> None:
        write_text(
            validity_response_path(self.paths, stage_slug),
            json.dumps({"responses": list(responses)}),
        )

    def a_response(self, identifier: str = "V1", **overrides) -> dict:
        payload = {
            "id": identifier,
            "status": "addressed",
            "explanation": "Re-tuned both conditions on a held-out development split and re-ran.",
            "evidence": "results/retuned_metrics.json",
        }
        payload.update(overrides)
        return payload


class RoutingTest(ValidityTestCase):
    def test_stage_06_answers_stage_05(self) -> None:
        self.assertEqual(reviewed_stage_for(STAGE_06), "05_experimentation")

    def test_stage_07_answers_stage_06(self) -> None:
        self.assertEqual(reviewed_stage_for(STAGE_07), "06_analysis")

    def test_earlier_stages_owe_nothing(self) -> None:
        for stage in STAGES:
            if stage.number in (6, 7):
                continue
            with self.subTest(stage=stage.slug):
                self.assertIsNone(reviewed_stage_for(stage))

    def test_the_reviewed_stages_are_the_ones_with_a_result_to_attack(self) -> None:
        self.assertEqual(REVIEWED_STAGE_NUMBERS, (5, 6))


class ResponseContractTest(ValidityTestCase):
    def test_a_complete_response_passes(self) -> None:
        self.write_review(self.a_finding())
        self.write_response(self.a_response())
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])

    def test_an_unanswered_finding_is_refused(self) -> None:
        """The whole point: silence is not a disposition."""
        self.write_review(self.a_finding())
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("validity_response" in problem for problem in problems), problems)

    def test_answering_only_some_findings_is_refused(self) -> None:
        self.write_review(self.a_finding("V1"), self.a_finding("V2"))
        self.write_response(self.a_response("V1"))
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("V2" in problem for problem in problems), problems)

    def test_a_rebuttal_is_a_complete_answer(self) -> None:
        """Dismissing an objection with an argument is legitimate and must stay cheap."""
        self.write_review(self.a_finding())
        self.write_response(
            self.a_response(
                status="rebutted",
                explanation="Tuning used a separate development split; the reviewer misread the config.",
                evidence="",
            )
        )
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])

    def test_an_accepted_limitation_is_a_complete_answer(self) -> None:
        self.write_review(self.a_finding())
        self.write_response(
            self.a_response(
                status="accepted_limitation",
                explanation="The objection stands and this run cannot re-tune; recorded as a limitation.",
                evidence="",
            )
        )
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])

    def test_there_is_no_noted_status(self) -> None:
        self.write_review(self.a_finding())
        self.write_response(self.a_response(status="noted"))
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("expected one of" in problem for problem in problems), problems)
        self.assertNotIn("noted", RESPONSE_STATUSES)

    def test_an_empty_explanation_is_refused(self) -> None:
        self.write_review(self.a_finding())
        self.write_response(self.a_response(explanation="ok"))
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("no substantive explanation" in problem for problem in problems), problems)

    def test_addressed_must_point_at_something(self) -> None:
        self.write_review(self.a_finding())
        self.write_response(self.a_response(evidence=""))
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("points at nothing" in problem for problem in problems), problems)

    def test_answering_a_finding_nobody_raised_is_refused(self) -> None:
        """Otherwise a stage can look responsive by answering easy invented objections."""
        self.write_review(self.a_finding("V1"))
        self.write_response(self.a_response("V1"), self.a_response("V9"))
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("V9" in problem for problem in problems), problems)

    def test_a_review_that_raised_nothing_owes_nothing(self) -> None:
        self.write_review()
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])

    def test_no_review_at_all_owes_nothing(self) -> None:
        """A stage must not be blocked because the critique never ran."""
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])


class StageGateWiringTest(ValidityTestCase):
    def test_stage_06_is_blocked_by_an_unanswered_stage_05_finding(self) -> None:
        self.write_review(self.a_finding())
        problems = validate_stage_artifacts(STAGE_06, self.paths)
        self.assertTrue(any("validity_response" in problem for problem in problems), problems)

    def test_stage_05_is_not_blocked_by_its_own_review(self) -> None:
        self.write_review(self.a_finding())
        problems = validate_stage_artifacts(STAGE_05, self.paths)
        self.assertFalse(any("validity_response" in problem for problem in problems), problems)

    def test_stage_07_is_blocked_by_an_unanswered_stage_06_finding(self) -> None:
        self.write_review(self.a_finding(), stage_slug="06_analysis")
        problems = validate_stage_artifacts(STAGE_07, self.paths)
        self.assertTrue(any("validity_response" in problem for problem in problems), problems)


class ReviewerTest(ValidityTestCase):
    def test_the_fake_reviewer_writes_a_real_finding(self) -> None:
        """Fake mode has to exercise the loop, or the loop is untested end to end."""
        reviewer = ValidityReviewer(_FakeOperator())
        findings = reviewer.review(paths=self.paths, stage=STAGE_05, stage_markdown="# Stage 05")

        self.assertEqual(len(findings), 1)
        self.assertTrue(validity_review_path(self.paths, STAGE_05.slug).exists())
        self.assertEqual(load_findings(self.paths, STAGE_05.slug)[0].severity, "critical")

    def test_stages_with_no_result_to_attack_are_skipped(self) -> None:
        reviewer = ValidityReviewer(_FakeOperator())
        stage_03 = next(stage for stage in STAGES if stage.number == 3)
        self.assertEqual(reviewer.review(paths=self.paths, stage=stage_03, stage_markdown="x"), [])
        self.assertFalse(validity_review_path(self.paths, stage_03.slug).exists())

    def test_a_malformed_finding_is_dropped_rather_than_half_parsed(self) -> None:
        reviewer = ValidityReviewer(_FakeOperator())
        parsed = reviewer._parse(  # noqa: SLF001
            json.dumps({"findings": [{"id": "V1", "finding": ""}, {"id": "V2", "finding": "real"}]})
        )
        self.assertEqual([item.identifier for item in parsed], ["V2"])

    def test_an_unknown_category_falls_back_rather_than_being_dropped(self) -> None:
        """Losing a real objection to a taxonomy mismatch is the worse error."""
        reviewer = ValidityReviewer(_FakeOperator())
        parsed = reviewer._parse(  # noqa: SLF001
            json.dumps({"findings": [{"id": "V1", "category": "vibes", "finding": "something real"}]})
        )
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].category, "overclaim")

    def test_findings_wrapped_in_prose_are_still_read(self) -> None:
        reviewer = ValidityReviewer(_FakeOperator())
        parsed = reviewer._parse(  # noqa: SLF001
            'Here is my review:\n```json\n{"findings": [{"id": "V1", "finding": "real"}]}\n```\nDone.'
        )
        self.assertEqual(len(parsed), 1)

    def test_an_unparseable_response_yields_nothing_rather_than_crashing(self) -> None:
        reviewer = ValidityReviewer(_FakeOperator())
        self.assertEqual(reviewer._parse("no json here"), [])  # noqa: SLF001


class PromptRenderingTest(ValidityTestCase):
    def test_the_next_stage_is_shown_the_findings_and_the_response_format(self) -> None:
        self.write_review(self.a_finding())
        rendered = format_findings_for_prompt(self.paths, STAGE_06)

        self.assertIn("V1", rendered)
        self.assertIn("critical", rendered)
        self.assertIn("What would settle it", rendered)
        self.assertIn("validity_response_05_experimentation.json", rendered)
        self.assertIn("accepted_limitation", rendered)

    def test_a_stage_with_no_findings_gets_no_block(self) -> None:
        self.assertEqual(format_findings_for_prompt(self.paths, STAGE_06), "")

    def test_the_review_prompt_asks_for_the_mechanism_not_a_verdict(self) -> None:
        reviewer = ValidityReviewer(_FakeOperator())
        prompt = reviewer._build_prompt(  # noqa: SLF001
            paths=self.paths, stage=STAGE_05, stage_markdown="# Stage 05"
        )
        self.assertIn("explain why this result is wrong", prompt)
        self.assertIn("cannot approve, reject, or edit", prompt)
        self.assertIn("Raising nothing is a legitimate outcome", prompt)
        # It must not duplicate the completeness reviewer's job.
        self.assertIn("not assessing completeness", prompt)

    def test_the_review_prompt_carries_the_preregistration_and_protocol(self) -> None:
        """Without them the reviewer cannot check metric switching or baseline budgets."""
        write_text(self.paths.preregistration, '{"digest": "abc"}')
        write_text(self.paths.experimental_protocol, '{"primary_metric": "accuracy"}')
        reviewer = ValidityReviewer(_FakeOperator())
        prompt = reviewer._build_prompt(  # noqa: SLF001
            paths=self.paths, stage=STAGE_05, stage_markdown="# Stage 05"
        )
        self.assertIn("Preregistered Hypotheses", prompt)
        self.assertIn("Experimental Protocol", prompt)
        self.assertIn("primary_metric", prompt)


class ReviewerFailureTest(ValidityTestCase):
    def test_a_failed_reviewer_is_recorded_as_failed_not_as_clean(self) -> None:
        """An empty findings list from a crashed critique reads as "nothing wrong"."""
        reviewer = ValidityReviewer(_FakeOperator())
        reviewer._write_review(  # noqa: SLF001
            self.paths, STAGE_05, [], note="exit code 1", failed=True
        )
        payload = json.loads(validity_review_path(self.paths, STAGE_05.slug).read_text(encoding="utf-8"))
        self.assertTrue(payload["reviewer_failed"])
        self.assertIn("exit code 1", payload["note"])


if __name__ == "__main__":
    unittest.main()
