"""Paired trials: does a capability actually make the output better?

AutoR has accumulated roughly a dozen quality mechanisms — a stage graph, a
champion ratchet, review panels, effort tiers, deliberation, obligations, anchored
comments. Every one is argued for from first principles and defended by unit
tests, and **not one of them has any evidence that it improves a research
output**. The rubric measures a draft. Nothing has ever compared a run that had a
mechanism against a run that did not.

The cross-run archive (:mod:`src.archive`) was meant to be that evidence and
cannot be. Its comparisons are observational: runs differ by goal, and goal
difficulty swamps everything. Six runs on each side of a contrast tells you which
questions were easier, not which configuration was better.

A **paired trial** is the fix, and it is a small one. Run the same goal twice, once
with the capability and once without, tag both with a shared ``trial_id``, and the
statistic becomes the *within-pair difference*. Goal difficulty cancels. What is
left is the effect plus run-to-run noise, and the noise is what the pairs are for.

Three things this module refuses to do, each because the alternative would produce
a number that looks like evidence and is not:

**It does not compare across a composition difference, even inside a pair.** If the
treatment arm abandoned at Stage 06 and the control ran to Stage 08, their mean
fitness is not one measurement of two configurations — later stages are scored on
strictly more criteria, so the arm that stopped early scores higher for stopping
early. That is the same bias :func:`src.archive.comparability_basis` exists to
remove, and it reappears inside a pair. The difference is taken over the stages
*both* arms measured, and pairs whose shapes differed are counted and reported
separately, because a capability that changes how far runs get has done something
worth knowing about and it is not a score.

**It does not report a total without the criterion decomposition.** The outcome
measure is a rubric, and a rubric can be gamed. A capability that writes more files
raises ``artifact_breadth`` whether or not the research is better. A win
concentrated in one criterion is a flag, not a result, and the only way to see it
is to print the vector next to the scalar.

**It does not call an unattainable result "not significant".** An exact two-sided
paired sign-flip test over *n* pairs cannot go below ``2 / 2**n``: three pairs
bottom out at 0.25, five at 0.0625, six at 0.031. Below six pairs no result can
reach 0.05 at any effect size, and reporting "p = 0.25, not significant" invites
the reading that the capability was tested and found wanting. The floor is printed
next to the p-value so the difference between *did not show an effect* and *could
not have shown one* stays visible.

**A known crack, recorded here because it is invisible where it lives.** Above
``MAX_EXACT_PAIRS`` the enumeration truncates ``usable[:18]`` while
:attr:`TrialResult.floor` still divides by the untruncated *n*. At n = 19 the printed
p is computed from eighteen pairs and the floor printed beside it is ``2 / 2**19`` —
lower than that p can reach, which breaks the third refusal above at exactly the
point it matters. Unreachable at the sample sizes anyone has run (a paired
ResearchClawBench trial is three to six pairs), and deliberately left alone; the next
reader extending a trial to forty tasks walks straight into it and should fix the
floor, or sample the sign assignments, in a change of its own.

What this measures is the rubric score, and the rubric is a proxy for rigour rather
than a measure of insight. A capability can raise it without making the research
better, and can make the research better without raising it. The decomposition and
the shape counts are there so a reader can argue with the number instead of
accepting it.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

from .archive import RunRecord


#: Pairs below this cannot reach p < 0.05 at any effect size, because an exact
#: two-sided sign-flip test over *n* pairs bottoms out at ``2 / 2**n``.
MIN_PAIRS_FOR_SIGNIFICANCE = 6

#: Above this, the exact enumeration is replaced by the same arithmetic on a
#: sampled basis. 2**18 is a quarter of a million sign assignments, which is
#: instant; there is no reason to go further and every reason not to hang a report.
MAX_EXACT_PAIRS = 18


def min_attainable_p(pairs: int) -> float:
    """The smallest two-sided p an exact sign-flip test over ``pairs`` can produce.

    Printed beside every p-value. "p = 0.25 with a floor of 0.25" and "p = 0.25 with
    a floor of 0.008" are completely different statements about a capability, and
    only the first is a fact about the sample size rather than about the effect.
    """
    if pairs <= 0:
        return 1.0
    return min(1.0, 2.0 / (2**pairs))


def min_attainable_concentration(criteria: int) -> float:
    """The smallest concentration a decomposition over ``criteria`` keys can show.

    The same discipline as :func:`min_attainable_p`, for the same reason. The
    Goodhart threshold below is 0.6, and 0.6 was calibrated against AutoR's eight
    rubric criteria, where a perfectly even spread reads 0.125. Hand the same
    property a two-key decomposition and an even spread already reads 0.50, so
    "60% of the movement is in one criterion" stops meaning anything — it fires on
    a 1.5:1 split. Printing the floor beside the observed value is what keeps a
    reader from believing a warning whose denominator changed underneath it.
    """
    if criteria <= 0:
        return 0.0
    return 1.0 / criteria


def sign_flip_p(differences: Sequence[float]) -> float:
    """Exact two-sided paired permutation test on the mean difference.

    The null is that the sign of each pair's difference is arbitrary — which is what
    "the capability did nothing" means for a paired design. Enumerating the sign
    assignments is exact and needs no distributional assumption, which matters at
    the sample sizes a multi-hour research run permits.

    Zero differences are kept rather than dropped. Under this statistic a tie is
    neutral — flipping its sign changes no mean, so the p-value is the same either
    way — which is not true of the classical sign test, where dropping ties shrinks
    *n* and moves the answer. What keeping them changes here is the gap between the
    achieved p and :func:`min_attainable_p`: six pairs of which two were ties report
    p = 0.125 against a floor of 0.031, and that gap is the honest signal that two
    of the six carried no information. Dropping them would report n = 4 and a floor
    of 0.125, making a sample that told you less look maximally informative.
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


