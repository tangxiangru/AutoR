"""Baseline competence and replication: what makes a `supported` verdict mean something.

Both failures these gates catch produce a clean-looking positive result. Beating
an untuned baseline measures the effort split, not the method. A single run
cannot separate an effect from variance. Neither is visible in the finished
artifacts, which is why they are gates rather than advice.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.experimental_protocol import (
    MIN_SEEDS_FOR_A_VERDICT,
    format_protocol_for_prompt,
    load_experimental_protocol,
    validate_experimental_protocol,
    validate_outcome_statistics,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, validate_stage_artifacts, write_text
from tests.prereg_support import write_experimental_protocol, write_validity_chain


STAGE_04 = next(stage for stage in STAGES if stage.number == 4)
STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)


class ProtocolTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def write_protocol(self, **overrides) -> None:
        payload = {
            "declared_at": "2026-04-08T00:00:00",
            "primary_metric": "held-out accuracy",
            "planned_seeds": 5,
            "baselines": [
                {
                    "name": "standard baseline",
                    "why_competent": "the established approach the method has to beat",
                    "tuning_budget": "the same search budget the method receives",
                }
            ],
        }
        payload.update(overrides)
        write_text(self.paths.experimental_protocol, json.dumps(payload))

    def write_outcome(self, statistics, verdict="supported") -> None:
        entry = {
            "id": "H1",
            "verdict": verdict,
            "rationale": "clears the rule",
            "evidence": ["results/metrics.json"],
        }
        if statistics is not None:
            entry["statistics"] = statistics
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps({"preregistration_digest": "x", "outcomes": [entry]}),
        )


class ProtocolDeclarationTest(ProtocolTestCase):
    def test_a_complete_protocol_passes(self) -> None:
        self.write_protocol()
        self.assertEqual(validate_experimental_protocol(self.paths), [])

    def test_a_missing_protocol_is_refused(self) -> None:
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("experimental_protocol.json" in problem for problem in problems), problems)

    def test_no_baseline_is_refused(self) -> None:
        self.write_protocol(baselines=[])
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("declares no baselines" in problem for problem in problems), problems)

    def test_a_baseline_with_no_competence_argument_is_refused(self) -> None:
        """A baseline nobody argued for is a strawman with a name."""
        self.write_protocol(
            baselines=[{"name": "weak thing", "why_competent": "", "tuning_budget": "none"}]
        )
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("why it is a competent comparison" in p for p in problems), problems)

    def test_a_baseline_with_no_tuning_budget_is_refused(self) -> None:
        self.write_protocol(
            baselines=[{"name": "thing", "why_competent": "standard", "tuning_budget": ""}]
        )
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("declares no tuning budget" in p for p in problems), problems)

    def test_no_primary_metric_is_refused(self) -> None:
        """Picking the metric after seeing results is the same defect as picking the hypothesis."""
        self.write_protocol(primary_metric="")
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("no primary_metric" in problem for problem in problems), problems)

    def test_planned_seeds_must_be_positive(self) -> None:
        self.write_protocol(planned_seeds=0)
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("planned_seeds" in problem for problem in problems), problems)

    def test_a_non_integer_seed_count_does_not_crash_the_gate(self) -> None:
        self.write_protocol(planned_seeds="five")
        problems = validate_experimental_protocol(self.paths)
        self.assertTrue(any("planned_seeds" in problem for problem in problems), problems)

    def test_the_prompt_renders_the_budget_and_forbids_metric_switching(self) -> None:
        self.write_protocol()
        protocol = load_experimental_protocol(self.paths)
        assert protocol is not None
        rendered = format_protocol_for_prompt(protocol)
        self.assertIn("standard baseline", rendered)
        self.assertIn("Tuning budget:", rendered)
        self.assertIn("do not switch to a metric that came out better", rendered)


class VerdictStatisticsTest(ProtocolTestCase):
    def test_a_verdict_with_full_statistics_passes(self) -> None:
        self.write_outcome({"n_seeds": 5, "dispersion": 0.01, "dispersion_type": "std"})
        self.assertEqual(validate_outcome_statistics(self.paths), [])

    def test_a_verdict_with_no_statistics_block_is_refused(self) -> None:
        self.write_outcome(None)
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("no `statistics` block" in problem for problem in problems), problems)

    def test_a_single_run_verdict_is_refused_without_a_justification(self) -> None:
        self.write_outcome({"n_seeds": 1, "dispersion": 0.0, "dispersion_type": "none"})
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("single run" in problem for problem in problems), problems)

    def test_a_single_run_verdict_passes_when_it_says_why(self) -> None:
        """Deterministic procedures exist. Saying so out loud is the requirement."""
        self.write_outcome(
            {
                "n_seeds": 1,
                "dispersion": 0.0,
                "dispersion_type": "none",
                "single_run_justification": "the procedure is deterministic given the fixed split",
            }
        )
        self.assertEqual(validate_outcome_statistics(self.paths), [])

    def test_an_unstated_dispersion_measure_is_refused(self) -> None:
        self.write_outcome({"n_seeds": 5, "dispersion": 0.01, "dispersion_type": ""})
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("dispersion_type" in problem for problem in problems), problems)

    def test_an_unknown_dispersion_measure_is_refused(self) -> None:
        self.write_outcome({"n_seeds": 5, "dispersion": 0.01, "dispersion_type": "vibes"})
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("expected one of" in problem for problem in problems), problems)

    def test_multiple_runs_reporting_no_dispersion_is_refused(self) -> None:
        self.write_outcome({"n_seeds": 5, "dispersion": 0.0, "dispersion_type": "none"})
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("no dispersion" in problem for problem in problems), problems)

    def test_a_boolean_is_not_a_seed_count(self) -> None:
        self.write_outcome({"n_seeds": True, "dispersion": 0.0, "dispersion_type": "std"})
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("positive integer" in problem for problem in problems), problems)

    def test_inconclusive_is_not_held_to_the_statistics_requirement(self) -> None:
        """Forcing statistics onto a hedge would push the run toward overclaiming."""
        self.write_outcome(None, verdict="inconclusive")
        self.assertEqual(validate_outcome_statistics(self.paths), [])

    def test_not_tested_is_not_held_to_the_statistics_requirement(self) -> None:
        self.write_outcome(None, verdict="not_tested")
        self.assertEqual(validate_outcome_statistics(self.paths), [])

    def test_a_refutation_is_held_to_the_same_bar_as_a_confirmation(self) -> None:
        """A refutation from one noisy run is as unfounded as a confirmation from one."""
        self.write_outcome(None, verdict="refuted")
        problems = validate_outcome_statistics(self.paths)
        self.assertTrue(any("no `statistics` block" in problem for problem in problems), problems)

    def test_the_replication_floor_is_more_than_one(self) -> None:
        self.assertGreater(MIN_SEEDS_FOR_A_VERDICT, 1)


class StageGateWiringTest(ProtocolTestCase):
    def test_stage_05_reports_a_missing_protocol(self) -> None:
        problems = validate_stage_artifacts(STAGE_05, self.paths)
        self.assertTrue(any("experimental_protocol.json" in p for p in problems), problems)

    def test_stage_04_is_not_held_to_the_protocol(self) -> None:
        """It is declared during design and enforced once experiments can run."""
        problems = validate_stage_artifacts(STAGE_04, self.paths)
        self.assertFalse(any("experimental_protocol" in p for p in problems), problems)

    def test_stage_06_reports_a_verdict_with_no_statistics(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"acc": 0.9}')
        write_validity_chain(self.paths)
        outcomes = json.loads(self.paths.hypothesis_outcomes.read_text(encoding="utf-8"))
        for entry in outcomes["outcomes"]:
            entry.pop("statistics", None)
        write_text(self.paths.hypothesis_outcomes, json.dumps(outcomes))

        problems = validate_stage_artifacts(STAGE_06, self.paths)
        self.assertTrue(any("no `statistics` block" in p for p in problems), problems)

    def test_a_fully_disciplined_run_clears_stage_06(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"acc": 0.9}')
        write_experimental_protocol(self.paths)
        write_validity_chain(self.paths)
        problems = [
            p
            for p in validate_stage_artifacts(STAGE_06, self.paths)
            if "protocol" in p or "statistics" in p or "hypothes" in p
        ]
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
