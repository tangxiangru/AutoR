"""Paired trials: the arithmetic, and the four things it refuses to compute.

The refusals are the point. A paired design is easy to get right and easy to make
say something it has not shown — by comparing arms that measured different work, by
reporting a total whose whole movement is one gameable criterion, or by calling a
result "not significant" when the sample could never have produced significance.
"""

from __future__ import annotations

import unittest

from src.archive import RunRecord, TrialTag
from src.rubric import RUBRIC_VERSION
from src.trials import (
    MIN_PAIRS_FOR_SIGNIFICANCE,
    Pair,
    collect_pairs,
    format_all_trials,
    format_trial_report,
    min_attainable_concentration,
    min_attainable_p,
    sign_flip_p,
)


def run(
    trial: str,
    arm: str,
    *,
    stages: dict[str, float],
    criteria: dict[str, float] | None = None,
    capability: str = "effort_tiers",
    provenance: str = "live",
) -> RunRecord:
    return RunRecord(
        run_id=f"{trial}-{arm}",
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness=dict(stages),
        topology="adaptive",
        provenance=provenance,
        route="",
        steps=len(stages),
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="t",
        criterion_fitness=dict(criteria or {}),
        trial_id=trial,
        capability=capability,
        arm=arm,
    )


EIGHT = [f"0{n}_s" for n in range(1, 9)]


def flat(value: float, stages=EIGHT) -> dict[str, float]:
    return {slug: value for slug in stages}


def paired(count: int, control: float, treatment: float, **kwargs) -> list[RunRecord]:
    records: list[RunRecord] = []
    for index in range(count):
        trial = f"g{index}"
        records.append(run(trial, "off", stages=flat(control), **kwargs.get("control_extra", {})))
        records.append(run(trial, "on", stages=flat(treatment), **kwargs.get("treatment_extra", {})))
    return records


class SignFlipTests(unittest.TestCase):
    def test_the_floor_is_two_over_two_to_the_n(self) -> None:
        self.assertAlmostEqual(min_attainable_p(3), 0.25)
        self.assertAlmostEqual(min_attainable_p(5), 0.0625)
        self.assertAlmostEqual(min_attainable_p(6), 0.03125)
        self.assertEqual(min_attainable_p(0), 1.0)

    def test_a_unanimous_result_hits_the_floor_exactly(self) -> None:
        """Six pairs all favouring the treatment is the most six pairs can say."""
        self.assertAlmostEqual(sign_flip_p([0.1] * 6), min_attainable_p(6))

    def test_below_six_pairs_nothing_can_reach_significance(self) -> None:
        """Not a convention — arithmetic. Reporting "p = 0.25, not significant" for
        five unanimous pairs invites the reading that the capability was tested and
        found wanting, when the sample could not have shown anything."""
        for pairs in range(1, MIN_PAIRS_FOR_SIGNIFICANCE):
            self.assertGreater(sign_flip_p([0.5] * pairs), 0.05)

    def test_a_tie_is_neutral_to_the_p_and_widens_the_gap_to_the_floor(self) -> None:
        """Keeping ties is right, but not for the reason it first looks like.

        Under a permutation test on the mean a tie is neutral: flipping its sign
        changes no mean, so the p is identical either way. That is *not* the
        classical sign test, where dropping ties shrinks n and moves the answer.

        What keeping them changes is the gap to the floor, and that gap is the
        signal. Six pairs of which two tied report p = 0.125 against a floor of
        0.031 — visibly less than six pairs could have said. Dropped, the same
        sample would report n = 4, floor 0.125, achieved 0.125, and look maximally
        informative.
        """
        four = [0.1] * 4
        six_with_ties = four + [0.0, 0.0]

        self.assertAlmostEqual(sign_flip_p(six_with_ties), sign_flip_p(four))
        self.assertAlmostEqual(sign_flip_p(four), min_attainable_p(4))
        self.assertGreater(sign_flip_p(six_with_ties), min_attainable_p(6))

    def test_an_effect_that_is_all_noise_is_not_significant(self) -> None:
        self.assertGreater(sign_flip_p([0.3, -0.28, 0.31, -0.29, 0.3, -0.3]), 0.5)

    def test_no_difference_at_all_is_p_one(self) -> None:
        self.assertEqual(sign_flip_p([]), 1.0)
        self.assertEqual(sign_flip_p([0.0, 0.0]), 1.0)


