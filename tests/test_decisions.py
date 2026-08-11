"""The `offered and declined` estimator, and the four states it stops pooling.

The old control arm was "runs that reached this node and did not take the edge",
which is four different things at once. Only one of them — the run was offered the
move and passed — is evidence about the move. The rest say the move was unavailable,
and since five of the seven guards read the same disk predicates the rubric scores,
"unavailable" is correlated with "the run was weak". Pooling them makes the guard a
selection mechanism on the outcome.
"""

from __future__ import annotations

import unittest

from src.archive import RunRecord
from src.decisions import (
    Decision,
    decisions_from,
    format_offered_payoffs,
    offered_payoffs,
)
from src.archive import DEFAULT_MIN_OBSERVATIONS
from src.stage_graph import REVISIT_EDGES
from src.utils import STAGES
from src.inference import (
    minimum_arms_for,
    paired_floor,
    unpaired_floor,
    unpaired_permutation,
)
from src.rubric import RUBRIC_VERSION


BACK = "06_analysis->05_experimentation"
FORWARD = "06_analysis->07_writing"
EIGHT = {f"0{n}_s": 0.0 for n in range(1, 9)}


def run(
    run_id: str,
    *,
    fitness: float,
    decisions: list[dict],
    provenance: str = "live",
    topology: str = "adaptive",
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness={key: fitness for key in EIGHT},
        topology=topology,
        provenance=provenance,
        route="",
        steps=1,
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="t",
        decisions=decisions,
    )


def decided(chose: str, offered: list[str], source: str = "06_analysis") -> dict:
    return {"source": source, "chose": chose, "offered": offered}


BOTH = ["05_experimentation", "07_writing"]


class ControlArmTests(unittest.TestCase):
    def test_a_run_that_was_never_offered_the_edge_is_not_a_control(self) -> None:
        """The whole point. A guard-blocked edge was not declined, and counting it as
        declined turns "this run's artifacts were missing" into "this edge pays"."""
        records = [
            run("took", fitness=0.60, decisions=[decided("05_experimentation", BOTH)]),
            run("declined", fitness=0.70, decisions=[decided("07_writing", BOTH)]),
            # Offered only the forward move — the revisit's guard was shut.
            run("never-offered", fitness=0.20, decisions=[decided("07_writing", ["07_writing"])]),
        ]
        payoff = offered_payoffs(decisions_from(records))[BACK]

        self.assertEqual((payoff.taken_n, payoff.declined_n), (1, 1))
        self.assertAlmostEqual(payoff.delta, -0.10, places=6)

    def test_the_old_arm_would_have_got_the_sign_backwards(self) -> None:
        """The same fixture, scored the old way, says the opposite.

        Six runs that never had the choice sit at 0.20; pooled into the control arm
        they drag its mean below the treatment's and the edge reads as a win.
        """
        offered_both = [
            run(f"took{i}", fitness=0.60, decisions=[decided("05_experimentation", BOTH)])
            for i in range(3)
        ] + [
            run(f"passed{i}", fitness=0.70, decisions=[decided("07_writing", BOTH)])
            for i in range(3)
        ]
        never = [
            run(f"blocked{i}", fitness=0.20, decisions=[decided("07_writing", ["07_writing"])])
            for i in range(6)
        ]

        payoff = offered_payoffs(decisions_from(offered_both + never))[BACK]
        self.assertLess(payoff.delta, 0.0)

        # What the run-level arm would have produced: every run that did not take it.
        old_control = [0.70] * 3 + [0.20] * 6
        old_delta = 0.60 - sum(old_control) / len(old_control)
        self.assertGreater(old_delta, 0.0)

    def test_a_bypassed_move_is_not_a_decision(self) -> None:
        records = [
            run("took", fitness=0.60, decisions=[decided("05_experimentation", BOTH)]),
            run("declined", fitness=0.70, decisions=[decided("07_writing", BOTH)]),
            run(
                "jumped",
                fitness=0.10,
                decisions=[{**decided("05_experimentation", BOTH), "bypassed": True}],
            ),
        ]
        payoff = offered_payoffs(decisions_from(records))[BACK]
        self.assertEqual((payoff.taken_n, payoff.declined_n), (1, 1))

    def test_a_visit_with_no_recorded_choice_set_is_excluded(self) -> None:
        """A record from before `offered` existed has an empty set, which is
        indistinguishable from "nothing else was available" and must not be read as
        it."""
        records = [
            run("legacy", fitness=0.9, decisions=[decided("05_experimentation", [])]),
            run("took", fitness=0.60, decisions=[decided("05_experimentation", BOTH)]),
            run("declined", fitness=0.70, decisions=[decided("07_writing", BOTH)]),
        ]
        self.assertEqual(len(decisions_from(records)), 2)

    def test_a_fake_run_contributes_no_decisions(self) -> None:
        records = [
            run("fake", fitness=0.99, provenance="fake", decisions=[decided("05_experimentation", BOTH)]),
        ]
        self.assertEqual(decisions_from(records), [])

    def test_arms_are_kept_within_a_comparability_basis(self) -> None:
        """A linear run and an adaptive run did not do the same work, and a basis
        with only one arm carries no contrast."""
        records = [
            run("took", fitness=0.60, decisions=[decided("05_experimentation", BOTH)]),
            run("declined", fitness=0.70, decisions=[decided("07_writing", BOTH)]),
            run(
                "other-topology",
                fitness=0.05,
                topology="linear",
                decisions=[decided("07_writing", BOTH)],
            ),
        ]
        payoff = offered_payoffs(decisions_from(records))[BACK]
        self.assertEqual((payoff.taken_n, payoff.declined_n), (1, 1))


