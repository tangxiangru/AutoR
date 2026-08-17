"""The sign-flip test above eighteen pairs, and the truncation that used to be there.

Written for one defect, measured on this tree before the fix. ``sign_flip_p`` took
``observed`` as the mean of all *n* differences and then, past ``MAX_EXACT_PAIRS``,
enumerated the sign assignments of ``usable[:18]`` only. An eighteen-pair permuted
mean was compared against a sixty-pair observed one, so the two halves of the
statistic came from different samples and the result was not a p-value:

* ``sign_flip_p([0.01] * 18 + [5.0] * 42)`` returned exactly ``0.0``. No permutation
  test can return zero — the observed assignment is always at least as extreme as
  itself, so the smallest attainable value over eighteen pairs is ``2 / 2**18`` =
  7.6e-06.
* ``sign_flip_p([5.0] * 42 + [0.01] * 18)``, the *same sixty differences* in the
  other order, returned ``0.0013``. Nothing about a paired test may depend on which
  order the pairs were collected in, and this depended on it by a factor the answer
  cannot survive: one of the two numbers is impossible and the other is not.
* ``sign_flip_p([5.0] * 18 + [0.01] * 42)`` returned ``0.2379``. A different sample
  — eighteen large and forty-two small rather than the other way round — whose mean
  difference is 1.507 against the first sample's 3.503, so the *weaker* effect
  reported the p that at least looked like a p, purely because its large values
  landed inside the first eighteen slots.
* ``TrialResult.floor`` printed ``min_attainable_p(60)`` = 1.7e-18 beside all three,
  so an unattainable p sat next to an unattainable floor.

The fix replaces the truncation with a seeded Monte-Carlo sample of sign assignments
over all *n* differences and reports the floor of the estimator that ran. Nothing
below the threshold moved, and the first class here is what holds that: twelve
inputs whose values were captured from the pre-fix code and pinned as literals,
because the paired ResearchClawBench trials this module already serves are three to
six pairs and their published numbers were not this change's to touch.

Three more defects, all in how the *report* describes that estimator rather than in
the estimator, and all measured on this tree after the first fix landed:

* ``TrialResult.p_is_sampled`` was ``self.n > MAX_EXACT_PAIRS`` — which estimator
  *would* run at that sample size, not which one *did*. ``sign_flip_p`` returns 1.0
  from its cancellation branch before either, so ``result_over(CANCELLING)`` at twenty
  pairs rendered "- sampled two-sided p: **1.000000** (floor at 200,000 sign
  assignments: 0.000005)" and the sentence "that p is a Monte-Carlo estimate over
  200,000 of them drawn with seed ``20260817``" with no assignment ever drawn — a floor
  describing a computation nobody ran, which is the defect above reappearing in the
  report. ``TheLabelNamesTheComputationThatRanTests`` instruments the random number
  generator and the enumeration so the label is checked against what executed.
* The p printed on the sampled line was pinned by nothing. ``sampled_p = 0.5``,
  ``= result.floor``, ``= result.mean_difference`` and ``{sampled_p:.4f}`` each survived
  the whole suite; the last renders 5e-06 as ``0.0000``, restoring the string the
  sampled branch exists to stop printing.
* ``n == MAX_EXACT_PAIRS`` was untested on the report side, so ``>=`` for ``>`` in the
  branch was invisible — an eighteen-pair trial then printed the sampled label and a
  floor of 5e-06 beside a number the untouched enumeration produced, whose own floor is
  7.63e-06.
"""

from __future__ import annotations

import inspect
import itertools
import random
import types
import unittest
from math import comb, sqrt
from unittest import mock

from src import trials
from src.archive import RunRecord
from src.rubric import RUBRIC_VERSION
from src.trials import (
    ESTIMATOR_CANCELLED,
    ESTIMATOR_EXACT,
    ESTIMATOR_NO_PAIRS,
    ESTIMATOR_SAMPLED,
    MAX_EXACT_PAIRS,
    RCB_TOTAL,
    SAMPLED_SIGN_ASSIGNMENTS,
    SIGN_FLIP_ESTIMATORS,
    SIGN_FLIP_SEED,
    Pair,
    TrialResult,
    _sampled_sign_flip_p,
    attainable_p_floor,
    format_trial_report,
    min_attainable_p,
    sign_flip_estimator,
    sign_flip_p,
)