class PairTests(unittest.TestCase):
    def test_the_difference_is_taken_over_the_stages_both_arms_measured(self) -> None:
        """The composition bias, inside a pair.

        Later stages are scored on strictly more criteria, so an arm that stopped
        early scores higher *for stopping early*. Comparing each arm's own mean would
        reward a capability for making runs give up — the same bias
        `comparability_basis` removes between runs, reappearing within one.
        """
        pair = Pair("g1", run("g1", "off", stages=flat(0.70)), run("g1", "on", stages=flat(0.75, EIGHT[:3])))

        self.assertEqual(pair.shared_stages, tuple(EIGHT[:3]))
        self.assertAlmostEqual(pair.difference, 0.05, places=6)
        self.assertFalse(pair.same_shape)

    def test_a_shape_change_is_counted_rather_than_folded_in(self) -> None:
        """That a capability changes how far a run gets is a result. Averaging it
        into a mean over shared stages would hide the thing worth reporting."""
        result = collect_pairs(
            [
                run("g1", "off", stages=flat(0.70)),
                run("g1", "on", stages=flat(0.70, EIGHT[:4])),
                run("g2", "off", stages=flat(0.70)),
                run("g2", "on", stages=flat(0.70)),
            ],
            capability="effort_tiers",
            control_arm="off",
            treatment_arm="on",
        )
        self.assertEqual((result.n, result.shape_changes), (2, 1))
        self.assertAlmostEqual(result.mean_difference, 0.0, places=6)
        self.assertIn("did not reach the same stages", format_trial_report(result))


class CollectionTests(unittest.TestCase):
    def collect(self, records):
        return collect_pairs(
            records, capability="effort_tiers", control_arm="off", treatment_arm="on"
        )

    def test_a_pair_needs_both_arms(self) -> None:
        result = self.collect(
            [run("g1", "off", stages=flat(0.7)), run("g2", "on", stages=flat(0.8))]
        )
        self.assertEqual(result.n, 0)
        self.assertEqual(len(result.excluded), 2)
        self.assertIn("no `on` arm", result.excluded[0][1])

    def test_a_fake_arm_disqualifies_the_pair(self) -> None:
        """A fake operator's scores measure the script. One fake arm makes the
        difference a measurement of nothing, so the pair goes rather than the arm."""
        result = self.collect(
            [
                run("g1", "off", stages=flat(0.7)),
                run("g1", "on", stages=flat(0.9), provenance="fake"),
            ]
        )
        self.assertEqual(result.n, 0)
        self.assertIn("fake run", result.excluded[0][1])

    def test_arms_from_a_different_capability_do_not_pair(self) -> None:
        result = self.collect(
            [
                run("g1", "off", stages=flat(0.7)),
                run("g1", "on", stages=flat(0.9), capability="review_panel"),
            ]
        )
        self.assertEqual(result.n, 0)

    def test_untagged_runs_are_invisible(self) -> None:
        result = self.collect([run("", "", stages=flat(0.7))])
        self.assertEqual((result.n, len(result.excluded)), (0, 0))

    def test_a_pair_with_no_stage_in_common_is_excluded(self) -> None:
        result = self.collect(
            [
                run("g1", "off", stages=flat(0.7, EIGHT[:2])),
                run("g1", "on", stages=flat(0.7, EIGHT[5:])),
            ]
        )
        self.assertEqual(result.n, 0)
        self.assertIn("no stage in common", result.excluded[0][1])

    def test_a_re_run_arm_replaces_rather_than_duplicates(self) -> None:
        result = self.collect(
            [
                run("g1", "off", stages=flat(0.5)),
                run("g1", "off", stages=flat(0.7)),
                run("g1", "on", stages=flat(0.8)),
            ]
        )
        self.assertEqual(result.n, 1)
        self.assertAlmostEqual(result.mean_difference, 0.1, places=6)


