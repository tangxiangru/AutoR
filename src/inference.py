"""Exact permutation tests, and the floor each one cannot go below.

Two numbers decide whether the archive is allowed to act, and until now both were
assertions. ``DEFAULT_MIN_OBSERVATIONS = 3`` had a docstring saying "three is not
enough to be sure and is enough to stop acting on a single lucky run", which is a
sentence about intent rather than a derivation, and nothing anywhere said what a
comparison at three-a-side could attain even in principle.

It can attain 0.10. An exact two-sided permutation test over ``a`` and ``b``
observations has ``C(a+b, a)`` distinct labellings, of which two are the extremes,
so no result can go below ``2 / C(a+b, a)``. Three against three bottoms out at
0.10; against a family the size of the adaptive graph's edge set, the corrected
threshold needs six a side. The archive was licensing topology changes at a sample
size where the arithmetic forbids the claim.

The family is not a constant and the docstrings here no longer name one. `Archive`
corrects against the number of contrasts it actually has in hand, which grows as the
graph does — the adaptive topology went from eighteen edges to twenty-two while this
module was being written, and a hard-coded eighteen would have quietly under-
corrected from then on.

The distinction this module exists to keep visible is between **did not show an
effect** and **could not have shown one**. They print identically as "not
significant" and they mean opposite things: the first is evidence about the edge,
the second is evidence about how many runs you have done. Every function here
returns the attainable floor alongside the p-value so a caller cannot report one
without the other.

Exact enumeration rather than a normal approximation, because the sample sizes a
multi-hour research run permits are exactly the sizes where the approximation is
worst, and because an exact test needs no assumption anyone would have to defend.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from math import comb
from typing import Sequence


#: Enumeration is capped here. ``C(24,12)`` is 2.7 million labellings, which takes a
#: couple of seconds; beyond it the answer is already far below any threshold
#: anyone would use, so the extra precision buys nothing and the wait is real.
MAX_EXACT_TOTAL = 24

#: What a believable comparison has to clear, before any family correction.
ALPHA = 0.05


@dataclass(frozen=True)
class TestResult:
    """A p-value that carries the sample size's own limit next to it."""

    p_value: float
    floor: float
    treatment_n: int
    control_n: int
    #: True when the enumeration was capped and the p-value is an approximation
    #: from a subsample rather than the exact figure.
    approximate: bool = False

    def believable(self, *, alpha: float = ALPHA, family: int = 1) -> bool:
        """Significant *and* attainably so, at a threshold corrected for the family.

        Both halves are required. Without the second, an archive comparing *n* edges
        reports the best of *n* at an uncorrected threshold, which is the
        multiple-comparisons mistake in its purest form: with twenty edges and no
        effect anywhere, the chance that at least one clears 0.05 is about 64%.
        """
        corrected = alpha / max(family, 1)
        return self.p_value <= corrected and self.floor <= corrected

    def attainable(self, *, alpha: float = ALPHA, family: int = 1) -> bool:
        return self.floor <= alpha / max(family, 1)

    def describe(self, *, alpha: float = ALPHA, family: int = 1) -> str:
        corrected = alpha / max(family, 1)
        if not self.attainable(alpha=alpha, family=family):
            return (
                f"p={self.p_value:.4f}, but {self.treatment_n}v{self.control_n} cannot reach "
                f"{corrected:.4f} at any effect size (floor {self.floor:.4f})"
            )
        verdict = "believable" if self.p_value <= corrected else "not significant"
        return f"p={self.p_value:.4f} against {corrected:.4f} — {verdict}"


def unpaired_floor(treatment_n: int, control_n: int) -> float:
    """Smallest two-sided p an exact label-shuffle over these two arms can produce."""
    if treatment_n <= 0 or control_n <= 0:
        return 1.0
    return min(1.0, 2.0 / comb(treatment_n + control_n, treatment_n))


def paired_floor(pairs: int) -> float:
    """Smallest two-sided p an exact sign-flip over this many pairs can produce."""
    if pairs <= 0:
        return 1.0
    return min(1.0, 2.0 / (2**pairs))


def minimum_arms_for(alpha: float, *, family: int = 1) -> int:
    """Smallest equal arm size whose floor clears the corrected threshold.

    The number to quote when refusing to act. "Not enough runs" invites the reading
    that some unspecified amount more would do; "six a side is the arithmetic floor
    for a family this size at 0.05" is actionable — so pass the family you are
    actually correcting against rather than a number from a docstring.
    """
    corrected = alpha / max(family, 1)
    for size in range(1, 40):
        if unpaired_floor(size, size) <= corrected:
            return size
    return 40


def unpaired_permutation(
    treatment: Sequence[float], control: Sequence[float]
) -> TestResult:
    """Exact two-sided test on the difference of means, by shuffling the labels.

    The null is that the arm label carries no information — every way of splitting
    the pooled values into arms of these sizes is equally likely. That is the right
    null for an observational contrast between runs that took an edge and runs that
    were offered it and did not.
    """
    treatment_values = [float(value) for value in treatment]
    control_values = [float(value) for value in control]
    if not treatment_values or not control_values:
        return TestResult(1.0, 1.0, len(treatment_values), len(control_values))

    observed = abs(
        sum(treatment_values) / len(treatment_values)
        - sum(control_values) / len(control_values)
    )
    pooled = treatment_values + control_values
    size = len(treatment_values)
    total = len(pooled)
    floor = unpaired_floor(len(treatment_values), len(control_values))

    if observed == 0.0:
        return TestResult(1.0, floor, len(treatment_values), len(control_values))

    if total > MAX_EXACT_TOTAL:
        # Deterministic subsample: the first `MAX_EXACT_TOTAL` values, split in the
        # same proportion. Flagged approximate rather than silently reported as
        # exact — the floor still describes the real sample, so a caller cannot
        # mistake a truncated enumeration for a smaller one.
        keep = MAX_EXACT_TOTAL * size // total or 1
        return TestResult(
            unpaired_permutation(treatment_values[:keep], control_values[: MAX_EXACT_TOTAL - keep]).p_value,
            floor,
            len(treatment_values),
            len(control_values),
            approximate=True,
        )

    at_least_as_extreme = 0
    arrangements = 0
    for indices in itertools.combinations(range(total), size):
        arrangements += 1
        chosen = set(indices)
        left = [pooled[index] for index in indices]
        right = [pooled[index] for index in range(total) if index not in chosen]
        difference = abs(sum(left) / len(left) - sum(right) / len(right))
        if difference >= observed - 1e-12:
            at_least_as_extreme += 1

    return TestResult(
        at_least_as_extreme / arrangements,
        floor,
        len(treatment_values),
        len(control_values),
    )
