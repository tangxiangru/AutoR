"""Keep the drafts that are best at *something*, not only the one best on average.

A single scalar picks one winner and throws the rest away. That is the right move
when the candidates differ by quality; it is the wrong move when they differ by
*shape*, which is what actually happens across refinement rounds. One draft has
every file reference resolving and no numbers in it. The next has the numbers and
broke two references. Averaged, they are indistinguishable and the loop keeps
whichever came second. Neither is the draft that should exist, and the ingredients
for that draft are sitting in the two of them.

GEPA (Agrawal et al., arXiv 2507.19457) makes this point about *tasks*: a prompt
that wins on one task and loses on another should stay in the pool, because a
scalar average would evict a specialist that is the only source of some capability.
The frontier here is over rigour criteria rather than tasks, which fits a research
stage better — there is only one task, and the interesting variation is which
dimension of it a draft got right.

The consequence used downstream is the merge. When the frontier holds two drafts
with complementary strengths, :func:`complementary_pair` names them and says which
criteria each one owns, and :mod:`src.evolution` spends a round asking for the
draft that keeps both — a targeted request, not "try again".

Nothing here reads a total. Domination is over the criterion vector, so a draft
cannot enter the frontier by being slightly better at the one criterion that
happens to carry the most weight.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .rubric import StageScore


#: Criterion scores are floats derived from counts and ratios, so two drafts that
#: differ only by floating-point noise are the same draft. Without this, a rerun
#: that changed nothing would read as a strict improvement and enter the frontier.
EPSILON = 1e-6


def _vector(score: StageScore) -> dict[str, float]:
    return {item.key: item.score for item in score.criteria}


def comparable(left: StageScore, right: StageScore) -> bool:
    """Two scores may only be ranked when they measure the same thing.

    A rubric version bump changes what the numbers mean. Ranking across one would
    show every draft measured under the old version suddenly rising or falling,
    with nothing in the run having changed — the reason every consumer here
    refuses rather than coercing.
    """
    if not left.comparable_to(right):
        return False
    return set(_vector(left)) == set(_vector(right))


def dominates(left: StageScore, right: StageScore) -> bool:
    """``left`` is at least as good on every criterion and strictly better on one."""
    if not comparable(left, right):
        return False
    left_vector, right_vector = _vector(left), _vector(right)
    strictly_better = False
    for key, value in left_vector.items():
        other = right_vector[key]
        if value < other - EPSILON:
            return False
        if value > other + EPSILON:
            strictly_better = True
    return strictly_better


def frontier(scores: Iterable[StageScore]) -> list[StageScore]:
    """The non-dominated subset, in descending total order.

    Ordering by total is presentation only: the frontier is a set, and the order
    exists so a human reading the ledger sees the strongest candidate first.
    """
    pool = list(scores)
    kept: list[StageScore] = []
    for candidate in pool:
        if any(dominates(other, candidate) for other in pool if other is not candidate):
            continue
        # Two candidates with identical vectors dominate neither. Keep the earlier
        # one: a later attempt that measured the same is not an improvement, and
        # letting it in would grow the frontier without adding anything.
        if any(_vector(other) == _vector(candidate) for other in kept):
            continue
        kept.append(candidate)
    kept.sort(key=lambda item: item.total, reverse=True)
    return kept


@dataclass(frozen=True)
class FrontierUpdate:
    """What happened when a candidate was offered to the frontier."""

    #: ``entered`` — the candidate is non-dominated and is now on the frontier.
    #: ``dominated`` — an existing candidate is at least as good everywhere.
    #: ``duplicate`` — an existing candidate has the identical criterion vector.
    #: ``incomparable`` — a rubric version or criterion-set mismatch; refused.
    verdict: str
    members: tuple[StageScore, ...]
    #: Members the candidate pushed off the frontier, if any.
    evicted: tuple[StageScore, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.verdict == "entered"


def insert(members: Sequence[StageScore], candidate: StageScore) -> FrontierUpdate:
    """Offer a candidate to the frontier and say what became of it."""
    usable = [item for item in members if comparable(item, candidate)]
    if len(usable) != len(members):
        # A mismatch means the stored frontier was measured under a different
        # rubric. Refusing is the honest outcome: silently dropping the stale
        # members would erase the record of what the earlier drafts scored.
        return FrontierUpdate("incomparable", tuple(members))

    for existing in usable:
        if _vector(existing) == _vector(candidate):
            return FrontierUpdate("duplicate", tuple(members))
    if any(dominates(existing, candidate) for existing in usable):
        return FrontierUpdate("dominated", tuple(members))

    evicted = tuple(existing for existing in usable if dominates(candidate, existing))
    survivors = [existing for existing in usable if existing not in evicted]
    survivors.append(candidate)
    survivors.sort(key=lambda item: item.total, reverse=True)
    return FrontierUpdate("entered", tuple(survivors), evicted)


@dataclass(frozen=True)
class Complement:
    """Two frontier members that are each the only source of some strength."""

    left: StageScore
    right: StageScore
    #: Criteria on which ``left`` beats ``right``, worst gap first.
    left_wins: tuple[str, ...]
    right_wins: tuple[str, ...]
    #: Total weighted score a draft would reach by taking the better of the two on
    #: every criterion. The headroom a merge round is chasing.
    merged_ceiling: float

    @property
    def headroom(self) -> float:
        return self.merged_ceiling - max(self.left.total, self.right.total)


def complementary_pair(members: Sequence[StageScore]) -> Complement | None:
    """The frontier pair whose merge would gain the most, or ``None``.

    Returns ``None`` when the frontier holds fewer than two comparable members, or
    when no pair is genuinely complementary — one draft beating another everywhere
    it differs is not a merge opportunity, it is a champion.
    """
    best: Complement | None = None
    for index, left in enumerate(members):
        for right in members[index + 1:]:
            if not comparable(left, right):
                continue
            left_vector, right_vector = _vector(left), _vector(right)
            weights = {item.key: item.weight for item in left.criteria}

            left_wins = tuple(
                key
                for key in sorted(
                    left_vector,
                    key=lambda k: (left_vector[k] - right_vector[k]) * weights.get(k, 1.0),
                    reverse=True,
                )
                if left_vector[key] > right_vector[key] + EPSILON
            )
            right_wins = tuple(
                key
                for key in sorted(
                    right_vector,
                    key=lambda k: (right_vector[k] - left_vector[k]) * weights.get(k, 1.0),
                    reverse=True,
                )
                if right_vector[key] > left_vector[key] + EPSILON
            )
            if not left_wins or not right_wins:
                continue

            total_weight = sum(weights.values()) or 1.0
            ceiling = (
                sum(
                    max(left_vector[key], right_vector[key]) * weights.get(key, 1.0)
                    for key in left_vector
                )
                / total_weight
            )
            candidate = Complement(left, right, left_wins, right_wins, ceiling)
            if best is None or candidate.headroom > best.headroom:
                best = candidate
    return best


def format_frontier_for_prompt(members: Sequence[StageScore]) -> str:
    if not members:
        return "(empty)"
    lines = ["| Attempt | Total | Strong on | Weak on |", "| --- | --- | --- | --- |"]
    for score in members:
        ordered = sorted(score.criteria, key=lambda item: item.score, reverse=True)
        strong = ", ".join(item.key for item in ordered if item.score >= 0.999) or "—"
        weak = ", ".join(item.key for item in reversed(ordered) if item.score < 0.999) or "—"
        lines.append(f"| {score.attempt_no} | {score.total:.3f} | {strong} | {weak} |")
    return "\n".join(lines)