#: ``(name, differences, p as the pre-fix code returned it)``. Captured by running the
#: old implementation, not derived, so a change to the exact branch shows up here as a
#: disagreement with a recorded observation rather than with a rewritten expectation.
#: Chosen to cover the shapes the branch has: empty, all-ties, a single pair, a
#: unanimous sample at the floor, ties mixed with signal, pure noise, an asymmetric
#: sample, and both sides of the ``n == MAX_EXACT_PAIRS`` boundary.
PINNED_EXACT: tuple[tuple[str, list[float], float], ...] = (
    ("no pairs at all", [], 1.0),
    ("every difference a tie", [0.0, 0.0], 1.0),
    ("one pair", [2.5], 1.0),
    ("five unanimous", [0.5] * 5, 0.0625),
    ("six unanimous, at the floor", [0.1] * 6, 0.03125),
    ("four unanimous and two ties", [0.1] * 4 + [0.0, 0.0], 0.125),
    ("six pairs of pure noise", [0.3, -0.28, 0.31, -0.29, 0.3, -0.3], 0.78125),
    ("eight mixed", [0.05, -0.02, 0.11, 0.07, -0.01, 0.09, 0.13, -0.04], 0.09375),
    ("seventeen unanimous", [1.0] * 17, 1.52587890625e-05),
    (
        "seventeen mixed, one of them a tie",
        [0.9, -0.1, 0.4, 0.4, -0.2, 0.7, 1.3, -0.4, 0.2, 0.05, -0.6, 0.8, 0.15, 0.0, 0.33, -0.25, 0.5],
        0.061004638671875,
    ),
    ("eighteen unanimous, the last exact n", [1.0] * 18, 7.62939453125e-06),
    ("eighteen, nine up and nine down", [3.0] * 9 + [-1.0] * 9, 0.0722503662109375),
)

#: One sample of sixty differences in two orders — the same multiset, and the pre-fix
#: code returned 0.0 for the first and 0.0013 for the second.
FRONT_LOADED = [0.01] * 18 + [5.0] * 42
REORDERED = [5.0] * 42 + [0.01] * 18

#: A *different* sample, kept because it is the one that shows what the truncation was
#: reading. Eighteen large differences and forty-two small ones: a mean difference of
#: 1.507 where ``FRONT_LOADED`` has 3.503, and the pre-fix code answered 0.2379 for
#: this and 0.0 for the stronger effect, because all the size in this one sits in the
#: eighteen slots the enumeration looked at.
LARGE_FIRST = [5.0] * 18 + [0.01] * 42

#: Forty differences of ``±1``, twenty-six up and fourteen down. Under the null every
#: ``sign * value`` is ``±1`` whatever the value was, so the null distribution is
#: exactly a sum of forty Rademacher variables and the true two-sided p is a binomial
#: tail this test can compute in closed form. That is the oracle the sampled branch is
#: checked against; there is no other one, because enumerating 2**40 is the thing the
#: branch exists to avoid.
RADEMACHER = [1.0] * 26 + [-1.0] * 14

#: Twenty differences summing to exactly ``0.0`` in float: ten up and ten down, a
#: quarter of a point each. Above ``MAX_EXACT_PAIRS``, so ``n > MAX_EXACT_PAIRS`` says
#: "sampled" — and ``sign_flip_p`` returns 1.0 from its cancellation branch without
#: drawing anything. Nothing contrived about the shape: the ResearchClawBench rubric is
#: scored in quarter points, so a trial whose within-pair differences cancel is an
#: ordinary outcome rather than a constructed one.
CANCELLING = [0.25] * 10 + [-0.25] * 10

#: The same twenty pairs with one flipped, so the mean is 0.025 rather than 0.0 and the
#: sample really is drawn. The control for every assertion made about ``CANCELLING``.
NOT_QUITE_CANCELLING = [0.25] * 11 + [-0.25] * 9


