"""The scientific-validity chain: freeze, adjudicate, trace.

These tests are mostly about what the gates *reject*. A validity gate that only
passes valid input is indistinguishable from no gate at all, and the failures
being prevented here — a hypothesis rewritten to fit the result, a verdict with
nothing behind it, a confirmatory claim resting on a refuted prediction — all
look completely normal in the finished artifacts.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.preregistration import (
    amend_preregistration,
    format_preregistration_for_prompt,
    freeze_preregistration,
    hypothesis_manifest_digest,
    load_preregistration,
    supported_hypothesis_ids,
    validate_claim_provenance,
    validate_hypothesis_outcomes,
    validate_preregistration,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, validate_stage_artifacts, write_text


STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


def _manifest(statement: str = "Retrieval raises accuracy by at least 8 points.", rule: str = "supported if the gap exceeds 8 points; refuted otherwise.") -> dict:
    return {
        "generated_at": "2026-04-08T00:00:00",
        "theoretical_propositions": [
            {"id": "T1", "type": "theoretical", "statement": "Context fragmentation is the mechanism."}
        ],
        "empirical_hypotheses": [
            {"id": "H1", "type": "empirical", "statement": statement, "decision_rule": rule}
        ],
        "paper_claims": [
            {"id": "C1", "type": "paper_claim", "statement": "Retrieval is a practical fix."}
        ],
    }


class PreregistrationTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.results_dir / "metrics.json", '{"baseline": 0.61, "treatment": 0.74}')

    def write_manifest(self, **kwargs) -> None:
        write_text(self.paths.hypothesis_manifest, json.dumps(_manifest(**kwargs)))

    def write_outcomes(self, verdict: str = "supported", evidence=("results/metrics.json",), digest=None, rationale="clears the rule") -> None:
        prereg = load_preregistration(self.paths)
        assert prereg is not None
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps(
                {
                    "generated_at": "2026-04-08T00:00:00",
                    "preregistration_digest": digest if digest is not None else prereg.digest,
                    "outcomes": [
                        {
                            "id": "H1",
                            "verdict": verdict,
                            "rationale": rationale,
                            "evidence": list(evidence),
                        }
                    ],
                }
            ),
        )

    def write_provenance(self, status="confirmatory", hypothesis_id="H1", evidence=("results/metrics.json",)) -> None:
        write_text(
            self.paths.claim_provenance,
            json.dumps(
                {
                    "claims": [
                        {
                            "claim": "Retrieval raises accuracy.",
                            "status": status,
                            "hypothesis_id": hypothesis_id,
                            "evidence": list(evidence),
                        }
                    ]
                }
            ),
        )


class FreezingTest(PreregistrationTestCase):
    def test_freezing_captures_the_hypotheses_and_their_decision_rules(self) -> None:
        self.write_manifest()
        prereg = freeze_preregistration(self.paths)

        assert prereg is not None
        self.assertEqual(prereg.adjudicated_ids, ["H1"])
        self.assertTrue(prereg.digest)
        self.assertIn("supported if the gap exceeds 8 points", prereg.to_dict()["hypotheses"][1]["decision_rule"])
        self.assertTrue(self.paths.preregistration.exists())

    def test_freezing_twice_does_not_move_the_frozen_set(self) -> None:
        """The second call is the dangerous one: it happens on every resume."""
        self.write_manifest()
        first = freeze_preregistration(self.paths)
        assert first is not None

        self.write_manifest(statement="Retrieval raises accuracy by at least 1 point.")
        second = freeze_preregistration(self.paths)

        assert second is not None
        self.assertEqual(second.digest, first.digest)
        self.assertIn("8 points", second.hypotheses[1].statement)

    def test_a_run_with_no_hypotheses_cannot_freeze(self) -> None:
        self.assertIsNone(freeze_preregistration(self.paths))

    def test_the_digest_ignores_the_timestamp_and_the_self_declared_status(self) -> None:
        """Re-running Stage 02 with no change of substance is not tampering."""
        self.write_manifest()
        before = hypothesis_manifest_digest(self.paths)

        payload = _manifest()
        payload["generated_at"] = "2026-12-25T00:00:00"
        payload["empirical_hypotheses"][0]["status"] = "confirmed"
        write_text(self.paths.hypothesis_manifest, json.dumps(payload))

        self.assertEqual(hypothesis_manifest_digest(self.paths), before)

    def test_the_digest_moves_when_a_statement_changes(self) -> None:
        self.write_manifest()
        before = hypothesis_manifest_digest(self.paths)
        self.write_manifest(statement="Retrieval changes accuracy somehow.")
        self.assertNotEqual(hypothesis_manifest_digest(self.paths), before)


class TamperTest(PreregistrationTestCase):
    def test_rewriting_a_hypothesis_after_the_freeze_is_a_validation_error(self) -> None:
        """The headline case: the hypothesis becomes whatever the result supports."""
        self.write_manifest()
        freeze_preregistration(self.paths)
        self.assertEqual(validate_preregistration(self.paths), [])

        self.write_manifest(statement="Retrieval changes accuracy by some amount.")

        problems = validate_preregistration(self.paths)
        self.assertTrue(
            any("no amendment was recorded" in problem for problem in problems), problems
        )

    def test_a_recorded_amendment_makes_the_revision_legitimate(self) -> None:
        self.write_manifest()
        freeze_preregistration(self.paths)
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")

        amended = amend_preregistration(self.paths, "Stage 02 re-run after rollback.")

        assert amended is not None
        self.assertEqual(len(amended.amendments), 1)
        self.assertEqual(amended.amendments[0]["reason"], "Stage 02 re-run after rollback.")
        self.assertIn("3 points", amended.hypotheses[1].statement)
        self.assertEqual(validate_preregistration(self.paths), [])

    def test_the_amendment_keeps_the_superseded_digest(self) -> None:
        """Otherwise the record cannot show what the run originally predicted."""
        self.write_manifest()
        original = freeze_preregistration(self.paths)
        assert original is not None
        self.write_manifest(statement="Retrieval raises accuracy by at least 3 points.")

        amended = amend_preregistration(self.paths, "revised")

        assert amended is not None
        self.assertEqual(amended.amendments[0]["previous_digest"], original.digest)
        self.assertNotEqual(amended.digest, original.digest)

    def test_amending_with_no_change_records_nothing(self) -> None:
        self.write_manifest()
        freeze_preregistration(self.paths)
        amended = amend_preregistration(self.paths, "no-op")
        assert amended is not None
        self.assertEqual(amended.amendments, [])

    def test_a_hypothesis_with_no_decision_rule_is_refused(self) -> None:
        self.write_manifest(rule="")
        freeze_preregistration(self.paths)
        problems = validate_preregistration(self.paths)
        self.assertTrue(any("has no decision rule" in problem for problem in problems), problems)

    def test_a_run_that_never_declared_hypotheses_is_named_as_such(self) -> None:
        problems = validate_preregistration(self.paths)
        self.assertTrue(any("no hypotheses on record" in problem for problem in problems), problems)


class AdjudicationTest(PreregistrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_manifest()
        freeze_preregistration(self.paths)

    def test_a_complete_adjudication_passes(self) -> None:
        self.write_outcomes()
        self.assertEqual(validate_hypothesis_outcomes(self.paths), [])

    def test_a_missing_outcomes_file_is_refused(self) -> None:
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("hypothesis_outcomes.json" in problem for problem in problems), problems)

    def test_omitting_a_hypothesis_is_refused(self) -> None:
        """Silence about an inconvenient hypothesis is the cheap way to hide a refutation."""
        prereg = load_preregistration(self.paths)
        assert prereg is not None
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps({"preregistration_digest": prereg.digest, "outcomes": []}),
        )
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("no verdict for preregistered hypothesis H1" in p for p in problems), problems)

    def test_a_verdict_against_a_different_hypothesis_set_is_refused(self) -> None:
        self.write_outcomes(digest="0" * 64)
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("different hypothesis set" in problem for problem in problems), problems)

    def test_support_with_no_evidence_is_refused(self) -> None:
        self.write_outcomes(evidence=())
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("with no evidence" in problem for problem in problems), problems)

    def test_support_citing_a_file_that_does_not_exist_is_refused(self) -> None:
        self.write_outcomes(evidence=("results/imaginary.json",))
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("no such file exists" in problem for problem in problems), problems)

    def test_an_unknown_verdict_word_is_refused(self) -> None:
        self.write_outcomes(verdict="probably")
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("expected one of" in problem for problem in problems), problems)

    def test_adjudicating_a_hypothesis_nobody_preregistered_is_refused(self) -> None:
        prereg = load_preregistration(self.paths)
        assert prereg is not None
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps(
                {
                    "preregistration_digest": prereg.digest,
                    "outcomes": [
                        {"id": "H1", "verdict": "supported", "rationale": "ok", "evidence": ["results/metrics.json"]},
                        {"id": "H9", "verdict": "supported", "rationale": "ok", "evidence": ["results/metrics.json"]},
                    ],
                }
            ),
        )
        problems = validate_hypothesis_outcomes(self.paths)
        self.assertTrue(any("H9" in problem and "not a preregistered" in problem for problem in problems), problems)

    def test_not_tested_needs_no_evidence(self) -> None:
        """A hypothesis the run never reached is a legitimate, recordable outcome."""
        self.write_outcomes(verdict="not_tested", evidence=(), rationale="the experiment never ran")
        self.assertEqual(validate_hypothesis_outcomes(self.paths), [])

    def test_a_refutation_is_a_valid_complete_analysis(self) -> None:
        self.write_outcomes(verdict="refuted", rationale="the gap was 2 points, below the rule's 8")
        self.assertEqual(validate_hypothesis_outcomes(self.paths), [])
        self.assertEqual(supported_hypothesis_ids(self.paths), set())


class ClaimProvenanceTest(PreregistrationTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.write_manifest()
        freeze_preregistration(self.paths)

    def test_a_confirmatory_claim_on_a_supported_hypothesis_passes(self) -> None:
        self.write_outcomes(verdict="supported")
        self.write_provenance()
        self.assertEqual(validate_claim_provenance(self.paths), [])

    def test_a_confirmatory_claim_on_a_refuted_hypothesis_is_refused(self) -> None:
        """The whole point. The paper may not claim what the run failed to show."""
        self.write_outcomes(verdict="refuted", rationale="gap below the rule")
        self.write_provenance()
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("is not `supported`" in problem for problem in problems), problems)

    def test_the_same_finding_may_be_reported_as_exploratory(self) -> None:
        self.write_outcomes(verdict="refuted", rationale="gap below the rule")
        self.write_provenance(status="exploratory", hypothesis_id="")
        self.assertEqual(validate_claim_provenance(self.paths), [])

    def test_a_confirmatory_claim_with_no_hypothesis_is_refused(self) -> None:
        self.write_outcomes()
        self.write_provenance(hypothesis_id="")
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("names no hypothesis" in problem for problem in problems), problems)

    def test_a_claim_citing_an_unpreregistered_hypothesis_is_refused(self) -> None:
        self.write_outcomes()
        self.write_provenance(hypothesis_id="H7")
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("not preregistered" in problem for problem in problems), problems)

    def test_a_claim_with_no_evidence_is_refused(self) -> None:
        self.write_outcomes()
        self.write_provenance(evidence=())
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("cites no evidence" in problem for problem in problems), problems)

    def test_an_unknown_status_word_is_refused(self) -> None:
        self.write_outcomes()
        self.write_provenance(status="probably")
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("expected one of" in problem for problem in problems), problems)

    def test_a_missing_provenance_file_is_refused(self) -> None:
        self.write_outcomes()
        problems = validate_claim_provenance(self.paths)
        self.assertTrue(any("claim_provenance.json" in problem for problem in problems), problems)


class StageGateWiringTest(PreregistrationTestCase):
    """The checks above only matter if the stage gates actually call them."""

    def test_stage_05_reports_a_run_with_no_hypotheses(self) -> None:
        problems = validate_stage_artifacts(STAGE_05, self.paths)
        self.assertTrue(any("no hypotheses on record" in problem for problem in problems), problems)

    def test_stage_06_reports_a_missing_adjudication(self) -> None:
        self.write_manifest()
        freeze_preregistration(self.paths)
        problems = validate_stage_artifacts(STAGE_06, self.paths)
        self.assertTrue(any("hypothesis_outcomes.json" in problem for problem in problems), problems)

    def test_stage_07_reports_missing_claim_provenance(self) -> None:
        self.write_manifest()
        freeze_preregistration(self.paths)
        self.write_outcomes()
        problems = validate_stage_artifacts(STAGE_07, self.paths)
        self.assertTrue(any("claim_provenance.json" in problem for problem in problems), problems)

    def test_stages_before_05_are_not_held_to_the_chain(self) -> None:
        """Hypotheses are not frozen until the design and code are settled."""
        for stage in STAGES:
            if stage.number >= 5:
                continue
            with self.subTest(stage=stage.slug):
                problems = validate_stage_artifacts(stage, self.paths)
                self.assertFalse(
                    any("hypotheses" in problem or "preregistration" in problem for problem in problems),
                    problems,
                )


class PromptRenderingTest(PreregistrationTestCase):
    def test_the_prompt_says_the_set_is_frozen_and_refutation_is_allowed(self) -> None:
        """The gate catches tampering; the prompt has to stop it being attempted."""
        self.write_manifest()
        prereg = freeze_preregistration(self.paths)
        assert prereg is not None

        rendered = format_preregistration_for_prompt(prereg)

        self.assertIn("**H1**", rendered)
        self.assertIn("Decision rule:", rendered)
        self.assertIn("may not edit", rendered)
        self.assertIn("record it as refuted", rendered)
        # Theoretical propositions and paper claims are not adjudicated here. Both ids are
        # matched as the prompt renders them, `**T1**`, rather than as bare substrings: the
        # header carries an ISO timestamp, so a bare "T1" also matches the "…-11T10:…" in
        # every prompt frozen between 10:00 and 19:59, and this test failed for ten hours
        # of each day rather than when the behaviour it describes broke.
        self.assertNotIn("**T1**", rendered)


if __name__ == "__main__":
    unittest.main()
