"""Unlimited attempts still have to end, and the thing that ends them is progress.

Removing the attempt ceiling removed the only thing that stopped a stage which cannot
pass. That is not obviously an improvement: a run that never ends produces *nothing*,
which is worse than the skipped stage the ceiling was removed to prevent, because a run
with a hole in it at least has a report.

So the stop is "no progress", not "no patience". A stage failing differently each time is
working through its problems and gets as many attempts as it needs. A stage whose
validation errors are identical three times running has demonstrated that another attempt
cannot help, and the run says so in those words rather than reporting an exhausted budget
it no longer has.
"""

from __future__ import annotations

import unittest

from src.utils import STUCK_AFTER_IDENTICAL_FAILURES as K
from src.utils import attempts_exhausted, is_stuck


class IsStuckTest(unittest.TestCase):
    def test_identical_failures_are_stuck(self) -> None:
        self.assertTrue(is_stuck([["missing sources.json"]] * K))

    def test_one_short_of_the_window_is_not_stuck(self) -> None:
        self.assertFalse(is_stuck([["missing sources.json"]] * (K - 1)))

    def test_reordered_errors_are_the_same_failure(self) -> None:
        # Validators run in registration order, which is not meaningful. Two attempts that
        # surfaced the same problems in a different order made the same progress: none.
        self.assertTrue(is_stuck([["a", "b"], ["b", "a"], ["a", "b"]][:K] * 1))

    def test_a_stage_failing_differently_gets_to_keep_going(self) -> None:
        self.assertFalse(is_stuck([["a"], ["b"], ["c"]]))

    def test_progress_then_a_repeat_only_counts_the_tail(self) -> None:
        self.assertFalse(is_stuck([["a"], ["a"], ["b"]]))
        self.assertTrue(is_stuck([["a"], ["b"], ["b"], ["b"]]))

    def test_an_attempt_with_no_recorded_errors_is_not_a_repeat(self) -> None:
        # A failure no validator named is the case most in need of another attempt, and
        # three of them would otherwise read as three identical failures.
        self.assertFalse(is_stuck([[]] * K))
        self.assertFalse(is_stuck([[], [], []]))

    def test_an_empty_history_is_not_stuck(self) -> None:
        self.assertFalse(is_stuck([]))

    def test_the_window_is_the_published_constant(self) -> None:
        # Pins the relationship rather than the number: the rule is "K identical", so a
        # history of K-1 must not trip it and a history of K must.
        history = [["same"]] * K
        self.assertTrue(is_stuck(history))
        self.assertFalse(is_stuck(history[: K - 1]))


class TheTwoStopsAreIndependentTest(unittest.TestCase):
    def test_no_ceiling_does_not_mean_no_stop(self) -> None:
        self.assertFalse(attempts_exhausted(500, None))
        self.assertTrue(is_stuck([["same"]] * K))

    def test_a_ceiling_still_stops_a_stage_that_is_making_progress(self) -> None:
        # The two answer different questions. Progress does not buy an unlimited run when
        # the caller asked for a bound.
        self.assertFalse(is_stuck([["a"], ["b"], ["c"]]))
        self.assertTrue(attempts_exhausted(6, 5))


if __name__ == "__main__":
    unittest.main()