def rademacher_p(count: int, positives: int) -> float:
    """Exact two-sided p for ``count`` differences of ``±1``, ``positives`` of them up."""
    observed = abs(2 * positives - count)
    tail = sum(comb(count, j) for j in range((count + observed) // 2, count + 1))
    tail += sum(comb(count, j) for j in range(0, (count - observed) // 2 + 1))
    return tail / 2**count


def truncating_sign_flip_p(differences: list[float]) -> float:
    """The pre-fix implementation, kept here as the control the fix is measured against.

    Copied from the code this change replaced, not re-derived: ``observed`` over all
    *n*, the enumeration over the first ``MAX_EXACT_PAIRS``. A test that only asserts
    the new numbers look reasonable would pass against an implementation that had
    quietly kept the bug in some other form, and the three literals in this module's
    docstring would be unattached prose.
    """
    usable = [float(value) for value in differences]
    if not usable:
        return 1.0
    observed = abs(sum(usable) / len(usable))
    if observed == 0.0:
        return 1.0
    count = len(usable)
    if count > MAX_EXACT_PAIRS:
        usable = usable[:MAX_EXACT_PAIRS]
        count = MAX_EXACT_PAIRS
    at_least_as_extreme = 0
    total = 0
    for signs in itertools.product((1.0, -1.0), repeat=count):
        total += 1
        mean = sum(sign * value for sign, value in zip(signs, usable)) / count
        if abs(mean) >= observed - 1e-12:
            at_least_as_extreme += 1
    return at_least_as_extreme / total


def one_sided_sign_flip_p(differences: list[float]) -> float:
    """A mutant of the exact branch that counts one tail, used only as a control.

    The enumeration with ``abs(mean) >= observed`` weakened to ``mean >= observed``.
    Nothing calls this outside the test that asks whether the pinned values above hold
    any content; it exists so "the exact branch is unchanged" is an assertion about a
    statistic and not about a lookup table that would survive rewriting it.
    """
    usable = [float(value) for value in differences]
    if not usable:
        return 1.0
    observed = abs(sum(usable) / len(usable))
    if observed == 0.0:
        return 1.0
    at_least_as_extreme = 0
    total = 0
    for signs in itertools.product((1.0, -1.0), repeat=len(usable)):
        total += 1
        mean = sum(sign * value for sign, value in zip(signs, usable)) / len(usable)
        if mean >= observed - 1e-12:
            at_least_as_extreme += 1
    return at_least_as_extreme / total


def run_watching_the_branches(differences: list[float]) -> tuple[float, int, int]:
    """``sign_flip_p`` with both estimators instrumented: ``(p, draws, enumerations)``.

    The only way to assert that a label names the computation that *ran* rather than the
    one the sample size predicts. ``src.trials.random`` and ``src.trials.itertools`` are
    swapped for namespaces that count, so the two figures come from the estimators
    themselves; patching the names bound in the module rather than the attributes of the
    stdlib modules keeps the instrument off every other test in the process.
    """
    counted = {"draws": 0, "enumerations": 0}

    class WatchedRandom:
        def __init__(self, seed: int) -> None:
            self._getrandbits = random.Random(seed).getrandbits

        def getrandbits(self, width: int) -> int:
            counted["draws"] += 1
            return self._getrandbits(width)

    def watched_product(*args: object, **kwargs: object) -> object:
        counted["enumerations"] += 1
        return itertools.product(*args, **kwargs)

    with mock.patch.object(trials, "random", types.SimpleNamespace(Random=WatchedRandom)):
        with mock.patch.object(trials, "itertools", types.SimpleNamespace(product=watched_product)):
            p_value = sign_flip_p(differences)
    return p_value, counted["draws"], counted["enumerations"]


def _record(trial: str, arm: str, value: float) -> RunRecord:
    return RunRecord(
        run_id=f"{trial}-{arm}",
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness={"01_s": value},
        topology="adaptive",
        provenance="live",
        route="",
        steps=1,
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="t",
        criterion_fitness={},
        trial_id=trial,
        capability="effort_tiers",
        arm=arm,
    )


def result_over(differences: list[float]) -> TrialResult:
    """A :class:`TrialResult` whose within-pair differences are exactly these."""
    pairs = tuple(
        Pair(f"g{index}", _record(f"g{index}", "off", 0.5), _record(f"g{index}", "on", 0.5 + value))
        for index, value in enumerate(differences)
    )
    return TrialResult(
        capability="effort_tiers",
        control_arm="off",
        treatment_arm="on",
        pairs=pairs,
        outcome=RCB_TOTAL,
    )


class TheExactBranchDidNotMoveTests(unittest.TestCase):
    """Every existing paired trial is three to six pairs. This is their oracle."""

    def test_every_pinned_value_below_the_threshold_is_returned_unchanged(self) -> None:
        for name, differences, expected in PINNED_EXACT:
            with self.subTest(name):
                self.assertEqual(sign_flip_p(differences), expected)

    def test_the_pinned_inputs_reach_both_sides_of_the_threshold(self) -> None:
        """The control on the population above: pins that all sat at n = 3 would hold
        nothing about the boundary the change is at."""
        sizes = {len(differences) for _, differences, _ in PINNED_EXACT}
        self.assertIn(MAX_EXACT_PAIRS, sizes)
        self.assertIn(MAX_EXACT_PAIRS - 1, sizes)
        self.assertEqual(max(sizes), MAX_EXACT_PAIRS)
        self.assertGreaterEqual(len(PINNED_EXACT), 6)

    def test_the_pinned_values_would_notice_a_change_to_the_statistic(self) -> None:
        """The control on the assertion itself.

        Twelve equalities are worth nothing if every plausible mutant satisfies them,
        and one obvious mutant does: dropping ties before the enumeration leaves every
        pin standing, because under a permutation test on the mean a tie is neutral.
        That is the property the module documents, not a weakness of these pins, but it
        does mean the pins need a mutant they *can* see. Counting one tail instead of
        two is one — the difference between a one- and a two-sided test — and it moves
        ten of the twelve.
        """
        moved = [
            name
            for name, differences, expected in PINNED_EXACT
            if one_sided_sign_flip_p(differences) != expected
        ]
        self.assertGreaterEqual(len(moved), 10, f"only {moved} distinguish a one-sided test")
        unmoved = {name for name, _, _ in PINNED_EXACT} - set(moved)
        # The two that cannot move are the two that return before the enumeration: no
        # differences at all, and differences that are all ties.
        self.assertEqual(unmoved, {"no pairs at all", "every difference a tie"})

    def test_the_exact_branch_is_still_the_untouched_enumeration(self) -> None:
        """Below the threshold the truncation never fired, so the pre-fix code and the
        current code have to agree everywhere — the second witness that the pins above
        are pins on the old behaviour and not on a new one that happens to match."""
        for name, differences, _ in PINNED_EXACT:
            with self.subTest(name):
                self.assertEqual(sign_flip_p(differences), truncating_sign_flip_p(differences))


class TheOrderOfTheDifferencesNoLongerMovesThePTests(unittest.TestCase):
    """`[0.01]*18 + [5.0]*42` returned 0.0 and the same sixty reordered returned 0.0013."""

    def test_the_pre_fix_code_still_reproduces_the_three_numbers_in_the_docstring(self) -> None:
        """The control. Without it the tests below assert that two numbers agree
        without ever showing that they used to disagree, and the defect this file names
        would be a claim about a tree nobody can check."""
        self.assertEqual(truncating_sign_flip_p(FRONT_LOADED), 0.0)
        self.assertAlmostEqual(truncating_sign_flip_p(REORDERED), 0.001312255859375, places=12)
        self.assertAlmostEqual(truncating_sign_flip_p(LARGE_FIRST), 0.237884521484375, places=12)

    def test_the_same_sixty_differences_in_two_orders_now_give_the_same_p(self) -> None:
        self.assertEqual(sorted(FRONT_LOADED), sorted(REORDERED))
        # Both sit on the estimator's floor: a mean of 3.503 over sixty differences
        # whose largest is 5.0 is not reachable by any sign assignment but the observed
        # one. The tolerance is the sampling error there, which is under 5e-06.
        self.assertLess(
            abs(sign_flip_p(FRONT_LOADED) - sign_flip_p(REORDERED)), 4.0 / SAMPLED_SIGN_ASSIGNMENTS
        )

    def test_the_weaker_of_the_two_samples_no_longer_reports_the_larger_looking_p(self) -> None:
        """`LARGE_FIRST` is not a reordering of `FRONT_LOADED` — it is a different
        sample, with a mean difference of 1.507 against 3.503 — and that is what makes
        it the sharper witness. Both are unanimous samples whose observed mean is out
        of reach of every sign assignment but the observed one, so both belong exactly
        on the floor; the truncation put one on 0.2379 and the other on 0.0, and picked
        which by where the large values happened to sit."""
        self.assertLess(sum(LARGE_FIRST) / 60, sum(FRONT_LOADED) / 60)
        self.assertEqual(sign_flip_p(LARGE_FIRST), attainable_p_floor(60))
        self.assertEqual(sign_flip_p(FRONT_LOADED), attainable_p_floor(60))

    def test_no_order_returns_a_p_no_permutation_test_could_produce(self) -> None:
        for name, differences in (
            ("front-loaded", FRONT_LOADED),
            ("reordered", REORDERED),
            ("large first", LARGE_FIRST),
        ):
            with self.subTest(name):
                self.assertGreaterEqual(sign_flip_p(differences), attainable_p_floor(len(differences)))


class TheSampledEstimateIsOfTheRightQuantityTests(unittest.TestCase):
    """That the branch samples is not the claim. That it samples the null is."""

    def test_the_sampled_p_agrees_with_a_closed_form_null_over_forty_pairs(self) -> None:
        exact = rademacher_p(40, 26)
        error = sqrt(exact * (1.0 - exact) / SAMPLED_SIGN_ASSIGNMENTS)
        self.assertAlmostEqual(exact, 0.0806904677519924, places=12)
        self.assertLess(abs(sign_flip_p(RADEMACHER) - exact), 4.0 * error)

    def test_the_truncation_this_replaced_missed_that_null_by_two_hundred_errors(self) -> None:
        """The control on the test above: it has to be a test the old code fails.

        Truncating forty ``±1`` differences to eighteen leaves the observed mean at
        0.30 while the permuted mean is over eighteen, so the condition becomes
        ``|S_18| >= 6`` instead of ``|S_40| >= 12`` and the answer moves from 0.081 to
        0.238 — two hundred and fifty standard errors, so the four-error band above is
        not a band the old implementation could have slipped through.
        """
        exact = rademacher_p(40, 26)
        error = sqrt(exact * (1.0 - exact) / SAMPLED_SIGN_ASSIGNMENTS)
        self.assertGreater(abs(truncating_sign_flip_p(RADEMACHER) - exact), 200.0 * error)

    def test_reordering_the_same_forty_differences_lands_on_the_same_null(self) -> None:
        reordered = [1.0, -1.0] * 14 + [1.0] * 12
        self.assertEqual(sorted(reordered), sorted(RADEMACHER))
        exact = rademacher_p(40, 26)
        error = sqrt(exact * (1.0 - exact) / SAMPLED_SIGN_ASSIGNMENTS)
        self.assertLess(abs(sign_flip_p(reordered) - exact), 4.0 * error)

    def test_a_sample_of_one_assignment_is_the_observed_one(self) -> None:
        """The estimator counts the observed sign assignment rather than drawing it,
        which is what keeps it off zero. Asked for a reference set of one, it returns
        1/1 — the observed assignment is always at least as extreme as itself."""
        self.assertEqual(_sampled_sign_flip_p(RADEMACHER, 0.3, assignments=1), 1.0)


class TheSampledPIsReproducibleTests(unittest.TestCase):
    def test_the_same_differences_give_the_same_p_twice(self) -> None:
        self.assertEqual(sign_flip_p(RADEMACHER), sign_flip_p(RADEMACHER))
        self.assertEqual(sign_flip_p(FRONT_LOADED), sign_flip_p(FRONT_LOADED))

    def test_a_different_seed_moves_the_p_by_no_more_than_sampling_error(self) -> None:
        exact = rademacher_p(40, 26)
        error = sqrt(exact * (1.0 - exact) / SAMPLED_SIGN_ASSIGNMENTS)
        observed = abs(sum(RADEMACHER) / len(RADEMACHER))
        draws = [
            _sampled_sign_flip_p(RADEMACHER, observed, seed=seed)
            for seed in (SIGN_FLIP_SEED, SIGN_FLIP_SEED + 1, 7)
        ]
        # Not "all three differ": the counts are around 16,138 out of 200,000 with a
        # standard deviation of 122, so two seeds landing on the same count is a
        # once-in-a-few-hundred event and would be a flake rather than a finding. That
        # the seed is read at all is the claim.
        self.assertGreater(len(set(draws)), 1, "the seed made no difference to the sample")
        for value in draws:
            self.assertLess(abs(value - exact), 4.0 * error)

    def test_the_seed_is_not_a_call_site_choice(self) -> None:
        """A caller that can pick the seed can pick the p. The resolution is 5e-06 and
        the error near 0.05 is 0.0005, so seed-shopping could not move a verdict here —
        but the public function takes the differences and nothing else, and the tests
        that have to vary the seed reach into the private helper for it."""
        self.assertEqual(list(inspect.signature(sign_flip_p).parameters), ["differences"])


class TheFloorDescribesTheEstimatorThatRanTests(unittest.TestCase):
    def test_below_the_threshold_the_floor_is_still_two_over_two_to_the_n(self) -> None:
        for pairs in range(1, MAX_EXACT_PAIRS + 1):
            with self.subTest(pairs=pairs):
                self.assertEqual(attainable_p_floor(pairs), min_attainable_p(pairs))
        self.assertEqual(attainable_p_floor(0), 1.0)

    def test_above_the_threshold_the_floor_is_the_sampled_resolution(self) -> None:
        for pairs in (MAX_EXACT_PAIRS + 1, 40, 59, 60):
            with self.subTest(pairs=pairs):
                self.assertEqual(attainable_p_floor(pairs), 1.0 / SAMPLED_SIGN_ASSIGNMENTS)

    def test_the_floor_the_old_code_printed_was_below_anything_it_could_return(self) -> None:
        """Why the split exists, as an assertion rather than as a docstring. At sixty
        pairs the exact floor is twelve orders of magnitude under the smallest number
        the estimator can produce, so "p = 0.0000 against a floor of 0.0000" was two
        unattainable numbers printed as a comparison."""
        self.assertLess(min_attainable_p(60), attainable_p_floor(60))
        self.assertLess(min_attainable_p(60), 1e-17)

    def test_a_trial_result_reports_the_floor_of_the_branch_it_used(self) -> None:
        small = result_over([0.1] * 6)
        self.assertEqual(small.estimator, ESTIMATOR_EXACT)
        self.assertEqual(small.floor, min_attainable_p(6))

        large = result_over([0.1] * 12 + [-0.05] * 7)
        self.assertEqual(large.estimator, ESTIMATOR_SAMPLED)
        self.assertEqual(large.n, MAX_EXACT_PAIRS + 1)
        self.assertEqual(large.floor, 1.0 / SAMPLED_SIGN_ASSIGNMENTS)

    def test_the_boundary_pair_count_is_reported_as_the_enumeration_that_ran(self) -> None:
        """Both sides of ``n == MAX_EXACT_PAIRS``, which is the comparison the whole
        change turns on and the one the test above jumps over: it goes from six pairs to
        nineteen, so ``>=`` in place of ``>`` moves nothing it looks at.

        Under that off-by-one an eighteen-pair trial renders the sampled label, the seed
        and "floor at 200,000 sign assignments: 0.000005" beside a number the untouched
        enumeration produced, whose real floor is 7.63e-06 — a printed floor *below* the
        smallest value the estimator that ran can return, which is the defect this
        module's docstring says was closed, in the other direction. ``attainable_p_floor``
        itself is pinned at the boundary by the first test in this class, which loops to
        ``MAX_EXACT_PAIRS`` inclusive; the ``TrialResult`` and the report were not.
        """
        boundary = result_over([0.1] * MAX_EXACT_PAIRS)
        self.assertEqual(boundary.n, MAX_EXACT_PAIRS)
        self.assertEqual(boundary.estimator, ESTIMATOR_EXACT)
        self.assertEqual(boundary.floor, min_attainable_p(MAX_EXACT_PAIRS))
        self.assertEqual(boundary.floor, 7.62939453125e-06)
        rendered = format_trial_report(boundary)
        self.assertIn("- exact two-sided p: **0.000008** (floor at n=18: 0.000008)", rendered)
        self.assertNotIn("- sampled two-sided p: **", rendered)
        self.assertNotIn(str(SIGN_FLIP_SEED), rendered)

        over = result_over([0.1] * (MAX_EXACT_PAIRS + 1))
        self.assertEqual(over.estimator, ESTIMATOR_SAMPLED)
        self.assertEqual(over.floor, 1.0 / SAMPLED_SIGN_ASSIGNMENTS)
        self.assertIn("- sampled two-sided p: **", format_trial_report(over))

    def test_a_p_line_carries_enough_decimals_to_keep_its_own_floor_off_zero(self) -> None:
        """The reason the boundary's rendering above is six decimals and a three-pair
        report's is four. Four decimals print anything under 5e-05 as ``0.0000``, and the
        exact enumeration reaches 1.53e-05 at seventeen pairs, so the branch that never
        sampled anything could still print the p-of-zero shape the sampled branch was
        rewritten to stop printing. The control is the other direction: a trial whose
        floor is readable at four decimals must not grow two more, because every existing
        trial report is three to six pairs and those numbers were not this change's."""
        for pairs, expected in ((3, "0.2500"), (6, "0.0312"), (15, "0.0001")):
            with self.subTest(pairs=pairs):
                self.assertIn(
                    f"(floor at n={pairs}: {expected})", format_trial_report(result_over([0.1] * pairs))
                )
        for pairs, expected in ((17, "0.000015"), (18, "0.000008")):
            with self.subTest(pairs=pairs):
                self.assertIn(
                    f"(floor at n={pairs}: {expected})", format_trial_report(result_over([0.1] * pairs))
                )
                self.assertLess(min_attainable_p(pairs), 5e-5)

    def test_a_trial_result_never_reports_a_p_below_its_own_floor(self) -> None:
        for differences in ([0.1] * 19, [0.02] * 18 + [1.0] * 42, [1.0] * 60):
            with self.subTest(pairs=len(differences)):
                result = result_over(differences)
                self.assertGreaterEqual(result.p_value, result.floor)


class TheReportSaysWhichEstimatorRanTests(unittest.TestCase):
    def test_the_sampled_branch_prints_the_seed_and_the_number_of_assignments(self) -> None:
        rendered = format_trial_report(result_over([0.1] * 12 + [-0.05] * 7))
        self.assertIn("- sampled two-sided p: **", rendered)
        self.assertIn(f"seed `{SIGN_FLIP_SEED}`", rendered)
        self.assertIn(f"{SAMPLED_SIGN_ASSIGNMENTS:,}", rendered)
        self.assertNotIn("- exact two-sided p: **", rendered)

    def test_the_exact_branch_prints_neither(self) -> None:
        """The control. A seed line printed on every report would say nothing about
        which estimator ran, and every existing trial report test is on this branch."""
        rendered = format_trial_report(result_over([0.1] * 6))
        self.assertIn("- exact two-sided p: **", rendered)
        self.assertNotIn("- sampled two-sided p: **", rendered)
        self.assertNotIn(str(SIGN_FLIP_SEED), rendered)

    def test_the_sampled_floor_is_printed_with_enough_digits_to_read(self) -> None:
        """5e-06 at four decimal places is ``0.0000``, which is the shape of the number
        this whole change exists to stop printing."""
        rendered = format_trial_report(result_over([0.1] * 12 + [-0.05] * 7))
        self.assertIn("floor at 200,000 sign assignments: 0.000005", rendered)
        self.assertNotIn("floor at 200,000 sign assignments: 0.0000)", rendered)

    def test_the_sampled_p_printed_on_the_floor_is_the_floor_and_not_a_zero(self) -> None:
        """The number the change exists to make correct, and it was unpinned.

        Three tests here asserted the label, the seed, the assignment count and the
        *floor*'s digits; none asserted the p. Every one of ``sampled_p = 0.5``,
        ``sampled_p = result.floor``, ``sampled_p = result.mean_difference`` and
        ``{sampled_p:.4f}`` survived the whole suite. The last is the sharpest: at four
        decimals ``5e-06`` renders ``0.0000``, so the mutant silently restores the exact
        string the sampled branch was written to stop printing, and it renders both sides
        of this line as zero at once.
        """
        on_the_floor = result_over(FRONT_LOADED)
        self.assertEqual(on_the_floor.p_value, 1.0 / SAMPLED_SIGN_ASSIGNMENTS)
        self.assertIn(
            "- sampled two-sided p: **0.000005** "
            "(floor at 200,000 sign assignments: 0.000005)",
            format_trial_report(on_the_floor),
        )

    def test_the_printed_p_is_the_p_value_and_not_another_float_on_the_result(self) -> None:
        """The control on the test above, whose fixture sits exactly on its floor: a line
        that printed the floor would satisfy it. This one's p is mid-range, so it agrees
        with nothing else the report holds — asserted, rather than assumed, because "the
        printed number is `p_value`" is only a claim if the other candidates differ."""
        result = result_over([0.1] * 12 + [-0.05] * 7)
        printed = f"{result.p_value:.6f}"
        self.assertEqual(printed, "0.028920")
        for name, other in (
            ("the floor", f"{result.floor:.6f}"),
            ("the mean difference", f"{result.mean_difference:.6f}"),
            ("the concentration", f"{result.concentration:.6f}"),
            ("a hard-coded half", "0.500000"),
        ):
            with self.subTest(name):
                self.assertNotEqual(printed, other)
        self.assertIn(f"- sampled two-sided p: **{printed}**", format_trial_report(result))


class TheLabelNamesTheComputationThatRanTests(unittest.TestCase):
    """``p_is_sampled`` was ``n > MAX_EXACT_PAIRS``: which estimator *would* run.

    ``sign_flip_p`` returns 1.0 from its cancellation branch before either estimator, so
    the two answers differ on any trial above eighteen pairs whose differences sum to
    exactly zero. Measured on this tree before the fix, ``result_over(CANCELLING)``
    reported ``p_is_sampled = True`` and rendered "- sampled two-sided p: **1.000000**
    (floor at 200,000 sign assignments: 0.000005)" followed by the sentence "that p is a
    Monte-Carlo estimate over 200,000 of them drawn with seed `20260817`". No assignment
    was drawn. That is a floor describing a computation nobody ran — this module's own
    defect, one level up in the report.
    """

    def test_a_cancelling_trial_above_the_threshold_does_not_claim_a_sample(self) -> None:
        self.assertEqual(sum(CANCELLING), 0.0)
        result = result_over(CANCELLING)
        self.assertGreater(result.n, MAX_EXACT_PAIRS)
        self.assertEqual(result.estimator, ESTIMATOR_CANCELLED)
        self.assertEqual(result.p_value, 1.0)
        self.assertEqual(result.floor, 1.0)

        rendered = format_trial_report(result)
        self.assertIn("- two-sided p: **1.0000**", rendered)
        self.assertIn("cancel to a mean of exactly zero", rendered)
        self.assertNotIn("sampled two-sided p", rendered)
        self.assertNotIn("Monte-Carlo", rendered)
        self.assertNotIn(str(SIGN_FLIP_SEED), rendered)
        self.assertNotIn("0.000005", rendered)

    def test_a_trial_of_the_same_size_that_did_sample_says_all_of_it(self) -> None:
        """The control on the four ``assertNotIn``s above. Twenty pairs either way; the
        only difference is that these do not cancel. Without this, a report that had
        stopped printing p-values at all would pass the test above."""
        rendered = format_trial_report(result_over(NOT_QUITE_CANCELLING))
        self.assertNotEqual(sum(NOT_QUITE_CANCELLING), 0.0)
        self.assertIn("sampled two-sided p", rendered)
        self.assertIn("Monte-Carlo", rendered)
        self.assertIn(str(SIGN_FLIP_SEED), rendered)
        self.assertIn("0.000005", rendered)
        self.assertNotIn("- two-sided p: **", rendered)

    def test_the_label_is_the_branch_that_executed_and_not_the_one_n_predicts(self) -> None:
        """The observation the old boolean could not make, taken with the estimators
        instrumented. A cancelling twenty-pair trial draws nothing and enumerates
        nothing; ``n > MAX_EXACT_PAIRS`` calls it sampled anyway.

        The draw counts are exact rather than "more than zero": nineteen differences are
        two blocks of at most fifteen, so a draw is two ``getrandbits`` calls and the
        sample is ``SAMPLED_SIGN_ASSIGNMENTS - 1`` of them — the observed assignment is
        counted, not drawn.
        """
        for name, differences, estimator, draws, enumerations in (
            ("no pairs", [], ESTIMATOR_NO_PAIRS, 0, 0),
            ("cancelling, above the threshold", CANCELLING, ESTIMATOR_CANCELLED, 0, 0),
            ("cancelling, below it", [0.5, -0.5], ESTIMATOR_CANCELLED, 0, 0),
            ("six unanimous", [0.1] * 6, ESTIMATOR_EXACT, 0, 1),
            (
                "nineteen mixed",
                [0.1] * 12 + [-0.05] * 7,
                ESTIMATOR_SAMPLED,
                2 * (SAMPLED_SIGN_ASSIGNMENTS - 1),
                0,
            ),
        ):
            with self.subTest(name):
                p_value, drawn, enumerated = run_watching_the_branches(differences)
                self.assertEqual(sign_flip_estimator(differences), estimator)
                self.assertEqual(drawn, draws)
                self.assertEqual(enumerated, enumerations)
                # The instrument did not move the answer it was measuring.
                self.assertEqual(p_value, sign_flip_p(differences))

    def test_every_declared_estimator_is_reachable_and_reaches_the_report(self) -> None:
        """The registry control. ``format_trial_report`` keys its p-line on this label,
        so a fifth estimator added without a line there would drop the p out of the
        report and leave the mean difference standing on its own. Four fixtures, four
        labels, and the set has to be the whole of ``SIGN_FLIP_ESTIMATORS``."""
        rendered_by_estimator = {}
        for differences in ([], [0.1] * 6, CANCELLING, [0.1] * 12 + [-0.05] * 7):
            result = result_over(differences)
            rendered_by_estimator[result.estimator] = format_trial_report(result)

        self.assertEqual(set(rendered_by_estimator), set(SIGN_FLIP_ESTIMATORS))
        for estimator, rendered in rendered_by_estimator.items():
            with self.subTest(estimator):
                if estimator == ESTIMATOR_NO_PAIRS:
                    self.assertNotIn("two-sided p", rendered)
                else:
                    self.assertIn("two-sided p: **", rendered)


if __name__ == "__main__":
    unittest.main()
