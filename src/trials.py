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

**It does not report a capability that selects on the outcome measure.** The
champion ratchet keeps whichever polish round scored highest and reverts the rest —
``argmax`` over drafts on ``score.total``, which is the number this module reports.
Trialling it against ``--evolve-rounds 0`` therefore cannot lose: the treatment arm is
the maximum of several draws from the same distribution the control arm draws once
from, and a generator of random drafts would show the same "effect". The mean
difference would be real, positive, and evidence of nothing. See
:data:`SELECTS_ON_THE_OUTCOME`.

That refusal is keyed on the *pair* — capability and outcome — rather than on the
capability alone, because ``argmax`` on ``score.total`` guarantees the win only while
``score.total`` is what gets printed. The same ratchet scored against an external
judge is a sound trial, and it is the one ``docs/self-improvement.md`` asks for under
"What may not be trialled": *to trial them, the outcome has to be something the
ratchet cannot see*. :mod:`src.rcb_trial` is that outcome — a benchmark judge run
after the workspace is finished, against a checklist no stage was shown — so a trial
declares which measure filled its ``stage_fitness`` and the refusal reads the
capability against *that*. The declared measures are :data:`DECLARED_OUTCOMES`, and a
:class:`TrialResult` carrying anything else is refused at construction: a call site
that could invent an outcome could exempt itself from the refusal by naming one.

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

#: Capabilities whose mechanism is selection on the rubric total. A paired trial of
#: one of these *against the rubric* measures ``max(N draws) >= 1 draw`` and nothing
#: else. Scored against a measure the run cannot read, the same capability is
#: trialable — which is why this set is a property of :data:`RUBRIC_TOTAL` and not of
#: the module.
#:
#: Found the hard way. The first paired trial anyone tried to run here was the
#: champion ratchet, ``--evolve-rounds 0`` against ``2``, and twelve real runs were
#: queued before the circularity was noticed. `EvolutionController.consider` promotes
#: a round when ``delta >= min_gain`` and reverts it otherwise, so the arm with rounds
#: is the running maximum over drafts, scored on exactly the total the report prints.
#:
#: This is not the same objection as the Goodhart one two paragraphs up. There the
#: worry is that a capability raises the proxy without improving the work. Here the
#: capability does not have to touch the work at all: the arithmetic guarantees the
#: win before the first token is generated.
#:
#: A capability belongs here if the run *reads the rubric* in order to decide what to
#: keep. `--effort-tiers`, the review panel, deliberation, the ideation panel and the
#: stage graph do not — they change what gets written, and the rubric then scores it
#: at arm's length. Those are trialable. These are not.
SELECTS_ON_THE_OUTCOME: frozenset[str] = frozenset(
    {"polish_rounds", "evolve_rounds", "evolution", "champion_ratchet", "pareto_frontier"}
)


@dataclass(frozen=True)
class Outcome:
    """The measure a trial's difference is a difference *in*.

    Three fields because the report needs three different things from it and each was
    previously a literal somewhere else: ``unit`` names the scale on the
    mean-difference line, ``measured_by`` names the instrument for a reader deciding
    whether the number is comparable to anything, and ``selected_on_by`` is what the
    circularity refusal reads. Keeping them on one object is what makes the refusal
    keyed on the pair rather than on the capability: an outcome the run can read
    during the run carries the capabilities that read it, and an outcome computed
    after the workspace is finished carries none.
    """

    #: Stable identifier, printed in the report so a reader can tell two trials of one
    #: capability apart when they were scored against different things.
    key: str
    #: The scale the mean difference is in. ``format_trial_report`` prints it.
    unit: str
    #: What computes the number, in a clause. Not the same claim as ``unit``: a 0–100
    #: total says nothing about who assigned it, and who assigned it is the whole of
    #: whether the ratchet could have optimised against it.
    measured_by: str
    #: Capabilities whose mechanism is ``argmax`` on *this* number. Empty is the
    #: ordinary case and the honest one for any measure produced after the run ends.
    selected_on_by: frozenset[str] = frozenset()

    def selects(self, capability: str) -> bool:
        return capability in self.selected_on_by


#: AutoR grading its own drafts, during the run, while it is still choosing between
#: them. The default for every caller that does not say otherwise, because it is what
#: :class:`src.archive.RunRecord` holds and it is the measure that can be gamed from
#: inside.
RUBRIC_TOTAL = Outcome(
    key="rubric_total",
    unit="rubric points",
    measured_by="AutoR's own rubric, scored during the run",
    selected_on_by=SELECTS_ON_THE_OUTCOME,
)

