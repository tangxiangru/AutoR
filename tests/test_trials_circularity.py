"""A capability that selects on the outcome measure may not be trialled against it.

The first paired trial anyone tried to run in this repo was the champion ratchet:
`--evolve-rounds 0` against `2`, scored on the rubric. Twelve real runs were queued
before the circularity surfaced.

`EvolutionController.consider` promotes a polish round when `delta >= min_gain` and
reverts it otherwise, so the arm with rounds is `argmax` over drafts on
`score.total` — the same total `format_trial_report` prints. The treatment arm is
the maximum of several draws from the distribution the control arm draws from once.
It cannot lose. A generator of random drafts would show the same effect, and on a
real run it did: Stage 03 went 0.9231 to 1.0000 and Stage 04 0.9296 to 1.0000, both
in a single round.

The refusal replaces the report rather than annotating it. A reader shown
"+0.0736, p = 0.031" takes the number, and a caveat underneath does not undo that.
"""

from __future__ import annotations

import unittest

from src.trials import (
    SELECTS_ON_THE_OUTCOME,
    Pair,
    TrialResult,
    format_trial_report,
)
from src.archive import RunRecord


def record(run_id: str, *, arm: str, fitness: float) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        variant_id="baseline",
        rubric_version="2",
        edges={},
        stage_fitness={"03_study_design": fitness, "04_implementation": fitness},
        topology="adaptive",
        provenance="live",
        route="",
        steps=2,
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="2026-08-11T00:00:00",
        trial_id=run_id,
        capability="polish_rounds",
        arm=arm,
    )


def result_for(capability: str, *, pairs: int = 6) -> TrialResult:
    made = []
    for index in range(pairs):
        control = record(f"t{index}", arm="off", fitness=0.93)
        treatment = record(f"t{index}", arm="on", fitness=1.00)
        made.append(Pair(f"t{index}", control, treatment))
    return TrialResult(
        capability=capability,
        control_arm="off",
        treatment_arm="on",
        pairs=tuple(made),
    )


class ACircularTrialIsRefusedTests(unittest.TestCase):
    def test_the_ratchet_is_named_as_selecting_on_the_outcome(self) -> None:
        self.assertIn("polish_rounds", SELECTS_ON_THE_OUTCOME)
        self.assertIn("pareto_frontier", SELECTS_ON_THE_OUTCOME)

    def test_the_report_refuses_instead_of_reporting(self) -> None:
        rendered = format_trial_report(result_for("polish_rounds"))
        self.assertIn("selects on the outcome measure", rendered)

    def test_the_refusal_replaces_the_number_rather_than_annotating_it(self) -> None:
        """The whole point. A caveat under a p-value is not a refusal."""
        rendered = format_trial_report(result_for("polish_rounds"))
        # The report *lines*, not the words. The refusal prose says "a positive mean
        # difference would be arithmetic rather than evidence", which is the point
        # being made rather than the number being reported.
        self.assertNotIn("- mean difference: **", rendered)
        self.assertNotIn("- exact two-sided p: **", rendered)
        self.assertNotIn("Concentration:", rendered)

    def test_the_refusal_says_what_would_make_it_trialable(self) -> None:
        rendered = format_trial_report(result_for("polish_rounds"))
        self.assertIn("does not read", rendered)

    def test_a_capability_that_does_not_read_the_rubric_still_reports(self) -> None:
        """The guard must not swallow the capabilities that *can* be trialled.

        `--effort-tiers` changes which model writes a stage. It never reads the
        rubric to decide what to keep, so the rubric scores its output at arm's
        length and a paired difference means something.
        """
        rendered = format_trial_report(result_for("effort_tiers"))
        self.assertNotIn("selects on the outcome measure", rendered)
        self.assertIn("- mean difference: **", rendered)
        self.assertIn("- exact two-sided p: **", rendered)

    def test_the_circular_flag_tracks_the_constant(self) -> None:
        self.assertTrue(result_for("polish_rounds").circular)
        self.assertFalse(result_for("effort_tiers").circular)


class TheRatchetReallyIsArgmaxOnTheReportedTotalTests(unittest.TestCase):
    """The premise of the refusal, asserted against the code rather than assumed.

    If `consider` ever stopped selecting on `total` — if it became, say, a fixed
    number of rounds with the last one kept — the refusal would be wrong and this
    test is what should notice.
    """

    def test_a_losing_polish_round_is_reverted(self) -> None:
        import inspect

        from src.evolution import EvolutionController

        source = inspect.getsource(EvolutionController.consider)
        self.assertIn("delta >= self.config.min_gain", source)
        self.assertIn("_revert", source)
        self.assertIn("regressed", source)


if __name__ == "__main__":
    unittest.main()
