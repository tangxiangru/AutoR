"""Something that watches the whole walk while the walk is still happening, and acts.

Every other decider in the tree is local. :mod:`src.evolution` ranks the drafts of one
stage. :mod:`src.router` picks the next edge at one node, from state at that node.
:mod:`src.archive` compares runs that already finished. :mod:`src.review_panel` and
:mod:`src.validity_review` judge content rather than spend. :mod:`src.effort` is the
closest relative and is still a different thing: it assigns a tier *ahead of time*, from
the stage's identity, and never looks at what the stage went on to cost. Nothing looked at
the run as a whole while there was still money to save, and nothing acted on what it saw.

The deliverable here is interventions, not a report
---------------------------------------------------
There is no view in this module, no progress artifact, no terminal summary, and nothing
formatted for a person. The README's Limits section already records the defect of building
the other thing -- "the self-measurement files feed a report, not a decision" -- and a
second one would be a regression dressed as a feature. What is written is
:data:`SUPERVISOR_LEDGER_FILENAME`, one line per ruling, so an intervention can be audited
afterwards; that is the whole output.

It wakes inside a stage
-----------------------
:meth:`RunSupervisor.review_attempt` is called at the top of the attempt loop, next to the
existing stuck check, and :meth:`RunSupervisor.review_stage_exit` at the stage boundary.
The failure this exists to prevent happens *within* a stage -- a visit burning attempt
after attempt against one unchanging objection -- so a supervisor that only woke between
stages would watch the money leave and comment afterwards.

What it reads, and what it may not
----------------------------------
Only the harness-written per-stage cost ledger (:mod:`src.stage_cost`): the closed rows
via :func:`~src.stage_cost.read_stage_cost_ledger`, and the open
:class:`~src.stage_cost.StageCostMeter` for the visit in progress. Never a field the agent
wrote. The operator runs ``bypassPermissions`` at ``cwd=run_root`` and every stage prompt
directs it at ``workspace/``, so a supervisor that believed anything under ``workspace/``
would be a supervisor the supervised party writes.
``SupervisorReadsOnlyHarnessFieldsTests`` resolves every ``paths.<field>`` this module
touches against ``build_run_paths`` and fails if one lands under ``workspace/``.

The invariant: it may never make a gate pass
--------------------------------------------
It cannot approve a stage, open a guarded edge, discharge an obligation, satisfy a
validator, or raise any budget's total. It may stop, it may reallocate inside a total it
never increases, and it may choose among moves the guards have already left open. Three
things in the code, not in this paragraph, are what hold that:

* :meth:`AttemptAllowance.ceiling` is a :func:`min` against the run's own
  ``--max-attempts``. No state of the allowance ledger can return a larger number than the
  run already allows, so no intervention can buy an attempt the run had not already
  bought. A run that declared no ceiling gets ``None`` back and no pool: the supervisor
  does not invent a bound the operator declined, and does not invent a budget to move.
* :meth:`AttemptAllowance.transfer` moves units between stages and asserts
  :meth:`AttemptAllowance.conserved` on the way out. The total is fixed at construction and
  there is no method that raises it.
* :data:`INTERVENTION_EFFECTS` is the complete list of what a caller may do with a ruling,
  and the only one that changes control flow inside a stage is "end the visit", which hands
  to ``_handle_stage_exhaustion`` -- the recovery path that already exists, whose two
  outcomes are an explicit skip stub and an abort. Neither writes an approval.

This is the shape two rules in the tree already have, and it is stated in those terms on
purpose: the archive may reorder which move is preferred and may never open a guarded
edge, and the cross-model reviewer is a veto and never an override. Three independent
reviews refused wiring a learned statistic into ``default_move`` because it would put an
unrandomised, guard-selected number in charge at the moment a guard has just failed. A
supervisor that cannot add cannot make that mistake, and this one cannot add.

Every threshold here was measured, and what against
----------------------------------------------------
The replay is ``tools/supervisor_threshold_replay.py``. The population is the first live
paired trial under ``/rmeng_data/robtang/rcb-trial-graph``: its three finished runs, which
are 22 stage visits and 141 attempt-loop iterations, reconstructed from each run's
``logs.txt``. A fourth run was still walking when this was measured; it fires no rule and
pointing the replay at all four reports a larger population and the same firings. The
replay calls the predicates below rather than reimplementing them, so a threshold that
moves here moves there, and the numbers in this docstring describe what this code does
rather than what a second copy of it did.

:data:`STOP_AFTER_IDENTICAL_FAILURES` **= 2.** Two identical failure digests in a row
happened three times over the 22 visits, three in a row once, and four in a row never.
The three at ``N=2`` are Astronomy_000 linear ``03_study_design`` and Chemistry_000
adaptive ``03_study_design`` -- both repeating the same ``report_plan.json task output N
states nothing`` refusal, both cut after attempt 2 where the visit ran to attempt 10 and
was auto-skipped anyway -- and Astronomy_000 linear ``07_writing``, the one visit the
existing :func:`~src.utils.is_stuck` also ends. **None of the three went on to be
approved**, so no measured visit that reached an approval loses an attempt, and 17 of the
141 iterations are not bought for the same three outcomes. ``N=3`` fires only on the visit
``is_stuck`` already ends, and buys nothing.

Two honest limits on that. Every repeat in the three runs was a *validator* error -- a
reviewer's and a cross-reviewer's reasons are model prose and never repeat byte for byte
-- so reading the whole census rather than only the validation errors moved no firing on
this data, and what changed the count was 2 rather than 3. And the looser rule of
repeating the failure *kind* is refused by the same replay, which prints it as a control:
13 of 22 visits at two, and at three only 2 visits for a single iteration, because a kind
repeats three times only at the end of a visit where there is nothing left to save.

:data:`DISPROPORTIONATE_MULTIPLE` **= 2** and
:data:`MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION` **= 3.** The comparison is against the run's
own distribution rather than a declared ceiling: a stage's charged attempts summed over
its visits, against the median of the stages that have closed. At ``2x`` with three closed
stages the rule fires on 2 of the 22 visits, both the *second* visit to a stage in
Astronomy_000 adaptive -- the one run in the trial that took a real backward edge --
``06_analysis`` at 5 charged against a median of 2, and ``07_writing`` at 5 against 2.
``2.5x`` and ``3x`` fire on nothing. ``1.5x`` fires on three, one of them the *first*
visit to ``07_writing``, which went on to be approved. Requiring only two closed stages
rather than three changes nothing at ``2x`` on this data and adds two more firings at
``1.5x``; three is the minimum anyway, because a median over a run's first two stages is a
median over its two cheapest. Both firings survive the replay's ``after_stop_spending``
column, which re-runs the sweep with the visits :data:`STOP_SPENDING` has already cut
removed -- a proportionality rule that counts those is taking credit for another rule's
work, and at ``1.5x`` with two closed stages it does.

In both firings the ration :func:`ration` leaves -- 5 charged plus the run's median of 2,
so 7 -- is above the 5 either stage charged in total, so no attempt would have been taken
from a visit that was later approved, and one unit of allowance would have moved to
``08_dissemination``, the only stage that run had not entered. A stage that has already
charged more than its allowance less the median has no unspent units at all and gets a
``continue``: budget that is spent cannot be reallocated, which is arithmetic rather than
policy, and it is why the rule is checked for a surplus before it is recorded.

:data:`UNSETTLED_VISITS_BEFORE_A_REDIRECT` **= 2**, and it fires on none of the 22. Two is
the first count at which "this stage failed the same way twice" can be said at all, and
the replay finds no stage in the trial reaching it: the only stage pair visited twice --
``06_analysis`` and ``07_writing`` in Astronomy_000 adaptive -- had an approved first
visit each. That is the number worth reporting about this rule, because it is the one that
says the trial's single backward edge would have been left alone.

:data:`NO_RECOVERY_LEFT` fires on 1 of the 22 and takes one iteration away, at
Astronomy_000 linear ``07_writing`` with all three auto-skips already spent -- the visit
that ended that run as ``run_status: cancelled``. That it takes only one is the whole
design of its third precondition, and the number the replay prints beside it. Without that
precondition the rule fires at the *first* attempt boundary of the writing stage on every
run that reached it by routing to the deliverable, which is every run whose skip budget is
spent, and ends the deliverable stage before it has run once -- the opposite of the trade
``_route_to_deliverable`` exists to make.

**Early in a run, before there is a distribution, it does nothing.** Fewer than
:data:`MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION` closed stages and
:data:`DISPROPORTIONATE_SPEND` cannot fire at all; the ruling is ``continue`` and the
reason recorded names which precondition was short. :data:`UNCHANGING_FAILURE` needs no
distribution -- it is a repeat count inside one visit -- so it is live from the first
visit of the run. A guess standing in for the distribution is the thing not on offer.

The pool cost the measured runs nothing, which is also measured. Reconstructed charged
attempts came to 22, 21 and 31 per run against a total of 64 for a benchmark run's eight
stages at ``--max-attempts 8``, so the run-level half was never near binding. The
per-stage half can only bind on a revisit, and the trial contains exactly one revisit pair
-- ``06_analysis`` and ``07_writing`` in Astronomy_000 adaptive -- whose first visits
charged 2 and 4, leaving 6 and 4 for the second visits, which charged 3 and 1. Neither
would have been shortened. An envelope nothing pressed against is an envelope that cost
nothing; it is here because :data:`REALLOCATE` has to have a total to conserve, and a
total invented at the moment of the first transfer would be one the run never agreed to.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .stage_cost import HUMAN_REFUSED, StageCostMeter, read_stage_cost_ledger
from .utils import RunPaths, append_jsonl


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

#: Nothing. Recorded anyway, because a supervisor that speaks only when it acts cannot be
#: audited: a reader of the ledger has to be able to tell "it looked and let this pass"
#: from "it never looked".
CONTINUE = "continue"

#: Cut the stage's remaining attempts now and hand to the recovery path that already
#: exists. Not a verdict on the work: the recovery path writes an explicit skip stub or
#: aborts, and neither of those is an approval.
STOP_SPENDING = "stop_spending"

#: Move unspent attempt allowance between stages. Conserves the run total exactly and
#: never raises it; see :meth:`AttemptAllowance.transfer`.
REALLOCATE = "reallocate"

#: Require the next move out of this stage to be a named edge. Only ever an edge the
#: guards already leave open -- the supervisor picks from the admissible set it is handed
#: and cannot add to it.
REDIRECT = "redirect"

#: Mark the run for a human and stop spending on this stage. Last resort.
ESCALATE = "escalate"

#: The whole vocabulary, declared and bounded, in the shape ``BLOCK_KINDS``, the
#: scorecard's verdicts and the gate trust levels already have.
INTERVENTIONS: tuple[str, ...] = (
    CONTINUE,
    STOP_SPENDING,
    REALLOCATE,
    REDIRECT,
    ESCALATE,
)

#: What a caller is permitted to do with each ruling, exhaustively. Nothing in this table
#: approves a stage, opens an edge, discharges an obligation or satisfies a validator, and
#: the one entry that changes control flow inside a stage names the recovery path that
#: already exists rather than a new one.
INTERVENTION_EFFECTS: dict[str, str] = {
    CONTINUE: "nothing",
    STOP_SPENDING: "end the visit through the existing stage-exhaustion recovery path",
    REALLOCATE: "move attempt allowance between stages inside a conserved total",
    REDIRECT: "name one of the moves the guards already left open",
    ESCALATE: "end the visit through the existing recovery path and mark the run for a human",
}


# ---------------------------------------------------------------------------
# The rules, one per intervention that is not the default
# ---------------------------------------------------------------------------

#: The default's rule. Named rather than left blank so every row in the ledger carries the
#: same two columns and a reader never has to interpret an absence.
NOTHING_TO_DECIDE = "nothing_to_decide"

#: The same failure, unchanged, enough times that another attempt at it cannot help.
UNCHANGING_FAILURE = "unchanging_failure"

#: This stage has consumed several times what a stage of this run consumes.
DISPROPORTIONATE_SPEND = "disproportionate_spend"

#: This stage has now failed to settle twice, so a third visit is not the move.
UNFUNDED_REVISIT = "unfunded_revisit"

#: The auto-skip budget is spent and the run is at the stage that writes the deliverable,
#: which is the exact state in which ``_route_to_deliverable`` has nowhere left to route.
NO_RECOVERY_LEFT = "no_recovery_left"

#: Every rule this module can decide on. A registry rather than a set of ``if`` branches
#: for the same reason ``GUARDS`` and ``FEATURES`` are registries: a new rule joins the
#: gate table in ``tests/test_writable_decisive_fields.py`` or fails it.
SUPERVISOR_RULES: tuple[str, ...] = (
    NOTHING_TO_DECIDE,
    UNCHANGING_FAILURE,
    DISPROPORTIONATE_SPEND,
    UNFUNDED_REVISIT,
    NO_RECOVERY_LEFT,
)


# ---------------------------------------------------------------------------
# The measured thresholds
# ---------------------------------------------------------------------------

#: Failure kinds the repeat rule does not count.
#:
#: A person who asks for the same change twice is exercising judgement AutoR has no
#: standing to overrule. :data:`~src.utils.MAX_AUTOMATED_SENDBACKS` draws that line in
#: those words for the reviewer's budget; this is the same line drawn on the attempt
#: budget, and without it a supervisor built to bound an automated loop would be bounding
#: a person instead. Measured cost: none. All four trial runs ran ``approval_mode: agent``,
#: so no human refusal appears anywhere in the population the thresholds were measured
#: over, and excluding the kind moves no firing in the replay.
NOT_COUNTED_AS_A_REPEAT: tuple[str, ...] = (HUMAN_REFUSED,)

#: Attempts that must still be at stake for :data:`STOP_SPENDING` to be worth taking.
#:
#: The intervention exists to stop money leaving. When the run's own ceiling is one attempt
#: from ending the visit, stopping it now renames an event the exhaustion path is about to
#: record at the next boundary anyway, and the run already has a name for that event.
#:
#: Measured cost on the trial: none, and the replay prints both columns to show it. The
#: four runs walked under ``--max-attempts 8`` and all three firings land at attempt 2
#: with six still at stake, so the rule fires identically with the condition and without
#: it. What the condition changes is a run whose ceiling is tight: at ``--max-attempts 3``
#: the second identical failure arrives with one attempt left, and there the supervisor
#: would be relabelling the exhaustion rather than preventing it.
MIN_ATTEMPTS_AT_STAKE = 2

#: Identical failure digests in a row before :data:`STOP_SPENDING`.
#:
#: Measured, not chosen. Over the 26 stage visits of the first live paired trial two in a
#: row happened three times, three once and four never; at two the rule fires on three
#: visits, none of which went on to be approved, and saves 17 of the run set's 162
#: attempt-loop iterations. At three it fires only on the visit
#: :func:`~src.utils.is_stuck` already ends. ``tools/supervisor_threshold_replay.py`` is
#: the replay and prints both columns.
STOP_AFTER_IDENTICAL_FAILURES = 2

#: How many times the run's own median a stage may consume before :data:`REALLOCATE`.
#:
#: Measured against the same 26 visits: at ``2x`` the rule fires twice, both on a second
#: visit in the one run that took a backward edge; ``2.5x`` and ``3x`` fire on nothing and
#: ``1.5x`` reaches a visit that was approved.
DISPROPORTIONATE_MULTIPLE = 2

#: Closed stages needed before there is a distribution to be disproportionate against.
#:
#: Three, measured: at two, the rule picks up two further visits that
#: :data:`STOP_SPENDING` has already cut, and the median is being taken over a run's first
#: two stages, which are its cheapest. Below this the supervisor does nothing rather than
#: guessing what a typical stage of this run costs.
MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION = 3

#: Visits that ended without an approval before a stage stops being funded for another
#: one. Two rather than a measured larger number because two is the first count at which
#: "this stage failed the same way twice" can be said at all, and the replay finds no
#: stage in the trial reaching even that: the only stage pair visited twice
#: (``06_analysis`` and ``07_writing`` in Astronomy_000 adaptive) had an approved first
#: visit, so :data:`UNFUNDED_REVISIT` fires on none of the 26.
UNSETTLED_VISITS_BEFORE_A_REDIRECT = 2

#: Where the rulings go. Run root, beside the stage cost ledger and for the same reason:
#: the operator is sent at ``workspace/``, and a record of the decisions taken about a
#: party's spending must not sit where that party is told to write. JSON Lines rather than
#: a rewritten document because every ruling is recorded, including the ones that did
#: nothing, and a file rewritten once per attempt is a file that grows quadratically.
SUPERVISOR_LEDGER_FILENAME = "supervisor_ledger.jsonl"

#: Bumped when a row grows or loses a field, so a reader that predates a change can say so
#: rather than reading a missing key as a zero.
SUPERVISOR_LEDGER_VERSION = 1


# ---------------------------------------------------------------------------
# The predicates, separately callable so the replay runs the rule and not a copy
# ---------------------------------------------------------------------------


def longest_unchanged_run(digests: Sequence[str]) -> int:
    """The longest unbroken run of one digest in *digests*.

    ``0`` for a visit that recorded nothing and ``1`` for one whose failures were all
    different. :class:`~src.stage_cost.StageCostMeter` computes the same thing for the
    open visit; this is here for the closed rows, whose ``attempt_digests`` come back off
    disk as dictionaries, and for the replay.
    """
    longest = 0
    run = 0
    previous: str | None = None
    for digest in digests:
        run = run + 1 if digest == previous else 1
        previous = digest
        longest = max(longest, run)
    return longest


def countable_digests(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """The digests a repeat rule may count, in order.

    Everything :data:`NOT_COUNTED_AS_A_REPEAT` names is dropped rather than treated as a
    break in the run, because a human asking twice for the same change is not evidence
    about whether the *automated* loop is going anywhere -- and treating it as a break
    would let one human comment between two identical validator refusals hide them from
    the rule.
    """
    return [
        str(entry.get("digest") or "")
        for entry in entries
        if entry.get("kind") not in NOT_COUNTED_AS_A_REPEAT and entry.get("digest")
    ]


def unchanging_failure(digests: Sequence[str], *, repeats: int = STOP_AFTER_IDENTICAL_FAILURES) -> bool:
    """Whether the same failure has now happened *repeats* times with nothing changing.

    Consecutive rather than merely frequent. "The same objection again" and "the same
    objection again and again" are different claims, and only the second one says another
    attempt cannot help: a stage alternating between two objections is being told
    different things each time and is still making progress of a kind.
    """
    return repeats > 0 and longest_unchanged_run(digests) >= repeats


def disproportionate(
    spent: int,
    closed: Sequence[int],
    *,
    multiple: int = DISPROPORTIONATE_MULTIPLE,
    minimum_population: int = MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION,
) -> bool:
    """Whether *spent* is out of proportion to what a stage of this run costs.

    *closed* is one number per stage that has finished -- its charged attempts summed over
    its visits. The comparison is against the run's own median rather than against a
    declared ceiling, because a ceiling is a claim about every run and a median is a claim
    about this one, and the ceiling was measured not to be the binding budget anyway.

    ``False`` while the population is smaller than *minimum_population*. That is the
    answer to "what does it do before there is a distribution", and it is deliberately
    "nothing": a median over one or two stages is a median over a run's opening stages,
    which are its cheapest.
    """
    if multiple <= 0 or len(closed) < minimum_population:
        return False
    median = statistics.median(closed)
    return median > 0 and spent > multiple * median


def ration(spent: int, closed: Sequence[int]) -> int:
    """What a stage put back on the run's own average ration is left with.

    *spent* plus the median closed stage, floored at one more attempt. The floor is
    structural rather than a taste: a ration of zero is :data:`STOP_SPENDING`, which has
    its own precondition and its own record, and collapsing the two would leave the ledger
    unable to say which rule ended a visit.
    """
    if not closed:
        return spent + 1
    return spent + max(1, int(round(statistics.median(closed))))


def charged_attempts(row: Mapping[str, Any]) -> int:
    """Attempts a closed ledger row charged against ``--max-attempts``.

    A polish round improves work that already passed validation and the attempt loop does
    not charge it, so neither does this. Reading the two fields and subtracting rather
    than trusting one of them is what keeps this in step with the loop's own comparison.
    """
    try:
        attempts = int(row.get("attempts") or 0)
        polish = int(row.get("polish_rounds") or 0)
    except (TypeError, ValueError):
        return 0
    return max(attempts - polish, 0)


#: Row outcomes that mean the visit ended without the stage being approved. Spelled as a
#: set of what *is* an approval rather than a list of what is not, so a new outcome in
#: :mod:`src.stage_cost` counts as unsettled -- the conservative direction, because the
#: only thing :data:`UNFUNDED_REVISIT` does with it is decline to fund another visit.
SETTLED_OUTCOMES: tuple[str, ...] = ("approved",)


def unsettled_visits(rows: Iterable[Mapping[str, Any]], stage_slug: str) -> int:
    """How many closed visits to *stage_slug* ended without an approval."""
    return sum(
        1
        for row in rows
        if row.get("stage") == stage_slug and str(row.get("outcome") or "") not in SETTLED_OUTCOMES
    )


# ---------------------------------------------------------------------------
# The conserved total
# ---------------------------------------------------------------------------


class AllowanceError(RuntimeError):
    """A transfer that would not conserve the total, or would come from nowhere.

    Raised rather than clamped. A budget that silently rounds itself back into shape is a
    budget nobody can audit, and :meth:`RunSupervisor.review_attempt` catches this on the
    way out so a bookkeeping bug cannot fail a run that produced good work.
    """


class AttemptAllowance:
    """A run-wide attempt pool, denominated in the run's own ``--max-attempts``.

    The status quo has no run total at all: the ceiling is *per stage visit*, so a graph
    walk of ``--graph-max-steps`` steps may buy ``steps x --max-attempts`` attempts. This
    pool is ``stages x --max-attempts``, which for a benchmark run is 64 against the 160
    the walk could otherwise spend, and :meth:`ceiling` hands out
    ``min(--max-attempts, what is left)`` -- a :func:`min` against the status quo, so no
    state of this ledger can produce a visit ceiling larger than the run already allows.
    Both halves matter: the pool is what :data:`REALLOCATE` moves inside, and the ``min``
    is why moving inside it cannot buy an attempt.
    """

    def __init__(self, stage_slugs: Sequence[str], per_stage: int) -> None:
        self.per_stage = per_stage
        self.allowance: dict[str, int] = {slug: per_stage for slug in stage_slugs}
        #: Fixed at construction and read-only afterwards. There is no method that raises
        #: it, which is the point.
        self.total = sum(self.allowance.values())

    def conserved(self) -> bool:
        return sum(self.allowance.values()) == self.total

    def remaining(self, stage_slug: str, spent: int) -> int:
        """Units left for *stage_slug* after *spent* charged attempts, never negative."""
        return max(self.allowance.get(stage_slug, self.per_stage) - spent, 0)

    def ceiling(self, stage_slug: str, spent: int) -> int:
        """This visit's attempt ceiling: the run's own, or what is left, whichever is less.

        The ``min`` is the invariant. Whatever the allowance ledger has been moved to, the
        number handed back is bounded above by the ceiling the run was started with, so
        the supervisor can only ever lower it.
        """
        return min(self.per_stage, self.remaining(stage_slug, spent))

    def transfer(self, donor: str, recipients: Sequence[str], units: int) -> int:
        """Move *units* from *donor*, split as evenly as the units allow.

        Returns how many units actually moved, which is zero when there is nothing to move
        or nobody to move it to. The total is asserted on the way out rather than trusted:
        this is the one method in the module that can change a budget, and a conservation
        law nobody checks is a comment.
        """
        if units <= 0 or not recipients:
            return 0
        held = self.allowance.get(donor)
        if held is None or units > held:
            raise AllowanceError(
                f"{donor} holds {held} allowance unit(s) and cannot give away {units}"
            )
        self.allowance[donor] = held - units
        for index in range(units):
            target = recipients[index % len(recipients)]
            self.allowance[target] = self.allowance.get(target, 0) + 1
        if not self.conserved():
            raise AllowanceError(
                f"transfer of {units} from {donor} left the total at "
                f"{sum(self.allowance.values())}, not {self.total}"
            )
        return units


# ---------------------------------------------------------------------------
# A ruling
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Intervention:
    """One ruling, and everything needed to audit it.

    :attr:`evidence` carries the numbers the rule actually read, so a reader can recompute
    the decision instead of taking the sentence in :attr:`because` on trust. That is the
    difference between an audit trail and a report: nothing here is formatted, ordered or
    summarised for a person.
    """

    kind: str
    rule: str
    stage: str
    because: str
    boundary: str = "attempt"
    attempt: int = 0
    #: For :data:`REDIRECT`, the edge the supervisor names. Always one of the moves it was
    #: handed as admissible; never one it constructed.
    target: str = ""
    #: For :data:`ESCALATE`. The run has nothing left to try and a person has to look.
    needs_a_human: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)
    effect: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """A ruling outside the declared vocabulary is refused at construction.

        The same shape ``Move.__post_init__`` uses for ``BLOCK_KINDS``, and for the same
        reason: a vocabulary that is only enforced by the constant being spelled right at
        every call site is a vocabulary. Both callers of this class wrap construction in
        a handler that falls back to a ``continue`` built from literals, so the check
        cannot be the thing that ends a run.
        """
        if self.kind not in INTERVENTIONS:
            raise ValueError(
                f"{self.kind!r} is not an intervention; the vocabulary is "
                f"{', '.join(INTERVENTIONS)}."
            )
        if self.rule not in SUPERVISOR_RULES:
            raise ValueError(
                f"{self.rule!r} is not a supervisor rule; the rules are "
                f"{', '.join(SUPERVISOR_RULES)}."
            )

    @property
    def acts(self) -> bool:
        """Whether this ruling asks the caller to do anything at all."""
        return self.kind != CONTINUE

    @property
    def ends_the_visit(self) -> bool:
        """Whether the caller must hand to the stage-exhaustion recovery path."""
        return self.kind in {STOP_SPENDING, ESCALATE}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": SUPERVISOR_LEDGER_VERSION,
            "at": datetime.now().isoformat(timespec="seconds"),
            "boundary": self.boundary,
            "intervention": self.kind,
            #: The bound on what the caller was allowed to do with this ruling, written
            #: beside the ruling rather than left to a reader to look up, so the ledger
            #: answers "could this have approved anything" without leaving the file.
            "permitted_effect": INTERVENTION_EFFECTS[self.kind],
            "rule": self.rule,
            "stage": self.stage,
            "attempt": self.attempt,
            "because": self.because,
            "target": self.target,
            "needs_a_human": self.needs_a_human,
            "evidence": dict(self.evidence),
            "effect": dict(self.effect),
        }


def supervisor_ledger_path(paths: RunPaths) -> Path:
    """Where the rulings go. Run root; see :data:`SUPERVISOR_LEDGER_FILENAME`."""
    return paths.run_root / SUPERVISOR_LEDGER_FILENAME


def record_intervention(paths: RunPaths, intervention: Intervention) -> bool:
    """Append one ruling. Returns whether it landed, and never raises.

    Bookkeeping may not fail a run. A run that produced good work must not be lost because
    the account of a decision about it could not be written, and this is called from
    inside the attempt loop where an exception would replace whatever the stage was doing.
    """
    try:
        path = supervisor_ledger_path(paths)
        path.parent.mkdir(parents=True, exist_ok=True)
        append_jsonl(path, intervention.to_dict())
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# The supervisor
# ---------------------------------------------------------------------------


class RunSupervisor:
    """Reads the cost ledger, rules on the walk, and can only ever slow it down.

    Constructed once per run and asked twice per stage: at every attempt boundary and once
    on the way out of a stage. It holds no opinion about the research and reads nothing
    the agent wrote.
    """

    def __init__(self, *, stage_slugs: Sequence[str], max_auto_skips: int) -> None:
        self.stage_slugs = tuple(stage_slugs)
        self.max_auto_skips = max_auto_skips
        #: The pool, once there is a ceiling to denominate it in. ``None`` until then, and
        #: forever on a run that declared none: the supervisor does not invent a bound the
        #: operator declined, and without one there is no total for :data:`REALLOCATE` to
        #: conserve, so that rule stands down and says so.
        self.allowance: AttemptAllowance | None = None
        #: Stages already put back on the run's ration, so the surplus is moved once
        #: rather than at every subsequent attempt boundary.
        self.rationed: set[str] = set()

    # -- what the ledger says ------------------------------------------------

    def closed_spend(self, paths: RunPaths) -> dict[str, int]:
        """Charged attempts per stage, summed over the visits that have closed."""
        spend: dict[str, int] = {}
        for row in read_stage_cost_ledger(paths):
            slug = str(row.get("stage") or "")
            if not slug:
                continue
            spend[slug] = spend.get(slug, 0) + charged_attempts(row)
        return spend

    def _pool(self, per_stage: int | None) -> AttemptAllowance | None:
        """The allowance pool, created the first time a ceiling is offered.

        Lazily rather than in ``__init__`` because the ceiling is not the supervisor's to
        hold: ``ResearchManager.max_stage_attempts`` is a plain attribute a caller may set
        after construction, and a supervisor holding a copy of it would enforce a ceiling
        the run no longer has -- which, when the copy is ``None``, is no ceiling at all and
        an attempt loop that cannot end. The number is asked for at every boundary instead.

        Zero is left without a pool on purpose. It already means "allow no attempts, fail
        at once" and is how a test reaches the skip path; a pool would answer the same
        thing more slowly and with more to go wrong.
        """
        if per_stage is None or per_stage <= 0:
            return None
        if self.allowance is None:
            self.allowance = AttemptAllowance(self.stage_slugs, per_stage)
        return self.allowance

    def attempt_ceiling(self, paths: RunPaths, stage_slug: str, per_stage: int | None) -> int | None:
        """This visit's ceiling: *per_stage*, or what the stage has left, whichever is less.

        The value handed to ``attempts_exhausted`` in place of ``--max-attempts``. It is a
        :func:`min` against the ceiling the caller passed in, so it can differ from it only
        downwards, and only on a stage the run has already visited: on a first visit
        nothing has been charged and the two are equal.
        """
        pool = self._pool(per_stage)
        if pool is None:
            return per_stage
        return min(per_stage, pool.remaining(stage_slug, self.closed_spend(paths).get(stage_slug, 0)))

    # -- the attempt boundary ------------------------------------------------

    def review_attempt(
        self,
        *,
        paths: RunPaths,
        stage_slug: str,
        stage_number: int,
        meter: StageCostMeter | None,
        attempt_no: int,
        auto_skips_spent: int,
        deliverable_number: int,
        per_stage_ceiling: int | None,
    ) -> Intervention:
        """Rule on one attempt boundary, before the attempt is bought.

        Order is severity, not convenience: nothing can be salvaged once there is no
        recovery path, so :data:`ESCALATE` is asked first; a stage that cannot succeed
        should not be given a ration, so :data:`STOP_SPENDING` is asked before
        :data:`REALLOCATE`.

        *deliverable_number* is the stage the run would be routed to if this one ran out
        of budget -- ``WRITING_STAGE`` unless ``--final-stage`` names an earlier one --
        and is passed per call rather than held, because the caller can be told which
        stage that is after this object is built.
        """
        try:
            intervention = self._rule_on_attempt(
                paths=paths,
                stage_slug=stage_slug,
                stage_number=stage_number,
                meter=meter,
                attempt_no=attempt_no,
                auto_skips_spent=auto_skips_spent,
                deliverable_number=deliverable_number,
                per_stage_ceiling=per_stage_ceiling,
            )
        except Exception as error:  # pragma: no cover - defended, not expected
            # A supervisor that raises has failed the run over bookkeeping, which is the
            # one thing it is told not to do. Fall back to the ruling that changes
            # nothing, and record that it did.
            intervention = Intervention(
                kind=CONTINUE,
                rule=NOTHING_TO_DECIDE,
                stage=stage_slug,
                attempt=attempt_no,
                because=f"the supervisor could not rule on this attempt: {error}",
            )
        record_intervention(paths, intervention)
        return intervention

    def _rule_on_attempt(
        self,
        *,
        paths: RunPaths,
        stage_slug: str,
        stage_number: int,
        meter: StageCostMeter | None,
        attempt_no: int,
        auto_skips_spent: int,
        deliverable_number: int,
        per_stage_ceiling: int | None,
    ) -> Intervention:
        digests = countable_digests(meter.attempt_digests()) if meter is not None else []
        live_charged = max(meter.attempts - meter.polish_rounds, 0) if meter is not None else 0
        ceiling = self.attempt_ceiling(paths, stage_slug, per_stage_ceiling)
        at_stake = None if ceiling is None else max(ceiling - live_charged, 0)
        closed = self.closed_spend(paths)
        stage_spend = closed.get(stage_slug, 0) + live_charged
        others = [value for slug, value in closed.items() if slug != stage_slug]

        # The two conditions ``_route_to_deliverable`` returns False on, and a third that
        # keeps this from causing the failure it reports.
        #
        # The first two: the skip budget is spent, and the run is already at or past the
        # node that writes the deliverable, so there is no stage left to route a failure
        # to. Read off the stage *number* rather than the slug because ``--final-stage``
        # can move which node that is, and the routing code compares numbers for the same
        # reason.
        #
        # The third is `nothing_left_to_buy`, and it is not decoration. Without it this
        # fires at the *first* attempt boundary of the writing stage on every run that got
        # there by routing to the deliverable -- which is every run whose skip budget is
        # spent, since routing there is what spends the last of it -- and ends the visit
        # before the stage has run once. That is the opposite of the trade
        # ``_route_to_deliverable`` exists to make: spend what is left writing up rather
        # than exiting with nothing. So the last resort may only be reached at a boundary
        # the visit was going to end at anyway, and what it adds there is the mark for a
        # human, not the ending.
        nothing_left_to_buy = (at_stake is not None and at_stake <= 0) or unchanging_failure(digests)
        if (
            auto_skips_spent >= self.max_auto_skips
            and stage_number >= deliverable_number
            and nothing_left_to_buy
        ):
            return Intervention(
                kind=ESCALATE,
                rule=NO_RECOVERY_LEFT,
                stage=stage_slug,
                attempt=attempt_no,
                needs_a_human=True,
                because=(
                    f"the auto-skip budget ({self.max_auto_skips}) is spent, the run is at "
                    f"stage {stage_number}, at or past the stage that writes the deliverable "
                    f"({deliverable_number}), and this visit has nothing left to buy, so "
                    "there is nowhere left to route a failure and nobody left to ask but a "
                    "person"
                ),
                evidence={
                    "auto_skips_spent": auto_skips_spent,
                    "max_auto_skips": self.max_auto_skips,
                    "stage_number": stage_number,
                    "deliverable_stage_number": deliverable_number,
                    "attempts_at_stake": at_stake,
                    "longest_unchanged_run": longest_unchanged_run(digests),
                },
                effect={"stops_the_visit": True, "marks_the_run_for_a_human": True},
            )

        if unchanging_failure(digests) and (at_stake is None or at_stake >= MIN_ATTEMPTS_AT_STAKE):
            return Intervention(
                kind=STOP_SPENDING,
                rule=UNCHANGING_FAILURE,
                stage=stage_slug,
                attempt=attempt_no,
                because=(
                    f"the same failure has now been recorded {STOP_AFTER_IDENTICAL_FAILURES} "
                    "times running with nothing changing, so another attempt at it cannot help"
                ),
                evidence={
                    "repeats_required": STOP_AFTER_IDENTICAL_FAILURES,
                    "longest_unchanged_run": longest_unchanged_run(digests),
                    "attempts_at_stake": at_stake,
                    "digests": list(digests),
                },
                effect={"stops_the_visit": True},
            )

        pool = self._pool(per_stage_ceiling)
        unentered = [
            slug for slug in self.stage_slugs if slug not in closed and slug != stage_slug
        ]
        keep = ration(stage_spend, others) if others else 0
        surplus = (
            max(pool.allowance.get(stage_slug, 0) - keep, 0) if pool is not None else 0
        )
        # A `reallocate` that moves nothing is a mislabelled `continue`: the ledger would
        # record an intervention against a run where no budget changed hands, and the one
        # thing an audit trail may not do is overstate what was done. Both ways that
        # happens are checked here rather than left to the transfer to shrug off -- the
        # stage is already at or below its ration, and there is no stage left to give to.
        if (
            pool is not None
            and stage_slug not in self.rationed
            and surplus > 0
            and unentered
            and disproportionate(stage_spend, others)
        ):
            moved = pool.transfer(stage_slug, unentered, surplus)
            self.rationed.add(stage_slug)
            return Intervention(
                kind=REALLOCATE,
                rule=DISPROPORTIONATE_SPEND,
                stage=stage_slug,
                attempt=attempt_no,
                because=(
                    f"{stage_slug} has charged {stage_spend} attempt(s) against a median of "
                    f"{statistics.median(others)} for the {len(others)} stage(s) this run has "
                    f"closed, which is more than {DISPROPORTIONATE_MULTIPLE}x; it keeps the run's "
                    f"own ration and the surplus goes to the stages that have not run"
                ),
                evidence={
                    "stage_charged_attempts": stage_spend,
                    "closed_stage_charges": sorted(others),
                    "median": statistics.median(others),
                    "multiple": DISPROPORTIONATE_MULTIPLE,
                    "ration": keep,
                },
                effect={
                    "units_moved": moved,
                    "to": list(unentered),
                    "run_total": pool.total,
                    "total_conserved": pool.conserved(),
                },
            )

        return Intervention(
            kind=CONTINUE,
            rule=NOTHING_TO_DECIDE,
            stage=stage_slug,
            attempt=attempt_no,
            because=self._why_nothing(digests, others, at_stake),
            evidence={
                "stage_charged_attempts": stage_spend,
                "closed_stages": len(others),
                "longest_unchanged_run": longest_unchanged_run(digests),
            },
        )

    def _why_nothing(
        self, digests: Sequence[str], others: Sequence[int], at_stake: int | None = None
    ) -> str:
        """Which precondition was short, so a `continue` row says more than "nothing".

        The three cases are named separately because they are short for different reasons
        and only one of them is temporary: a distribution arrives as the run walks, a
        ceiling about to fire does not un-fire, and a failure that has not repeated may
        yet.
        """
        if unchanging_failure(digests):
            return (
                f"the same failure has repeated, but only {at_stake} attempt(s) are at "
                f"stake and stopping is worth taking at {MIN_ATTEMPTS_AT_STAKE}; the "
                "run's own ceiling ends this visit either way"
            )
        if len(others) < MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION:
            return (
                f"{len(others)} stage(s) have closed and a distribution needs "
                f"{MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION}, so there is nothing to be "
                "disproportionate against yet; no failure has repeated unchanged either"
            )
        return (
            "no failure has repeated unchanged and this stage is within the run's own "
            "spread"
        )

    # -- the stage boundary --------------------------------------------------

    def review_stage_exit(
        self,
        *,
        paths: RunPaths,
        stage_slug: str,
        admissible_forward: Sequence[str],
    ) -> Intervention:
        """Rule on the way out of a stage.

        *admissible_forward* is the set of forward targets the guards have already left
        open, computed by the graph and handed in. The supervisor picks from it and cannot
        add to it, which is why :data:`REDIRECT` can never open a guarded edge: there is
        no code path from here to :meth:`~src.stage_graph.StageGraph.moves`.
        """
        try:
            intervention = self._rule_on_stage_exit(
                paths=paths, stage_slug=stage_slug, admissible_forward=admissible_forward
            )
        except Exception as error:  # pragma: no cover - defended, not expected
            intervention = Intervention(
                kind=CONTINUE,
                rule=NOTHING_TO_DECIDE,
                stage=stage_slug,
                boundary="stage_exit",
                because=f"the supervisor could not rule on this stage exit: {error}",
            )
        record_intervention(paths, intervention)
        return intervention

    def _rule_on_stage_exit(
        self,
        *,
        paths: RunPaths,
        stage_slug: str,
        admissible_forward: Sequence[str],
    ) -> Intervention:
        rows = read_stage_cost_ledger(paths)
        unsettled = unsettled_visits(rows, stage_slug)
        if unsettled >= UNSETTLED_VISITS_BEFORE_A_REDIRECT and admissible_forward:
            target = admissible_forward[0]
            return Intervention(
                kind=REDIRECT,
                rule=UNFUNDED_REVISIT,
                stage=stage_slug,
                boundary="stage_exit",
                target=target,
                because=(
                    f"{stage_slug} has now ended {unsettled} visit(s) without an approval, so "
                    f"another visit to it is not the move; `{target}` is taken from the moves "
                    "the guards already left open"
                ),
                evidence={
                    "unsettled_visits": unsettled,
                    "threshold": UNSETTLED_VISITS_BEFORE_A_REDIRECT,
                    "chosen_from": list(admissible_forward),
                },
                effect={"names_an_open_edge": target},
            )
        return Intervention(
            kind=CONTINUE,
            rule=NOTHING_TO_DECIDE,
            stage=stage_slug,
            boundary="stage_exit",
            because=(
                f"{stage_slug} has {unsettled} visit(s) that ended without an approval, below "
                f"the {UNSETTLED_VISITS_BEFORE_A_REDIRECT} at which the run stops funding "
                "another one"
            ),
            evidence={
                "unsettled_visits": unsettled,
                "admissible_forward": list(admissible_forward),
            },
        )