#: ResearchClawBench, filled by :mod:`src.rcb_trial`. ``selected_on_by`` is empty and
#: that is a claim, not an omission: the score is produced by a judge that runs after
#: the workspace is finished, against a checklist no stage was shown, so no mechanism
#: inside a run can keep a draft *because* it scores well here. A capability that read
#: a benchmark score in-loop to decide what to keep would belong in this set, and the
#: refusal would then fire on this outcome exactly as it does on the rubric.
RCB_TOTAL = Outcome(
    key="rcb_total",
    unit="RCB points (0-100 total scale)",
    measured_by="ResearchClawBench's judge, after the run, against a checklist no stage was shown",
    selected_on_by=frozenset(),
)

#: Every measure a trial may declare, by key. A registry and not a free-form string
#: for the same reason ``stage_graph.GUARDS`` is one: the failure mode of an outcome
#: nothing recognises is silence. ``circular`` would read an empty ``selected_on_by``,
#: the ratchet would report ``+0.0736, p = 0.031``, and the escape would be one
#: keyword argument at one call site. Adding a measure means adding it here, where the
#: claim that nothing selects on it is written down next to it.
DECLARED_OUTCOMES: Mapping[str, Outcome] = {
    outcome.key: outcome for outcome in (RUBRIC_TOTAL, RCB_TOTAL)
}


def outcomes_free_of(capability: str) -> tuple[Outcome, ...]:
    """Declared measures this capability's mechanism cannot select on.

    What a refusal owes the reader. "Score it on something the ratchet does not read"
    is advice; this is the list, derived from the same registry the refusal fires off,
    so a measure added to the registry appears in the refusal without anyone
    remembering to update the prose.
    """
    return tuple(
        outcome for outcome in DECLARED_OUTCOMES.values() if not outcome.selects(capability)
    )


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
    #: What filled ``stage_fitness``. Defaults to :data:`RUBRIC_TOTAL`, which is what
    #: an archived :class:`src.archive.RunRecord` carries, so every caller that does
    #: not produce its own measure keeps the behaviour it had. A producer that fills
    #: the two dicts from somewhere else declares it here, and ``circular`` is then
    #: read against the measure that was actually used.
    outcome: Outcome = RUBRIC_TOTAL
    #: Pairs found but not usable, with the reason. Reported rather than dropped:
    #: an analysis over four of nine pairs is a different claim from one over nine.
    excluded: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        """Refuse an outcome that is not in the registry, at construction.

        The same shape as ``Edge.__post_init__`` refusing an unregistered guard, for
        the same reason: the failure is silent in the direction that publishes. An
        outcome nobody declared has an empty ``selected_on_by``, so it makes
        ``circular`` false for every capability — inventing one at the call site is
        how a circular trial gets reported, and it would look like a keyword argument
        rather than like an exemption. ``dataclasses.replace`` re-runs this, so the
        rewrite in ``rcb_trial.collect_rcb_pairs`` cannot slip one past it either.
        """
        if not isinstance(self.outcome, Outcome):
            # A bare string is the natural mistake — `outcome="rubric"` reads like a
            # keyword argument and today raises `AttributeError: 'str' object has no
            # attribute 'key'` three frames away from the call. Refuse it here with the
            # registry in the message, because the whole point of this check is that an
            # outcome nobody declared exempts every capability from the refusal.
            raise TypeError(
                f"outcome must be a declared `Outcome`, not {type(self.outcome).__name__}. "
                f"Pass one of {sorted(DECLARED_OUTCOMES)} from `src.trials`."
            )
        declared = DECLARED_OUTCOMES.get(self.outcome.key)
        if declared is None:
            raise ValueError(
                f"outcome {self.outcome.key!r} is not declared. Add it to "
                "`DECLARED_OUTCOMES` with the capabilities that select on it, next to "
                "the argument that nothing does. An undeclared measure exempts every "
                "capability from the circularity refusal and reads as a spelling."
            )
        if declared != self.outcome:
            raise ValueError(
                f"outcome {self.outcome.key!r} does not match the declared one: "
                f"selected_on_by={sorted(self.outcome.selected_on_by)} against "
                f"{sorted(declared.selected_on_by)}. A trial may choose which declared "
                "measure it was scored on; it may not restate what selects on it."
            )

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

    @property
    def circular(self) -> bool:
        """The capability selects on the number this report prints.

        Reported instead of the p-value, not beside it. A reader who sees
        "+0.0736, p = 0.031" takes the number; a caveat under it does not undo
        that, and the number here is an artifact of the arithmetic rather than a
        measurement of anything.

        Read against :attr:`outcome` and not against the module. "Selects on the
        outcome" is a relation between a mechanism and a measure, and the mechanism
        that cannot lose a rubric-scored trial can lose one scored by a judge it never
        sees. Keying on the capability alone refused a sound trial — the ratchet
        against ResearchClawBench — with a message telling the reader to run exactly
        that trial.
        """
        return self.outcome.selects(self.capability)

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
    outcome: Outcome = RUBRIC_TOTAL,
) -> TrialResult:
    """Group tagged runs into pairs and say why any were dropped.

    ``outcome`` is what filled ``stage_fitness`` on these records, and the caller is
    the only one who knows: this function reads two dicts of floats and cannot tell a
    rubric mean from a benchmark total. It defaults to the rubric because the archive
    holds nothing else, and a producer that fills the dicts from another instrument
    passes its own — :func:`src.rcb_trial.collect_rcb_pairs` passes
    :data:`RCB_TOTAL`. Only a measure in :data:`DECLARED_OUTCOMES` is accepted.
    """
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
        outcome=outcome,
        excluded=tuple(excluded),
    )