@dataclass(frozen=True)
class Pair:
    """Two runs of the same goal that differ by one capability."""

    trial_id: str
    control: RunRecord
    treatment: RunRecord

    @property
    def shared_stages(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.control.stage_fitness) & set(self.treatment.stage_fitness)))

    @property
    def same_shape(self) -> bool:
        return set(self.control.stage_fitness) == set(self.treatment.stage_fitness)

    def _mean_over(self, record: RunRecord, stages: Sequence[str]) -> float:
        values = [record.stage_fitness[slug] for slug in stages if slug in record.stage_fitness]
        return sum(values) / len(values) if values else 0.0

    @property
    def difference(self) -> float:
        """Treatment minus control, over the stages both arms measured.

        Not over each arm's own stages. A treatment that made the run stop earlier
        would otherwise be credited with the easier criterion set of the stages it
        reached — the same bias that let the archive reward a run for not finishing.
        """
        stages = self.shared_stages
        if not stages:
            return 0.0
        return self._mean_over(self.treatment, stages) - self._mean_over(self.control, stages)

    def criterion_differences(self) -> dict[str, float]:
        keys = set(self.control.criterion_fitness) | set(self.treatment.criterion_fitness)
        return {
            key: self.treatment.criterion_fitness.get(key, 0.0)
            - self.control.criterion_fitness.get(key, 0.0)
            for key in sorted(keys)
        }


