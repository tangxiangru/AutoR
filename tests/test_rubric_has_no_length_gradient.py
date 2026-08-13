"""Prose may not move a criterion, because the improvement prompt promises it cannot.

`src/evolution.py` tells the agent, in every polish round:

    Do not lengthen a section to raise a score. Every criterion here is a ratio or a
    count over artifacts on disk; prose cannot move any of them.

That was false for `commitment`, whose hedge allowance was `words / 200`. Holding one
forward-looking phrase fixed and adding clean prose around it, measured on main before
this change:

    149 words   -> 0.8000
    677 words   -> 0.9409
    2,789 words -> 0.9857

+0.1857 on the criterion is +0.0253 on a Stage 01 total, against a `DEFAULT_MIN_GAIN`
of 0.02. So `EvolutionController.consider` recorded a round that added nothing but
words as `promoted`, "New champion". The rule was written down in the prompt and the
gradient paid for breaking it.

This module holds the prohibition itself rather than one formula: the assertion is
that adding contentless prose does not raise the criterion, and does not raise the
stage total past the threshold the ratchet promotes on. Any future denominator that
reintroduces a length term fails here.
"""

from __future__ import annotations

import unittest

from src.archive import DEFAULT_MIN_GAIN
from src.rubric import CRITERIA, CRITERIA_BY_KEY, _score_commitment

WORK = (
    "Ran the deduplication pass over the retrieval corpus and recorded 8/8 source paths. "
    "Counted 412 overlapping passages and wrote them to `workspace/data/overlap.json`. "
)
HEDGE = "We will investigate the remaining discrepancy in a follow-up pass. "
#: Grammatical, on topic, and says nothing that could be checked against a file.
FILLER = (
    "The corpus is an important object of study and the question is a longstanding one. "
    "Careful attention was paid throughout, and the approach follows established practice. "
)


def draft(body: str) -> str:
    return f"## What I Did\n\n{body}\n\n## Key Results\n\nAll counts above are from the run.\n"


def stage_01_weight_pool() -> float:
    return sum(
        criterion.weight
        for criterion in CRITERIA
        if (criterion.min_stage or 1) <= 1 and (criterion.max_stage or 99) >= 1
    )


class PaddingDoesNotPayTests(unittest.TestCase):
    def test_filler_does_not_raise_the_criterion(self) -> None:
        lean = _score_commitment(draft(WORK * 6 + HEDGE)).score
        padded = _score_commitment(draft(WORK * 6 + HEDGE + FILLER * 30)).score
        self.assertEqual(lean, padded)

    def test_filler_does_not_buy_a_promotion(self) -> None:
        """The number that matters is the stage total the ratchet compares.

        A criterion moving a little is harmless; a criterion moving enough to clear
        `DEFAULT_MIN_GAIN` on the weighted total is a champion recorded for padding.
        """
        lean = _score_commitment(draft(WORK * 6 + HEDGE)).score
        padded = _score_commitment(draft(WORK * 6 + HEDGE + FILLER * 30)).score
        weight = CRITERIA_BY_KEY["commitment"].weight
        moved = (padded - lean) * weight / stage_01_weight_pool()
        self.assertLess(moved, DEFAULT_MIN_GAIN)

    def test_the_gradient_is_absent_at_every_length_tried(self) -> None:
        """Not just the endpoints: no monotone climb hiding between them."""
        scores = {
            _score_commitment(draft(WORK * 6 + HEDGE + FILLER * n)).score
            for n in (0, 1, 4, 10, 30, 60)
        }
        self.assertEqual(len(scores), 1, f"length moved the score: {sorted(scores)}")


class WorkIsStillRewardedAndPlansAreStillPunishedTests(unittest.TestCase):
    def test_a_report_that_is_mostly_plan_scores_badly(self) -> None:
        score = _score_commitment(draft("Set up the environment. " + HEDGE * 4)).score
        self.assertLess(score, 0.35)

    def test_a_long_work_dense_report_keeps_its_allowance(self) -> None:
        """Ordinary scientific caution in a report full of results is not a plan.

        The old comment — "One hedge per 200 words is ordinary scientific caution" —
        had the right intent and the wrong denominator. Three hedges across eighty
        sentences of measured work must not read as a plan. Under the old rule the
        same draft scored 0.4545, because it was punished for the words the work
        needed.
        """
        score = _score_commitment(draft(WORK * 40 + HEDGE * 3)).score
        self.assertGreater(score, 0.95)

    def test_the_same_hedges_cost_more_in_a_thinner_report(self) -> None:
        """Density, not a flat per-hedge fine. The criterion is a ratio or it is nothing."""
        dense = _score_commitment(draft(WORK * 40 + HEDGE * 3)).score
        thin = _score_commitment(draft(WORK * 4 + HEDGE * 3)).score
        self.assertGreater(dense, thin)

    def test_hedges_still_cost_something(self) -> None:
        clean = _score_commitment(draft(WORK * 6)).score
        hedged = _score_commitment(draft(WORK * 6 + HEDGE * 3)).score
        self.assertEqual(clean, 1.0)
        self.assertLess(hedged, clean)

    def test_the_observed_string_names_the_denominator(self) -> None:
        """A reader has to be able to see why, or the shortfall is unactionable."""
        observed = _score_commitment(draft(WORK * 6 + HEDGE)).observed
        self.assertIn("sentence(s) carrying a quantity or a path", observed)


class TheProhibitionInThePromptIsTrueTests(unittest.TestCase):
    """The prompt makes a promise about every criterion. Hold it to that.

    Asserting the sentence is present would pass while the sentence was false, which
    is how this survived: `tests/test_evolution.py` already checks the string is
    rendered. This checks the claim.
    """

    def test_no_criterion_scored_from_markdown_alone_has_a_length_gradient(self) -> None:
        from src.rubric import _score_quantification, _score_traceability

        for name, scorer in (
            ("commitment", _score_commitment),
            ("quantification", _score_quantification),
            ("traceability", _score_traceability),
        ):
            lean = draft(WORK * 6 + HEDGE)
            padded = draft(WORK * 6 + HEDGE + FILLER * 30)
            with self.subTest(criterion=name):
                before = scorer(lean)
                after = scorer(padded)
                self.assertLessEqual(
                    getattr(after, "score", after),
                    getattr(before, "score", before) + 1e-9,
                    f"{name} rose on filler alone",
                )


if __name__ == "__main__":
    unittest.main()