class DecompositionTests(unittest.TestCase):
    def test_a_win_concentrated_in_one_criterion_is_visible(self) -> None:
        """The Goodhart check. A capability that writes more files raises
        `artifact_breadth` whether or not the research improved — a real total and a
        fake result, and the only way to see it is the vector next to the scalar."""
        result = collect_pairs(
            paired(
                6,
                0.70,
                0.75,
                control_extra={"criteria": {"artifact_breadth": 0.5, "grounding": 0.8}},
                treatment_extra={"criteria": {"artifact_breadth": 0.9, "grounding": 0.8}},
            ),
            capability="effort_tiers",
            control_arm="off",
            treatment_arm="on",
        )
        deltas = result.criterion_differences()
        self.assertAlmostEqual(deltas["artifact_breadth"], 0.4, places=6)
        self.assertAlmostEqual(deltas["grounding"], 0.0, places=6)
        self.assertAlmostEqual(result.concentration, 1.0, places=6)

        rendered = format_trial_report(result)
        self.assertIn("Concentration: **100%**", rendered)
        self.assertIn("fake result", rendered)

    def test_an_effect_spread_across_criteria_is_not_flagged(self) -> None:
        result = collect_pairs(
            paired(
                6,
                0.70,
                0.75,
                control_extra={"criteria": {"a": 0.5, "b": 0.5, "c": 0.5}},
                treatment_extra={"criteria": {"a": 0.6, "b": 0.6, "c": 0.6}},
            ),
            capability="effort_tiers",
            control_arm="off",
            treatment_arm="on",
        )
        self.assertLess(result.concentration, 0.4)
        self.assertNotIn("fake result", format_trial_report(result))


class ReportTests(unittest.TestCase):
    def test_an_underpowered_trial_says_so_rather_than_saying_not_significant(self) -> None:
        result = collect_pairs(
            paired(3, 0.5, 0.9), capability="effort_tiers", control_arm="off", treatment_arm="on"
        )
        rendered = format_trial_report(result)

        self.assertTrue(result.underpowered)
        self.assertIn("underpowered", rendered)
        self.assertIn("fact about the sample", rendered)
        self.assertIn("floor at n=3: 0.2500", rendered)

    def test_a_powered_unanimous_trial_reaches_significance(self) -> None:
        result = collect_pairs(
            paired(7, 0.60, 0.68), capability="effort_tiers", control_arm="off", treatment_arm="on"
        )
        self.assertFalse(result.underpowered)
        self.assertEqual((result.wins, result.losses), (7, 0))
        self.assertAlmostEqual(result.mean_difference, 0.08, places=6)
        self.assertLess(result.p_value, 0.05)

    def test_an_archive_with_no_trials_says_how_to_start_one(self) -> None:
        self.assertIn("--trial", format_all_trials([run("", "", stages=flat(0.5))]))

    def test_the_report_names_which_arm_is_which(self) -> None:
        """An inverted sign should be visible rather than silent, so the labels are
        printed even when they were inferred."""
        records = [run("g1", "off", stages=flat(0.5)), run("g1", "on", stages=flat(0.7))]
        self.assertIn("`on` against `off`", format_all_trials(records))


