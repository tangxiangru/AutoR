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

* :meth:`AttemptAllowance.visit_ceiling` is a :func:`min` against the run's own
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
The replay is ``tools/supervisor_threshold_replay.py`` and the population is
``tools.supervisor_threshold_replay.MEASURED_RUNS``: the three *finished* runs of the
first live paired trial under ``/rmeng_data/robtang/rcb-trial-graph``, named rather than
globbed, which reconstruct to 22 stage visits and 141 attempt-loop iterations from each
run's ``logs.txt``. Every population figure below is one of those two numbers, they are
``MEASURED_VISITS`` and ``MEASURED_ITERATIONS``, and running the replay on that invocation
prints ``population: as recorded`` or says which way it drifted. Do not quote the glob
``workspaces/*/.autor/*/``: a fourth run under the same directory is still being written,
it gave 26 visits and 166 iterations the day this branch was opened and 27 and 167 the
next, and an earlier version of this docstring claimed a denominator of 162 that no
invocation ever printed. The replay calls the predicates below rather than reimplementing
them, so a threshold that moves here moves there.

:data:`STOP_AFTER_IDENTICAL_FAILURES` **= 3.** On this population that is near-inert, which
is the honest answer and a finding about the population rather than about the rule.

Two identical failure digests in a row happened three times over the 22 visits, three in a
row once, and four in a row never. The replay's original report stopped there and read
``N=2`` as saving 17 iterations, which is what the rule *stops* rather than what it
*saves*. With :func:`~tools.supervisor_threshold_replay.bought` beside it, the same three
firings read: 17 iterations cut, **12 inert and 5 productive**. The five are a repair that
put the draft back inside the gate on attempt 3, and a promoted draft with obligations
discharged on attempt 5, in each of the two ``03_study_design`` visits that carry 16 of
the 17. And the decisive column is neither: in all three firings the draft on disk is
*outside* the gate at the moment of the cut, because a repeated **validator** refusal is
by construction a moment at which validation is failing. Both ``03_study_design`` visits
went on to end auto-skipped with a draft that did validate, so
``_validated_draft_for_skip`` kept it -- 49,347 and 23,513 bytes of stage summary. Cut at
attempt 2 and that call returns ``None`` and the 1,911-byte ``.skip_stub.md`` beside each
of them becomes Stage 03's output for every downstream stage. ``N=2`` does not buy 17
iterations; it buys 12 inert ones and pays two stage summaries for them.

So ``N=2`` is refused, and no larger value does useful work on this data either: ``N=3``
fires on 1 of the 22 visits and cuts **0** iterations, ``N=4`` and ``N=5`` fire on nothing
at all. Three is shipped as the safe value -- the smallest at which the measured cost is
zero on both columns -- and the finding recorded beside it is about the population:
**every repeat in these three runs is a validator error** (four repeat events, all
``validators_refused``, no other kind ever repeating), and a repeated validator error is
what :func:`~src.utils.is_stuck` already ends at the same count of three. What this rule
adds over ``is_stuck`` is real and unmeasurable here: ``is_stuck`` reads only
``last_validation_errors``, which the attempt loop assigns at one place, so it is blind to
a reviewer refusing identically, a cross-model veto repeating, or a backend failing the
same way; this reads the whole census. Three runs containing no such repeat cannot say
what that is worth, and the number to raise it against is a population that contains one.

The looser rule of repeating the failure *kind* is refused by the same replay, which
prints it as a control: 13 of 22 visits at two, cutting 43 iterations of which 9 were
productive; at three only 2 visits and a single iteration, and that one was productive.

:data:`DISPROPORTIONATE_MULTIPLE` **= 2** and
:data:`MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION` **= 3.** The comparison is against the run's
own distribution rather than a declared ceiling: a stage's charged attempts summed over
its visits, against the median of the stages that have closed. At ``2x`` with three closed
stages the rule fires on 2 of the 22 visits, both the *second* visit to a stage in
Astronomy_000 adaptive -- the one run in the trial that took a real backward edge --
``06_analysis`` at 5 charged against a median of 2, and ``07_writing`` at 5 against 2.
``2.5x`` and ``3x`` fire on nothing. ``1.5x`` with two closed stages fires on five, and
the replay's ``binds`` column says what the extra ones cost: Astronomy_000 linear
``03_study_design`` would have been rationed to 6 in a visit that charged 7, so that
firing shortens a visit and the two at ``2x`` shorten nothing. At ``2x`` itself, two
closed stages and three fire identically, so the population does not distinguish them and
the case for three is the structural one -- a median over a run's first two stages is a
median over its two cheapest. Both ``2x`` firings survive the replay's
``after_stop_spending`` column, which re-runs the sweep with the visits
:data:`STOP_SPENDING` has already cut removed -- a proportionality rule that counts those
is taking credit for another rule's work. At the shipped ``N`` that column removes nothing
anywhere, which is another way of saying the stop rule is inert on this population.

