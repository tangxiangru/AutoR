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

**"Selects on" is a relation, so the refusal is keyed on the pair.** The half of these
tests below the first class is there because the refusal used to read the capability
alone, and a relation reduced to one of its arguments over-refuses on the other. The
same ratchet scored by a judge that runs after the workspace is finished is a sound
trial — the one `docs/self-improvement.md` asks for by name — and the report refused
it while printing "score the arms on a held-out judge or a benchmark", which is what
had just been done. Which measures exist is `DECLARED_OUTCOMES`; which capabilities
read each is on the measure; and a trial that could name a measure of its own would be
writing its own exemption, so an undeclared one is refused at construction.
"""

from __future__ import annotations

import unittest

from src.trials import (
    DECLARED_OUTCOMES,
    RCB_TOTAL,
    RUBRIC_TOTAL,
    SELECTS_ON_THE_OUTCOME,
    Outcome,
    Pair,
    TrialResult,
    format_trial_report,
    outcomes_free_of,
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


def result_for(
    capability: str, *, pairs: int = 6, outcome: Outcome = RUBRIC_TOTAL
) -> TrialResult:
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
        outcome=outcome,
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
        # "two-sided p: **" and not "- exact two-sided p: **": there are three p-lines
        # now — exact, sampled, and the one for differences that cancel — and a refusal
        # that names one of them would go green the day a refused trial grew to nineteen
        # pairs. The substring is the part all three share.
        self.assertNotIn("two-sided p: **", rendered)
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

    def test_the_rubric_outcome_carries_the_module_constant(self) -> None:
        """One rule, not two. `SELECTS_ON_THE_OUTCOME` is named by
        `docs/self-improvement.md` and by the module docstring of `src/trials.py`; the refusal now reads
        `RUBRIC_TOTAL.selected_on_by`. If those two ever hold different sets, the doc
        describes a gate that is not the one running."""
        self.assertEqual(RUBRIC_TOTAL.selected_on_by, SELECTS_ON_THE_OUTCOME)


class TheRefusalIsKeyedOnTheMeasureTests(unittest.TestCase):
    """The same capability, two measures, two answers — and only one of them refused."""

    def test_the_ratchet_is_reportable_against_a_measure_it_cannot_read(self) -> None:
        """The over-refusal this class exists for.

        `argmax` on `score.total` guarantees the win only while `score.total` is what
        gets printed. Scored by ResearchClawBench's judge — run after the workspace is
        finished, against a checklist no stage was shown — the ratchet can lose, so the
        difference is a measurement and the report has to produce one.
        """
        result = result_for("polish_rounds", outcome=RCB_TOTAL)
        self.assertFalse(result.circular)

        rendered = format_trial_report(result)
        self.assertNotIn("refused", rendered)
        self.assertIn("- mean difference: **", rendered)
        self.assertIn("- exact two-sided p: **", rendered)

    def test_the_same_capability_on_the_rubric_is_still_refused(self) -> None:
        """The other half of the pair, asserted beside it: widening the gate for one
        measure must not open it for the measure the mechanism does read."""
        self.assertTrue(result_for("polish_rounds", outcome=RUBRIC_TOTAL).circular)
        self.assertIn(
            "selects on the outcome measure",
            format_trial_report(result_for("polish_rounds", outcome=RUBRIC_TOTAL)),
        )

    def test_the_report_names_the_measure_the_number_came_from(self) -> None:
        """Two trials of one capability now have two possible readings, and the only
        thing that separates them is which instrument filled `stage_fitness`. It is
        printed above the number on both branches rather than inferred from the unit,
        which names a scale and not who assigned it."""
        self.assertIn(
            "- outcome: `rcb_total` — " + RCB_TOTAL.measured_by,
            format_trial_report(result_for("effort_tiers", outcome=RCB_TOTAL)),
        )
        self.assertIn(
            "- outcome: `rubric_total` — " + RUBRIC_TOTAL.measured_by,
            format_trial_report(result_for("polish_rounds")),
        )

    def test_the_refusal_lists_the_declared_measures_that_escape_it(self) -> None:
        """"Score it on something the ratchet does not read" is advice; the list is
        the answer. Derived from the registry the refusal itself fires off, so a
        measure added there appears here without anyone editing prose."""
        self.assertEqual([item.key for item in outcomes_free_of("polish_rounds")], ["rcb_total"])
        self.assertEqual(
            sorted(item.key for item in outcomes_free_of("effort_tiers")),
            sorted(DECLARED_OUTCOMES),
        )

        rendered = format_trial_report(result_for("polish_rounds"))
        self.assertIn("Declared here: `rcb_total`", rendered)
        # The measure it was just refused on is never in the list, and that needs no
        # filtering at the call site: it is in the list of measures that select on this
        # capability, which is the whole reason this branch ran.
        self.assertNotIn("`rubric_total` (", rendered)


class AnOutcomeIsDeclaredNotInventedTests(unittest.TestCase):
    """The exemption has to cost an edit to the registry, not a keyword argument.

    An outcome carries the capabilities that select on it, so an outcome nobody
    declared carries none and makes `circular` false for everything. That failure is
    silent in the direction that publishes: the report renders, the p-value is real
    arithmetic, and the only trace is a string in a call.
    """

    def test_an_undeclared_measure_is_refused_at_construction(self) -> None:
        invented = Outcome(
            key="held_out_judge",
            unit="points",
            measured_by="a judge nobody has written",
        )
        with self.assertRaises(ValueError) as caught:
            result_for("polish_rounds", outcome=invented)
        self.assertIn("not declared", str(caught.exception))
        self.assertIn("DECLARED_OUTCOMES", str(caught.exception))

    def test_a_declared_key_may_not_be_restated_with_a_softer_selector_set(self) -> None:
        """The subtler forgery, and the reason equality is checked and not just the key.

        `Outcome` is a value type, so a caller can rebuild `rubric_total` with an empty
        `selected_on_by` and hand it in. The key matches, the report header reads
        identically, and the ratchet's rubric-scored trial publishes a p-value.
        """
        softened = Outcome(
            key="rubric_total",
            unit=RUBRIC_TOTAL.unit,
            measured_by=RUBRIC_TOTAL.measured_by,
            selected_on_by=frozenset(),
        )
        self.assertFalse(softened.selects("polish_rounds"))
        with self.assertRaises(ValueError) as caught:
            result_for("polish_rounds", outcome=softened)
        self.assertIn("may not restate what selects on it", str(caught.exception))

    def test_the_check_survives_a_dataclasses_replace(self) -> None:
        """`rcb_trial.collect_rcb_pairs` rewrites the result with `replace` after
        pairing, which is the one construction path that does not go through
        `collect_pairs`. `__post_init__` runs there too, and this is what says so."""
        import dataclasses

        result = result_for("polish_rounds", outcome=RCB_TOTAL)
        with self.assertRaises(ValueError):
            dataclasses.replace(
                result,
                outcome=Outcome(key="rcb_total", unit="x", measured_by="y"),
            )


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


class ABareStringOutcomeIsRefusedTests(unittest.TestCase):
    """`outcome="rubric"` is the natural mistake and used to fail three frames away.

    It matters more than an ordinary type slip: the registry check exists because an
    outcome nobody declared has an empty `selected_on_by` and therefore exempts every
    capability from the circularity refusal. A `TypeError` from deep inside
    `__post_init__` reads as a bug in the module rather than as a rejected exemption.
    """

    def test_a_string_is_refused_with_the_registry_in_the_message(self) -> None:
        from src.trials import DECLARED_OUTCOMES

        with self.assertRaises(TypeError) as caught:
            TrialResult(
                capability="polish_rounds",
                control_arm="off",
                treatment_arm="on",
                pairs=(),
                outcome="rubric",
            )
        message = str(caught.exception)
        for key in DECLARED_OUTCOMES:
            self.assertIn(key, message)


if __name__ == "__main__":
    unittest.main()