class RenderingContractTests(unittest.TestCase):
    """The parts of the report a second outcome measure leans on.

    Every one of these was unpinned before an external benchmark was fed through this
    module, and every one renders something false when it is wrong rather than raising.
    """

    def collect(self, records, **kwargs):
        return collect_pairs(
            records, capability="effort_tiers", control_arm="off", treatment_arm="on", **kwargs
        )

    def test_the_default_unit_is_rubric_points(self) -> None:
        """The default has to keep every existing report byte-identical."""
        result = self.collect(paired(3, 0.5, 0.6))
        self.assertIn("+0.1000** rubric points", format_trial_report(result))

    def test_the_unit_is_whatever_the_caller_declared(self) -> None:
        """An external benchmark's 0-100 total printed as "rubric points" is a lie
        about the instrument in the one place a reader takes the number from."""
        result = self.collect(paired(3, 0.5, 0.6))
        rendered = format_trial_report(result, unit="RCB points (0-100 total scale)")
        self.assertIn("+0.1000** RCB points (0-100 total scale)", rendered)
        self.assertNotIn("rubric points", rendered)

    def test_the_decomposition_table_says_how_many_pairs_each_row_is_over(self) -> None:
        """A criterion seen in one pair of three renders exactly like a mean over three.

        With AutoR's own rubric every key is in every pair and nobody missed the
        denominator. Hand the same table a per-goal key set — a benchmark checklist is
        written per task — and every row is a single observation under a header that
        says "mean difference".
        """
        records = paired(3, 0.5, 0.6)
        # One criterion only the first pair measured.
        records[0] = run("g0", "off", stages=flat(0.5), criteria={"shared": 0.5, "rare": 0.1})
        records[1] = run("g0", "on", stages=flat(0.6), criteria={"shared": 0.6, "rare": 0.9})
        for index in (2, 4):
            records[index] = run(f"g{index // 2}", "off", stages=flat(0.5), criteria={"shared": 0.5})
            records[index + 1] = run(f"g{index // 2}", "on", stages=flat(0.6), criteria={"shared": 0.6})

        result = self.collect(records)
        self.assertEqual(result.criterion_support(), {"shared": 3, "rare": 1})

        rendered = format_trial_report(result)
        self.assertIn("| Criterion | Mean difference | pairs |", rendered)
        self.assertIn("| `rare` | +0.8000 | 1 |", rendered)
        self.assertIn("| `shared` | +0.1000 | 3 |", rendered)

    def test_the_concentration_floor_is_printed_beside_the_concentration(self) -> None:
        """Same discipline as the p and its floor, for the same reason.

        0.6 was calibrated against eight rubric criteria, where an even spread reads
        0.125. Over two keys an even spread already reads 0.50 and the warning fires on
        a 1.5:1 split, so the denominator has to be visible.
        """
        self.assertAlmostEqual(min_attainable_concentration(8), 0.125)
        self.assertAlmostEqual(min_attainable_concentration(2), 0.5)
        self.assertEqual(min_attainable_concentration(0), 0.0)

        result = self.collect(
            paired(
                3, 0.5, 0.6,
                control_extra={"criteria": {"a": 0.5, "b": 0.5}},
                treatment_extra={"criteria": {"a": 0.9, "b": 0.5}},
            )
        )
        self.assertIn("floor at 2 criteria: 50%", format_trial_report(result))


class TagTests(unittest.TestCase):
    def test_a_partial_tag_is_refused(self) -> None:
        """A `trial_id` with no capability cannot be grouped with anything, and an
        arm with no trial cannot be paired. Both would look like data and be none."""
        with self.assertRaises(ValueError) as caught:
            TrialTag.build("g1", "", "on")
        self.assertIn("--capability", str(caught.exception))
        with self.assertRaises(ValueError):
            TrialTag.build("", "effort_tiers", "on")
        with self.assertRaises(ValueError):
            TrialTag.build("g1", "effort_tiers", "   ")

    def test_a_complete_tag_is_trimmed(self) -> None:
        tag = TrialTag.build(" g1 ", " effort_tiers ", " on ")
        self.assertEqual((tag.trial_id, tag.capability, tag.arm), ("g1", "effort_tiers", "on"))


if __name__ == "__main__":
    unittest.main()