class InferenceTests(unittest.TestCase):
    def test_the_unpaired_floor_is_two_over_the_binomial(self) -> None:
        self.assertAlmostEqual(unpaired_floor(3, 3), 0.1)
        self.assertAlmostEqual(unpaired_floor(6, 6), 2 / 924, places=6)
        self.assertEqual(unpaired_floor(0, 5), 1.0)

    def test_three_a_side_cannot_reach_five_percent(self) -> None:
        """Which is what `DEFAULT_MIN_OBSERVATIONS = 3` was licensing."""
        result = unpaired_permutation([0.9, 0.9, 0.9], [0.1, 0.1, 0.1])
        self.assertAlmostEqual(result.p_value, 0.1)
        self.assertFalse(result.attainable())
        self.assertIn("cannot reach", result.describe())

    def test_six_a_side_can(self) -> None:
        result = unpaired_permutation([0.9] * 6, [0.1] * 6)
        self.assertTrue(result.attainable())
        self.assertTrue(result.believable())

    def test_the_family_correction_is_applied(self) -> None:
        """Against the family the archive corrects over and no effect anywhere, the
        chance one clears an uncorrected 0.05 is about 66%. The best of many is not
        one test."""
        result = unpaired_permutation([0.9] * 6, [0.1] * 6)
        self.assertTrue(result.believable(family=1))
        self.assertFalse(result.believable(family=100))

    def test_the_derived_minimum_matches_the_arithmetic(self) -> None:
        # The family the archive actually corrects over, computed the same way it is
        # in `src.archive`. Pinning a literal here would keep passing after the graph
        # grew, which is the failure this whole module exists to make impossible.
        family = len(REVISIT_EDGES) + len(STAGES)
        size = minimum_arms_for(0.05, family=family)
        self.assertEqual(size, DEFAULT_MIN_OBSERVATIONS)
        self.assertLessEqual(unpaired_floor(size, size), 0.05 / family)
        self.assertGreater(unpaired_floor(size - 1, size - 1), 0.05 / family)

    def test_an_identical_pair_of_arms_is_not_significant(self) -> None:
        self.assertEqual(unpaired_permutation([0.5] * 4, [0.5] * 4).p_value, 1.0)

    def test_the_paired_floor_is_the_sign_flip_one(self) -> None:
        self.assertAlmostEqual(paired_floor(6), 2 / 64)


class ReportTests(unittest.TestCase):
    def test_a_row_that_cannot_reach_the_threshold_says_so(self) -> None:
        records = [
            run("took", fitness=0.9, decisions=[decided("05_experimentation", BOTH)]),
            run("declined", fitness=0.1, decisions=[decided("07_writing", BOTH)]),
        ]
        rendered = format_offered_payoffs(offered_payoffs(decisions_from(records)))
        self.assertIn("cannot reach", rendered)
        self.assertIn("reporting its sample size, not its effect", rendered)

    def test_an_empty_archive_says_why_it_is_empty(self) -> None:
        self.assertIn("predates `offered`", format_offered_payoffs({}))


class DecisionTests(unittest.TestCase):
    def test_an_edge_is_matched_on_both_ends(self) -> None:
        decision = Decision("r", "06_analysis", "07_writing", tuple(BOTH), 0.5, "b")
        self.assertTrue(decision.offered_edge(FORWARD))
        self.assertTrue(decision.took_edge(FORWARD))
        self.assertTrue(decision.offered_edge(BACK))
        self.assertFalse(decision.took_edge(BACK))
        self.assertFalse(decision.offered_edge("05_experimentation->06_analysis"))


if __name__ == "__main__":
    unittest.main()