def declared_trials(records: Iterable[RunRecord]) -> dict[str, set[str]]:
    """Capability to the arm labels seen for it."""
    found: dict[str, set[str]] = {}
    for record in records:
        if record.trial_id and record.capability:
            found.setdefault(record.capability, set()).add(record.arm)
    return found


def format_trial_report(result: TrialResult, *, unit: str | None = None) -> str:
    """Render a trial. ``unit`` names what the mean difference is measured in.

    A rendering concern, so it lives here and not on :class:`TrialResult`, which is a
    record about the statistics. It exists because the arithmetic in this module is
    scale-free — ``sign_flip_p`` is invariant to it, ``concentration`` is a ratio — and
    the only thing that was not was the literal string on the mean-difference line.
    Handed a ResearchClawBench total in 0–100 points, that line printed "+24.6000 rubric
    points", which is a lie about the instrument in the one place a reader takes the
    number from.

    Now an *override* of ``result.outcome.unit`` rather than a default of its own. The
    scale is a property of the measure, so a caller that declared the measure has
    already said it, and two callers saying it separately is one string that can drift
    into disagreeing with the outcome printed two lines above it. ``None`` means "the
    outcome's"; a string still wins, for a caller rendering the same result on a
    rescaled axis.
    """
    unit = result.outcome.unit if unit is None else unit
    header = f"## `{result.capability}`  —  `{result.treatment_arm}` against `{result.control_arm}`"
    # Printed on both branches, and above the number on the reporting branch. Which
    # instrument produced the difference decides whether the refusal below applies, so
    # a reader who disagrees with the verdict needs it before the verdict, not in a
    # footnote after it.
    measure = f"- outcome: `{result.outcome.key}` — {result.outcome.measured_by}"
    if result.circular:
        # No need to drop the measure just refused: it selects on this capability, which
        # is why we are here, so `outcomes_free_of` has already left it out.
        escapes = outcomes_free_of(result.capability)
        return "\n".join([
            header,
            "",
            f"- pairs: **{result.n}**",
            measure,
            f"- **refused: `{result.capability}` selects on the outcome measure "
            f"`{result.outcome.key}`.** The champion ratchet keeps the highest-scoring "
            "draft and reverts the rest, so the treatment arm is the maximum of several "
            "draws on exactly the total reported here. It cannot lose, a random draft "
            "generator would show the same effect, and a positive mean difference would be "
            "arithmetic rather than evidence.",
            "- To trial it, score the arms on something the ratchet does not read — a held-out "
            "judge, a benchmark, or a human read of the draft. "
            + (
                "Declared here: "
                + ", ".join(f"`{outcome.key}` ({outcome.measured_by})" for outcome in escapes)
                + "."
                if escapes
                else "No other measure is declared, so there is nothing to rerun this against "
                "until one is."
            ),
        ])

    lines = [
        header,
        "",
        f"- pairs: **{result.n}**"
        + (f" ({len(result.excluded)} excluded)" if result.excluded else ""),
        measure,
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
    """Every declared trial in the archive, or a note that there are none.

    No ``outcome`` parameter, and that is the refusal rather than an omission. These
    records came out of :class:`src.archive.Archive`, where ``stage_fitness`` is
    AutoR's own rubric by construction, so the measure is not the caller's to choose
    here and the ratchet stays refused on this path whatever a flag says.
    """
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