Neither firing costs the run anything, and that is measured rather than argued: the ration
:func:`ration` leaves is 5 for ``06_analysis`` and 3 for ``07_writing``, those visits
charged 3 and 1, and no later visit to either stage charged more, so the replay prints
``the narrowed per-visit allowance binds nothing`` for both. What moves is 3 and 5 units
to ``08_dissemination``, the only stage that run had not entered. A stage that has already
charged more than its allowance less the median has no unspent units at all and gets a
``continue``: budget that is spent cannot be reallocated, which is arithmetic rather than
policy, and it is why the rule is checked for a surplus before it is recorded.

:data:`UNSETTLED_VISITS_BEFORE_A_REDIRECT` **= 2**, and it is reached at none of the 22
stage exits. This is the replay's ``redirect`` column, which did not exist until the
threshold was questioned -- two sentences here credited the instrument with a finding it
had no column for, which is the same defect as a number nobody ran. It now imports
:func:`unsettled_visits` and evaluates it where the manager does, over the ledger rows
closed including the visit just ended: at one unsettled visit 10 of the 22 exits reach the
threshold, at two none do, at three none do. The only stage pair visited twice --
``06_analysis`` and ``07_writing`` in Astronomy_000 adaptive -- had an approved first visit
each. The count is an upper bound, because the replay cannot reconstruct which forward
edges the guards left open at each exit and requiring one can only remove firings; zero is
therefore zero for the whole rule. Two is the first count at which "this stage failed the
same way twice" can be said at all, and the number worth reporting is that the trial's
single backward edge would have been left alone.

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

The pool cost the measured runs nothing, which is also measured, and it is a *per-visit*
pool: see :class:`AttemptAllowance` for why an earlier lifetime-per-stage version of it
was a budget cut nobody asked for. Reconstructed charged attempts came to 22, 21 and 31
per run against 64 for one round of a benchmark run's eight stages at ``--max-attempts
8``. The per-visit half binds only where a transfer has already narrowed a stage, and the
two transfers the trial would have seen narrow ``06_analysis`` to 5 and ``07_writing`` to
3 in a run whose later visits to them charged 3 and 1. An envelope nothing pressed against
is an envelope that cost nothing; it is here because :data:`REALLOCATE` has to have a
total to conserve, and a total invented at the moment of the first transfer would be one
the run never agreed to.
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
#: a person instead. Measured cost: none. All three runs of ``MEASURED_RUNS`` ran
#: ``approval_mode: agent`` -- as does the fourth, still-walking one -- so no human refusal
#: appears anywhere in the population the thresholds were measured over, and excluding the
#: kind moves no firing in the replay.
NOT_COUNTED_AS_A_REPEAT: tuple[str, ...] = (HUMAN_REFUSED,)

#: Attempts that must still be at stake for :data:`STOP_SPENDING` to be worth taking.
#:
#: The intervention exists to stop money leaving. When the run's own ceiling is one attempt
#: from ending the visit, stopping it now renames an event the exhaustion path is about to
#: record at the next boundary anyway, and the run already has a name for that event.
#:
#: Measured cost on the trial: none, and the replay prints the sweep with and without the
#: condition to show it. ``MEASURED_RUNS`` walked under ``--max-attempts 8``, and at every
#: candidate ``N`` from 2 to 5 the two columns are identical -- at the shipped 3 the single
#: firing lands at attempt 3 with five still at stake. What the condition changes is a run
#: whose ceiling is tight: at ``--max-attempts 3`` the third identical failure arrives with
#: nothing left, and there the supervisor would be relabelling the exhaustion rather than
#: preventing it.
MIN_ATTEMPTS_AT_STAKE = 2

#: Identical failure digests in a row before :data:`STOP_SPENDING`.
#:
#: Measured, and the measurement says the safe value. Over the 22 stage visits of
#: ``MEASURED_RUNS`` (141 attempt-loop iterations; see the module docstring for the
#: invocation) two in a row happened three times, three once and four never. At **2** the
#: rule cuts 17 iterations of which only 12 produced nothing, and all three cuts land at a
#: moment when the draft is outside the gate, so the two visits that ended auto-skipped
#: with a rescued 49,347-byte and 23,513-byte stage summary would instead have published
#: the 1,911-byte skip stub. At **3** it fires on one visit and cuts 0 iterations; at 4 and
#: 5 it fires on nothing. Three is shipped: the smallest value whose measured cost on both
#: columns is zero. That it is also near-inert here is a fact about the population -- all
#: four repeat events in these runs are ``validators_refused``, which
#: :func:`~src.utils.is_stuck` already ends at the same count -- and this rule reads the
#: whole failure census rather than only ``last_validation_errors``, so what it adds is a
#: reviewer or a cross-model reviewer or a backend repeating, which these three runs never
#: do. ``tools/supervisor_threshold_replay.py`` prints both columns.
STOP_AFTER_IDENTICAL_FAILURES = 3