@dataclass(frozen=True)
class TrialResult:
    capability: str
    control_arm: str
    treatment_arm: str
    pairs: tuple[Pair, ...]
    #: Pairs found but not usable, with the reason. Reported rather than dropped:
    #: an analysis over four of nine pairs is a different claim from one over nine.
    excluded: tuple[tuple[str, str], ...] = ()

    @property
    def n(self) -> int:
        return len(self.pairs)

    @property
    def differences(self) -> list[float]:
        return [pair.difference for pair in self.pairs]

    @property
    def mean_difference(self) -> float:
        values = self.differences
        return sum(values) / len(values) if values else 0.0

    @property
    def wins(self) -> int:
        return sum(1 for value in self.differences if value > 1e-9)

    @property
    def losses(self) -> int:
        return sum(1 for value in self.differences if value < -1e-9)

    @property
    def ties(self) -> int:
        return self.n - self.wins - self.losses

    @property
    def shape_changes(self) -> int:
        """Pairs whose two arms did not measure the same stages.

        Not folded into the score. A capability that changes how far a run gets has
        done something, and averaging it into a mean over shared stages would hide
        exactly the thing worth reporting.
        """
        return sum(1 for pair in self.pairs if not pair.same_shape)

    @property
    def p_value(self) -> float:
        return sign_flip_p(self.differences)

    @property
    def floor(self) -> float:
        return min_attainable_p(self.n)

    @property
    def underpowered(self) -> bool:
        return self.n < MIN_PAIRS_FOR_SIGNIFICANCE

    def criterion_differences(self) -> dict[str, float]:
        """Mean per-criterion difference across pairs, worst first.

        The Goodhart check. The rubric is a proxy, and a capability that raises one
        criterion mechanically — writing more files raises ``artifact_breadth``
        whether or not the work improved — produces a real total and a fake result.
        A win concentrated in a single criterion is a flag.
        """
        totals: dict[str, list[float]] = {}
        for pair in self.pairs:
            for key, value in pair.criterion_differences().items():
                totals.setdefault(key, []).append(value)
        return {
            key: sum(values) / len(values)
            for key, values in sorted(totals.items(), key=lambda item: -abs(sum(item[1])))
        }

    def criterion_support(self) -> dict[str, int]:
        """How many pairs each criterion's mean was taken over.

        The denominator in :meth:`criterion_differences` is per key and has never
        been printed. With AutoR's own rubric every key is present in every pair, so
        the denominator is always *n* and nobody missed it. Hand the same table an
        outcome measure whose keys are per-goal — a ResearchClawBench checklist is
        written per task — and every key has a denominator of 1, while the column
        header still says "mean difference". A single observation and a mean over
        three pairs then render identically, which is the whole of the difference
        between an anecdote and a measurement.
        """
        counts: dict[str, int] = {}
        for pair in self.pairs:
            for key in pair.criterion_differences():
                counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def concentration(self) -> float:
        """Share of the total movement sitting in the single largest criterion.

        1.0 means the whole effect is one criterion. Not a verdict — some capabilities
        legitimately target one thing — but it is the number to look at before
        believing a total.
        """
        deltas = [abs(value) for value in self.criterion_differences().values()]
        total = sum(deltas)
        return max(deltas) / total if total > 0 else 0.0


def collect_pairs(
    records: Iterable[RunRecord],
    *,
    capability: str,
    control_arm: str,
    treatment_arm: str,
) -> TrialResult:
    """Group tagged runs into pairs and say why any were dropped."""
    by_trial: dict[str, dict[str, RunRecord]] = {}
    for record in records:
        if not record.trial_id or record.capability != capability:
            continue
        by_trial.setdefault(record.trial_id, {})
        # Last write wins, matching `Archive.runs`, so a re-run of one arm replaces it.
        by_trial[record.trial_id][record.arm] = record

    pairs: list[Pair] = []
    excluded: list[tuple[str, str]] = []
    for trial_id, arms in sorted(by_trial.items()):
        control = arms.get(control_arm)
        treatment = arms.get(treatment_arm)
        if control is None or treatment is None:
            missing = control_arm if control is None else treatment_arm
            excluded.append((trial_id, f"no `{missing}` arm"))
            continue
        if not (control.usable and treatment.usable):
            excluded.append((trial_id, "an arm is a fake run or a stale rubric version"))
            continue
        pair = Pair(trial_id, control, treatment)
        if not pair.shared_stages:
            excluded.append((trial_id, "the two arms measured no stage in common"))
            continue
        pairs.append(pair)

    return TrialResult(
        capability=capability,
        control_arm=control_arm,
        treatment_arm=treatment_arm,
        pairs=tuple(pairs),
        excluded=tuple(excluded),
    )


def declared_trials(records: Iterable[RunRecord]) -> dict[str, set[str]]:
    """Capability to the arm labels seen for it."""
    found: dict[str, set[str]] = {}
    for record in records:
        if record.trial_id and record.capability:
            found.setdefault(record.capability, set()).add(record.arm)
    return found