#: How many times the run's own median a stage may consume before :data:`REALLOCATE`.
#:
#: Measured against the same 22 visits: at ``2x`` the rule fires twice, both on a second
#: visit in the one run that took a backward edge, and the replay's ``binds`` column says
#: neither narrowed allowance would have shortened any visit. ``2.5x`` and ``3x`` fire on
#: nothing. ``1.5x`` adds a firing that rations a visit to 6 which went on to charge 7.
DISPROPORTIONATE_MULTIPLE = 2

#: Closed stages needed before there is a distribution to be disproportionate against.
#:
#: Three. At the shipped ``2x`` the measured population does not distinguish two from
#: three -- both fire on the same 2 of 22 visits -- and the docstring says so rather than
#: claiming a difference. Where the population does speak is at ``1.5x``: two closed stages
#: gives 5 firings against three's 3, and one of the two extra is Astronomy_000 linear
#: ``03_study_design``, rationed to 6 in a visit that went on to charge 7, which the
#: replay's ``binds`` column marks. The structural half is the reason three is the minimum
#: anyway: a median over a run's first two stages is a median over its two cheapest. Below
#: this the supervisor does nothing rather than guessing what a typical stage costs.
MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION = 3

#: Visits that ended without an approval before a stage stops being funded for another
#: one. Two rather than a measured larger number because two is the first count at which
#: "this stage failed the same way twice" can be said at all, and the replay's ``redirect``
#: column -- which imports :func:`unsettled_visits` and evaluates it at each stage exit
#: over the rows closed so far -- reaches it at none of the 22: 10 exits reach one
#: unsettled visit, none reach two, none reach three. The only stage pair visited twice
#: (``06_analysis`` and ``07_writing`` in Astronomy_000 adaptive) had an approved first
#: visit. That is an upper bound, since the replay cannot see which forward edges the
#: guards left open and requiring one only removes firings.
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
    """A pool of **per-visit** attempt allowances, denominated in ``--max-attempts``.

    One unit is one attempt of one *visit*, not one attempt of a stage's whole lifetime.
    That is what the run itself buys: ``_run_stage_attempts`` counts from zero on every
    entry to a stage, so without a supervisor a stage entered three times gets
    ``--max-attempts`` three times. :meth:`visit_ceiling` hands back
    ``min(--max-attempts, what this stage holds)`` -- a :func:`min` against the status
    quo, so no state of this ledger can hand a visit a larger ceiling than the run
    already allows, and a stage nothing has moved budget away from gets exactly what it
    would have got with no supervisor at all.

    **This is not a run total, and it must not be turned into one.** An earlier shape of
    this class charged a stage's closed visits against a single lifetime allowance, which
    read as a tighter run budget and was in fact a rule that funded the first visit and
    starved every one after it: a stage whose first visit charged the ceiling got
    ``remaining = 0``, ``attempt_ceiling`` returned 0, and the revisit died before buying
    an attempt with the ledger recording ``continue / nothing_to_decide``. The capability
    that narrows to zero is the backward edge, which is the one thing this project has
    that a plain agent loop does not. The invariant is "never above what the run would
    have had", and what the run would have had is ``--max-attempts`` *per visit*.

    What :attr:`total` conserves is therefore the run's per-visit envelope --
    ``stages x --max-attempts``, the budget for one round of visits -- and
    :meth:`transfer` is the only method that moves anything inside it. Narrowing one
    stage's per-visit allowance is a real narrowing that persists across its later visits;
    widening another's is capped by the ``min`` and can only ever restore a stage that had
    been narrowed. Both directions lower or leave the run where it was; neither raises it.
    """

    def __init__(self, stage_slugs: Sequence[str], per_stage: int) -> None:
        self.per_stage = per_stage
        self.allowance: dict[str, int] = {slug: per_stage for slug in stage_slugs}
        #: Fixed at construction and read-only afterwards. There is no method that raises
        #: it, which is the point.
        self.total = sum(self.allowance.values())

    def conserved(self) -> bool:
        return sum(self.allowance.values()) == self.total

    def visit_ceiling(self, stage_slug: str) -> int:
        """What one visit to *stage_slug* may charge: the run's own ceiling, or less.

        The ``min`` is the invariant. Whatever the allowance ledger has been moved to, the
        number handed back is bounded above by the ceiling the run was started with, so
        the supervisor can only ever lower it.

        Note what is *not* subtracted here: anything a previous visit charged. The attempt
        loop counts from zero on every entry, so this is the number that loop compares
        against, and subtracting a closed visit's spend from it would charge the same
        attempts twice -- once to the visit that spent them and once to every visit after.
        """
        return min(self.per_stage, self.allowance.get(stage_slug, self.per_stage))

    def transfer(self, donor: str, recipients: Sequence[str], units: int) -> int:
        """Move *units* from *donor*, split as evenly as the units allow.

        Returns how many units actually moved, which is zero when there is nothing to move
        or nobody to move it to. The total is asserted on the way out rather than trusted:
        this is the one method in the module that can change a budget, and a conservation
        law nobody checks is a comment.

        A donor may not give away everything it holds, and that bound is here rather than
        in the rule that calls it. A stage at zero per-visit allowance is a stage that
        fails on entry with "Exceeded 0 attempts" before it has run once -- which is the
        regression this class was reshaped to remove, arrived at from the other side.
        Making a stage impossible to enter is the mirror of opening a guarded edge, and
        neither is on offer. The *policy* floor is higher and lives in
        :meth:`RunSupervisor._rule_on_attempt`, which leaves the donor
        :func:`ration`'s "this visit's spend plus the run's own median"; this is the
        structural floor under it, checkable without knowing the median.
        """
        if units <= 0 or not recipients:
            return 0
        held = self.allowance.get(donor)
        if held is None or units >= held:
            raise AllowanceError(
                f"{donor} holds {held} allowance unit(s) and cannot give away {units}: a "
                "donor must keep enough to fund one more visit"
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

    def attempt_ceiling(self, stage_slug: str, per_stage: int | None) -> int | None:
        """This visit's ceiling: *per_stage*, or what this stage holds, whichever is less.

        The value handed to ``attempts_exhausted`` in place of ``--max-attempts``. It is a
        :func:`min` against the ceiling the caller passed in, so it can differ from it only
        downwards, and only on a stage :data:`REALLOCATE` has already moved budget away
        from. Every visit is funded, including the second and third: a backward edge is
        the capability this component exists beside, not one for it to price out.

        It takes no ``RunPaths``, and that absence is the fix rather than a tidy-up. The
        version that read the closed cost ledger here subtracted a stage's finished visits
        from its per-visit ceiling, so a stage whose first visit charged ``--max-attempts``
        was handed 0 on its second and died before buying an attempt. A ceiling that
        cannot see what previous visits spent cannot make that mistake again.
        """
        pool = self._pool(per_stage)
        if pool is None:
            return per_stage
        return pool.visit_ceiling(stage_slug)

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
        ceiling = self.attempt_ceiling(stage_slug, per_stage_ceiling)
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
        # Two different spends, on purpose, because the rule asks two different questions.
        #
        # The *trigger* below is `stage_spend`: what this stage has charged over all its
        # visits, against the median of the stages that have closed. Lifetime against
        # lifetime is what "disproportionate on the run's own terms" means, and it is the
        # comparison the replay swept.
        #
        # The *amount* is `keep`, and it is computed from `live_charged` -- this visit --
        # because the pool is denominated in per-visit allowances and a per-visit
        # allowance can only be compared with a per-visit spend. Using the lifetime figure
        # here would make `surplus` zero on every second visit, which is to say the rule
        # would stand down on exactly the revisits it was written to notice. On a first
        # visit the two numbers are equal, which is why nothing in the replay's sweep of
        # the trial's first visits moves.
        keep = ration(live_charged, others) if others else 0
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
                    f"closed, which is more than {DISPROPORTIONATE_MULTIPLE}x; this visit keeps "
                    f"the {live_charged} it has charged plus the run's own median, so {keep} "
                    f"per visit, and the surplus goes to the stages that have not run"
                ),
                evidence={
                    "stage_charged_attempts": stage_spend,
                    # Both spends, because the trigger reads one and the amount reads the
                    # other, and a reader recomputing the decision from this row needs
                    # whichever of the two the number in front of them came from.
                    "visit_charged_attempts": live_charged,
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
                    #: What this stage's later visits are now funded at. The narrowing is
                    #: the point of the intervention, so it is recorded rather than left
                    #: to be inferred from `units_moved`.
                    "visit_ceiling_after": pool.visit_ceiling(stage_slug),
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