def format_trial_report(result: TrialResult, *, unit: str = "rubric points") -> str:
    """Render a trial. ``unit`` names what the mean difference is measured in.

    A rendering concern, so it lives here and not on :class:`TrialResult`, which is a
    record about the statistics. The default keeps every existing caller byte-identical.
    It exists because the arithmetic in this module is scale-free — ``sign_flip_p`` is
    invariant to it, ``concentration`` is a ratio — and the only thing that was not was
    the literal string on the mean-difference line. Handed a ResearchClawBench total in
    0–100 points, that line printed "+24.6000 rubric points", which is a lie about the
    instrument in the one place a reader takes the number from.
    """
    lines = [
        f"## `{result.capability}`  —  `{result.treatment_arm}` against `{result.control_arm}`",
        "",
        f"- pairs: **{result.n}**"
        + (f" ({len(result.excluded)} excluded)" if result.excluded else ""),
        f"- mean difference: **{result.mean_difference:+.4f}** {unit}",
        f"- won {result.wins}, lost {result.losses}, tied {result.ties}",
    ]
    if result.n:
        lines.append(f"- exact two-sided p: **{result.p_value:.4f}** (floor at n={result.n}: {result.floor:.4f})")
    if result.underpowered:
        lines.append(
            f"- **underpowered.** Below {MIN_PAIRS_FOR_SIGNIFICANCE} pairs no result can reach "
            "p < 0.05 at any effect size. This is a fact about the sample, not about the "
            "capability."
        )
    if result.shape_changes:
        lines.append(
            f"- {result.shape_changes} pair(s) whose arms did not reach the same stages. The score "
            "above is over the stages both measured; that a capability changes how far a run gets "
            "is a separate result and is not in this number."
        )
    for trial_id, reason in result.excluded:
        lines.append(f"  - excluded `{trial_id}`: {reason}")

    deltas = result.criterion_differences()
    if deltas:
        support = result.criterion_support()
        floor = min_attainable_concentration(len(deltas))
        lines += [
            "",
            "| Criterion | Mean difference | pairs |",
            "| --- | --- | --- |",
            *[
                f"| `{key}` | {value:+.4f} | {support.get(key, 0)} |"
                for key, value in deltas.items()
            ],
            "",
            f"Concentration: **{result.concentration:.0%}** of the movement is in one criterion "
            f"(floor at {len(deltas)} criteria: {floor:.0%}).",
        ]
        if result.concentration >= 0.6 and result.n:
            lines.append(
                "That is high enough to check before believing the total. The rubric is a proxy, "
                "and a capability that raises one criterion mechanically produces a real number "
                "and a fake result."
            )
    return "\n".join(lines)


def format_all_trials(records: Sequence[RunRecord], *, arms: Mapping[str, tuple[str, str]] | None = None) -> str:
    """Every declared trial in the archive, or a note that there are none."""
    declared = declared_trials(records)
    if not declared:
        return (
            "No paired trials recorded. Tag two runs of the same goal with the same "
            "`--trial ID`, the same `--capability NAME`, and different `--arm` labels."
        )
    blocks: list[str] = []
    for capability, seen in sorted(declared.items()):
        control, treatment = (arms or {}).get(capability, _infer_arms(seen))
        blocks.append(
            format_trial_report(
                collect_pairs(
                    records, capability=capability, control_arm=control, treatment_arm=treatment
                )
            )
        )
    return "\n\n".join(blocks)


def _infer_arms(seen: set[str]) -> tuple[str, str]:
    """Pick the control and treatment labels when the caller did not say.

    ``off``/``control``/``baseline`` is the control if one of them is present;
    otherwise the labels are sorted and the first is the control, which is arbitrary
    but stable — and the report prints which is which, so an inverted sign is
    visible rather than silent.
    """
    for candidate in ("off", "control", "baseline", "0"):
        if candidate in seen:
            other = sorted(seen - {candidate})
            return candidate, other[0] if other else candidate
    ordered = sorted(seen)
    return ordered[0], ordered[-1] if len(ordered) > 1 else ordered[0]
