"""What a stage visit spent, and what it spent it on.

A run's binding budget is spent inside :meth:`ResearchManager._run_stage`, and until this
module existed the run recorded neither half of the transaction. Two measured holes, both
from the first live paired trial (``/rmeng_data/robtang/rcb-trial-graph``).

The population, pinned
----------------------
The trial directory held four runs when this was written and a fifth number would be
wrong tomorrow, so every count below is over the **three whose ``run_manifest.json``
says they finished** — ``Astronomy_000_20260814_175426`` (``cancelled``),
``Astronomy_000_20260815_074118`` (``completed``) and
``Chemistry_000_20260816_011751`` (``cancelled``). ``Chemistry_000_20260816_173127`` was
still ``running`` and is left out of all of them: a log that is still being appended to
is not a denominator. Nothing here needs the fourth run, and quoting it would put a
number in a docstring that a reader re-deriving it next week would not get back.

**The cause was not recorded.** Across those three runs the attempt loop hit its ceiling
ten times — nine ``max_attempts_exceeded`` log entries and one ``stage_stuck`` — and five
of the ten wrote ``Last validation errors: None recorded.`` Counted as *log entries*
(``grep -ac '^=== .* max_attempts_exceeded ===$'`` gave 4, 1, 4 and the ``stage_stuck``
heading 1, 0, 0). The ``-a`` is not decoration: the 08-14 log holds seven NUL bytes, GNU
grep therefore treats the whole file as binary, and plain ``grep -c`` prints nothing and
exits 1 on exactly the run that contributes the most. The sentence itself occurs more
often than the entries do, because the message is stored as the stage's ``last_error`` in
``run_manifest.json`` and comes back into the log every time a later stage reads that
file: counting raw occurrences of ``Exceeded 8 attempts in the current stage run`` gives
eighteen, eleven of them carrying ``None recorded.`` Either denominator says the same
thing — half or more of the exhaustions named no cause — and the entry count is the one
that means "times a stage ran out of attempts". The reason is structural rather than
incidental: ``last_validation_errors`` is assigned at exactly one place in
``src/manager.py``, the branch where a draft failed validation, was repaired, failed
again, was normalised locally and failed a third time. Every *other* way an attempt is
consumed — an automated reviewer asking for changes, a cross-model reviewer vetoing an
approval, a backend that crashed or answered unreadably, a crux the agent stopped to
ask — leaves that list empty, so the exhaustion message says nothing. In all five of the
silent exhaustions the decision immediately before was a reviewer refusal or a
cross-model veto; in none of them was it a validation failure. A reviewer refusing eight
times, a validator refusing eight times and a backend not answering eight times were
indistinguishable after the fact.

**The spend was not recorded.** A stage that burned eight attempts, consumed an auto-skip
and pushed the run toward cancellation left no row anywhere saying so. The run manifest
records the last state of each stage, not what reaching it cost, and a stage visited
twice overwrites its own history.

What this module adds is a row per *stage visit* — not per stage, because a backward edge
re-runs one and the second visit is a separate purchase. :class:`StageCostMeter` is opened
when the manager enters a stage and closed on every way out; :func:`append_stage_cost_row`
puts the closed row in :func:`stage_cost_ledger_path`.

Where the ledger lives, and why
-------------------------------
``run_root/stage_cost_ledger.json``, outside ``workspace/``. The precedent is
``report_plan_stamp.json`` and the validity-review stamp, and the reason carries over
without weakening: the operator runs with ``bypassPermissions`` at ``cwd=run_root`` and
every stage prompt directs it at ``workspace/``, so a run's account of what it spent must
not sit where the party whose spending it records is being sent to write. Nothing here is
a gate — the ledger refuses nothing — but it is the input a later supervisor decides on,
and a receipt the payer prints is worth what it cost to print.

Naming the cause
----------------
The three cases the manager has to be able to tell apart afterwards are the reviewer
refusing, the validators refusing, and the backend not answering. ``src/approval_agent.py``
already ships the vocabulary for the third — :data:`~src.approval_agent.CRASHED_REASON`,
:data:`~src.approval_agent.UNREADABLE_REASON`, :data:`~src.approval_agent.UNSUPPORTED_REASON`
and ``AutomatedReviewer.is_degraded_verdict`` — so :func:`classify_refusal` reads those
constants rather than spelling a fourth vocabulary. Renaming one of them breaks this
import instead of silently reclassifying every degraded verdict as an ordinary refusal.

Whether it repeated
-------------------
Eight attempts against one error is a stage that was never going to succeed; eight
attempts against eight different errors is a stage making progress it ran out of budget
to finish. The two need different responses and looked identical in the record, so every
attempt's reason is reduced to a stable digest (:func:`failure_digest`) and the row
carries the repeat structure: :attr:`StageCostRow.distinct_failures`,
:attr:`StageCostRow.max_repeat`, :attr:`StageCostRow.max_consecutive_repeat` and
:attr:`StageCostRow.repeated_failure`, over the ordered
:attr:`StageCostRow.attempt_digests`. Ordered, because "the same failure again" and "the
same failure *again and again*" are different claims and only the second can be settled
from a sequence. No threshold is applied to any of them here: how many repeats is too
many is a decision, this module is the record it will be taken from.

What the visit cost, and where the number comes from
----------------------------------------------------
The row used to carry no token count and no dollar figure, with a note saying exactly what
would have to change: *"Do not derive one from ``logs_raw.jsonl`` inside the supervisor;
wire it through ``OperatorResult`` and ``ReviewDecision`` first."* That is done, and
:attr:`StageCostRow.call_cost` is the result. The path is
``ClaudeOperator._run_streaming_command`` → ``stream_meta`` →
:attr:`~src.utils.OperatorResult.call_cost` and
:attr:`~src.approval_agent.ReviewDecision.call_cost` →
:meth:`StageCostMeter.note_call_cost` → the row. Nothing reads the raw log a second time,
which matters because there are two traps in that data and :mod:`src.call_cost` documents
both: ``total_cost_usd`` is a per-call charge whose values sum, and ``input_tokens`` is the
uncached remainder of a four-way split. A second reader is a second chance to get either
one wrong, and both are wrong in a direction that looks plausible.

**Which calls it covers.** The ones this row already counts and no others:
:attr:`StageCostRow.operator_invocations`, :attr:`StageCostRow.review_invocations` and the
adversarial validity pass, all dispatched by the manager inside the visit. Three other
places in ``src/`` reach the backend — the router's two, and the benchmark front end's —
and none of them is inside a stage visit, so none of them can be charged to one.
``tests/test_cost_is_recorded_and_unread.py`` derives that population from the syntax and
fails when a new dispatch site joins the tree unclassified, and
:func:`format_run_cost_report` prints the boundary beside the total rather than leaving a
reader to assume it is the whole bill.

**Absent is not zero.** A backend that reports nothing leaves every field ``None``, and the
formatter prints ``not measured`` rather than ``$0.00``. The fake operator is the case that
makes this concrete: it makes no call at all, and a run smoke-tested with it must not
publish a measured zero. See :mod:`src.call_cost`.

**And nothing decides on it.** The fields may appear in this record, in
:func:`summarize_stage_cost` and in :func:`format_run_cost_report`, and in no condition
anywhere under ``src/`` — no comparison, no boolean operator, no ``if``, no comprehension
filter, no ``sorted`` key, no ``max``. That is asserted over the syntax, in the shape
``tests/test_router_budget.py`` uses for ``StageRouter.choose``, and the run supervisor is
asserted twice over: once by the same walk and once by replaying its rulings against two
ledgers that differ only in what they cost.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .approval_agent import CRASHED_REASON, UNREADABLE_REASON, UNSUPPORTED_REASON
from .call_cost import (
    RECORD_FIELD,
    CallCost,
    call_cost_of,
    describe_coverage,
    format_call_cost,
)
from .utils import RunPaths, StageSpec


#: Bumped when a row grows or loses a field, so a reader that predates the change can say
#: so instead of reading a missing key as a zero.
#:
#: 2 since the row carries :data:`~src.call_cost.RECORD_FIELD`. The bump is what stops a
#: reader of a version-1 ledger concluding that its visits were free: the key is absent
#: there, and absent is not zero.
STAGE_COST_LEDGER_VERSION = 2

# ---------------------------------------------------------------------------
# Why an attempt did not settle the stage
# ---------------------------------------------------------------------------

#: An automated reviewer read the draft and asked for changes. The stage is being told
#: what to fix, which is the loop working as designed until the budget runs out.
REVIEWER_REFUSED = "reviewer_refused"

#: A reviewer from a different model family overturned an approval the primary gave.
#: Separate from :data:`REVIEWER_REFUSED` because it is a *disagreement between two
#: reviewers*, not a stage falling short, and two of the five silent exhaustions measured
#: on the trial were exactly this: ``choice: 5`` from the primary, then ``cross_review``
#: coming back ``agrees: False``.
CROSS_REVIEW_VETOED = "cross_review_vetoed"

#: A human at the approval gate asked for changes. Distinct from the automated reviewer
#: so an attended run's spend is not filed under a reviewer that was not running.
HUMAN_REFUSED = "human_refused"

#: The stage markdown or artifact validators refused, after repair and local
#: normalisation both failed. This is the only cause the run recorded before this module.
VALIDATORS_REFUSED = "validators_refused"

#: The reviewer backend failed to run at all.
BACKEND_CRASHED = "backend_crashed"

#: The reviewer answered and the answer could not be parsed as a verdict.
BACKEND_UNREADABLE = "backend_unreadable"

#: The reviewer returned a decision token outside the accepted vocabulary.
BACKEND_UNSUPPORTED = "backend_unsupported"

#: The agent stopped and asked a question, and settling it cost an attempt. Not a
#: failure of the draft; recorded so the census sums to the attempts.
CRUX_RAISED = "crux_raised"

#: An improvement round on work that already passed validation. Charged to the polish
#: budget rather than the attempt budget, and in the census so a visit that spent its
#: wall clock getting better is not read as one that spent it thrashing.
POLISH_ROUND = "polish_round"

#: A refusal that reached here with no recognisable cause. Present so an unclassified
#: attempt is counted rather than dropped: a census that silently omits what it cannot
#: name is the defect this module exists to remove, one level up.
UNCLASSIFIED_REFUSAL = "unclassified_refusal"

#: Every kind an attempt can be filed under. A supervisor iterating this is guaranteed to
#: see every column the census can produce.
FAILURE_KINDS: tuple[str, ...] = (
    REVIEWER_REFUSED,
    CROSS_REVIEW_VETOED,
    HUMAN_REFUSED,
    VALIDATORS_REFUSED,
    BACKEND_CRASHED,
    BACKEND_UNREADABLE,
    BACKEND_UNSUPPORTED,
    CRUX_RAISED,
    POLISH_ROUND,
    UNCLASSIFIED_REFUSAL,
)

#: The three that mean "the backend never answered, or answered unreadably" — the third
#: of the cases the manager has to tell apart, and the one whose remedy is not another
#: attempt at the research. Mirrors ``AutomatedReviewer.is_degraded_verdict``.
DEGRADED_FAILURE_KINDS: tuple[str, ...] = (
    BACKEND_CRASHED,
    BACKEND_UNREADABLE,
    BACKEND_UNSUPPORTED,
)


# ---------------------------------------------------------------------------
# How the visit ended
# ---------------------------------------------------------------------------

OUTCOME_APPROVED = "approved"
OUTCOME_AUTO_SKIPPED = "auto_skipped"
OUTCOME_HUMAN_SKIPPED = "human_skipped"
OUTCOME_ROUTED_TO_DELIVERABLE = "routed_to_deliverable"
OUTCOME_ROLLED_BACK = "rolled_back"
OUTCOME_ABORTED = "aborted"

#: The stage was never entered: a route to the deliverable stepped over it and put it in
#: the run's not-completed list. It gets a row so the ledger's stage set matches the
#: run's own account of itself rather than being flatter than it.
OUTCOME_BYPASSED = "bypassed"

#: The visit ended by raising. The row is still written, because a visit that crashed is
#: precisely the one whose spend nobody can reconstruct from the stage file.
OUTCOME_RAISED = "raised"

#: Closed without anyone saying how. Kept rather than defaulted to ``approved`` so a new
#: exit path shows up as an unnamed one instead of as a success.
OUTCOME_UNKNOWN = "unknown"

OUTCOMES: tuple[str, ...] = (
    OUTCOME_APPROVED,
    OUTCOME_AUTO_SKIPPED,
    OUTCOME_HUMAN_SKIPPED,
    OUTCOME_ROUTED_TO_DELIVERABLE,
    OUTCOME_ROLLED_BACK,
    OUTCOME_ABORTED,
    OUTCOME_BYPASSED,
    OUTCOME_RAISED,
    OUTCOME_UNKNOWN,
)


def classify_refusal(reason: str, *, cross_review: bool = False, automated: bool = True) -> str:
    """Which kind of refusal a review verdict's ``reason`` is.

    The degraded cases are matched on the reason prefix rather than on the decision
    token, for the reason ``AutomatedReviewer._is_unreadable`` gives: an unsupported token
    keeps whatever word the model wrote, so a token check misses it. The prefixes are
    imported from :mod:`src.approval_agent` rather than re-spelled, so the two readers
    cannot drift.

    ``cross_review`` is checked after the degraded prefixes on purpose. A veto carries the
    cross-reviewer's own prose, which cannot begin with one of AutoR's stand-in reasons,
    but ordering it this way means a future stand-in on that path is still filed as
    degraded rather than as a judgement nobody made.
    """
    text = reason or ""
    if text.startswith(CRASHED_REASON):
        return BACKEND_CRASHED
    if text.startswith(UNREADABLE_REASON):
        return BACKEND_UNREADABLE
    if text.startswith(UNSUPPORTED_REASON):
        return BACKEND_UNSUPPORTED
    if cross_review:
        return CROSS_REVIEW_VETOED
    if not automated:
        return HUMAN_REFUSED
    return REVIEWER_REFUSED


def failure_digest(kind: str, reason: str) -> str:
    """A stable short id for "this same failure again".

    Whitespace-collapsed and lowercased, then hashed with the kind, so a reviewer that
    re-wraps its paragraph is still the same refusal and a validator error that happens to
    read like a reviewer's sentence is not. Twelve hex characters: the population being
    distinguished is one stage visit's attempts, never more than a few dozen.

    The kind is part of the input rather than a separate column so an attempt with no
    reason text at all — a crashed backend can produce one — still has a digest, and two
    such attempts still count as a repeat.
    """
    normalized = " ".join((reason or "").split()).lower()
    return hashlib.sha256(f"{kind}|{normalized}".encode("utf-8")).hexdigest()[:12]


#: How much of a failure reason is kept beside its digest. Long enough to recognise the
#: refusal without reading the log, short enough that eight of them do not turn the ledger
#: into a transcript.
FAILURE_EXAMPLE_CHARS = 400


@dataclass(frozen=True)
class AttemptCost:
    """One attempt that did not settle the stage."""

    attempt_no: int
    kind: str
    reason: str

    @property
    def digest(self) -> str:
        return failure_digest(self.kind, self.reason)


@dataclass(frozen=True)
class StageCostRow:
    """One stage visit's account of itself.

    Every field is written by the harness. Nothing on it is copied from a file the agent
    can edit, and nothing on it is inferred from a number the backend did not report.
    """

    stage: str
    stage_number: int
    #: 1 for the first time this run entered this stage, 2 for the visit a backward edge
    #: produced, and so on. Assigned by :func:`append_stage_cost_row` from what is already
    #: in the ledger, so it survives a resume — :meth:`StageCostMeter.close` cannot know
    #: it and does not try, and there is deliberately no second way to set it.
    visit: int
    started_at: str
    wall_seconds: float
    #: Iterations of the attempt loop in this visit — every trip through it, whatever the
    #: trip was for. Not the run-wide attempt number the manifest carries: a second visit
    #: starts this at zero.
    #:
    #: **This is not the ``--max-attempts`` spend.** That ceiling is tested against
    #: ``loop_attempts - (polish_rounds - entry_polish_rounds) + 1`` in
    #: ``ResearchManager._run_stage_attempts``, so an improvement round is a loop iteration
    #: that costs the budget nothing, and the spend this visit made against the ceiling is
    #: :attr:`attempts` **minus** :attr:`polish_rounds`. Both numbers are on the row rather
    #: than one derived number, because "how long did this visit go on for" and "how much
    #: of the failure budget did it burn" are different questions and a visit that spent
    #: its wall clock getting better answers them differently.
    attempts: int
    #: Improvement rounds taken in this visit, each of them one of :attr:`attempts`.
    polish_rounds: int
    #: Backend launches the manager dispatched to do the stage's work — the stage run
    #: itself and the summary-repair passes.
    operator_invocations: int
    #: Backend launches the manager dispatched to judge the work — the approval gate and
    #: the cross-model audit.
    review_invocations: int
    auto_skipped: bool
    outcome: str
    exhausted: bool
    #: How many of :attr:`attempts` produced a census entry. The denominator is
    #: :attr:`attempts` alone and not ``attempts + polish_rounds``: a polish round *is* a
    #: loop iteration, so adding the two would count it twice and make every polished
    #: visit look like it had lost an attempt.
    #:
    #: A gap is a path that consumed a loop iteration and recorded nothing — the shape
    #: this module was written to remove, kept visible so a new one announces itself. One
    #: gap is expected and is not that shape: the iteration that *settled* the stage did
    #: not fail, so an approved visit reads ``attempts_with_a_recorded_cause ==
    #: attempts - 1``. A visit that exhausted its budget has no such iteration and should
    #: read equal.
    attempts_with_a_recorded_cause: int
    failure_census: dict[str, int]
    distinct_failures: int
    #: How many times the most repeated single failure occurred, anywhere in the visit.
    max_repeat: int
    #: The longest unbroken run of one digest. Separate from :attr:`max_repeat` because
    #: the two answer different questions and only this one distinguishes "the same
    #: objection eight times running" from "two objections alternating": the first is a
    #: stage that was never going to succeed, the second is one still being told
    #: different things. A reader that needs the other rule can rebuild it from
    #: :attr:`attempt_digests`; both are recorded so neither has to be guessed at.
    max_consecutive_repeat: int
    #: Whether any single failure occurred more than once.
    repeated_failure: bool
    dominant_failure: str | None
    failures: list[dict[str, Any]]
    #: One entry per recorded cause, in the order the attempts happened:
    #: ``{"attempt": int, "kind": str, "digest": str}``. The grouped :attr:`failures`
    #: loses the ordering, and a rule about a failure repeating *consecutively* cannot be
    #: evaluated without it. No reason text here — that lives once, in :attr:`failures`.
    attempt_digests: list[dict[str, Any]]
    note: str = ""
    #: What the backend charged for this visit, summed over the operator and review calls
    #: the manager dispatched inside it. Absent, not zero, on a backend that reports
    #: nothing: see :mod:`src.call_cost`, and :func:`bypassed_row` for the stage nobody
    #: called at all.
    #:
    #: Recorded and inert. It is on the row, in :func:`summarize_stage_cost`, and in
    #: :func:`format_run_cost_report`, and in no condition anywhere under ``src/`` --
    #: ``tests/test_cost_is_recorded_and_unread.py`` walks the syntax and fails if it
    #: reaches one, the run supervisor included.
    call_cost: CallCost = field(default_factory=CallCost)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "stage_number": self.stage_number,
            "visit": self.visit,
            "started_at": self.started_at,
            "wall_seconds": self.wall_seconds,
            "attempts": self.attempts,
            "polish_rounds": self.polish_rounds,
            "operator_invocations": self.operator_invocations,
            "review_invocations": self.review_invocations,
            "auto_skipped": self.auto_skipped,
            "outcome": self.outcome,
            "exhausted": self.exhausted,
            "attempts_with_a_recorded_cause": self.attempts_with_a_recorded_cause,
            "failure_census": dict(self.failure_census),
            "distinct_failures": self.distinct_failures,
            "max_repeat": self.max_repeat,
            "max_consecutive_repeat": self.max_consecutive_repeat,
            "repeated_failure": self.repeated_failure,
            "dominant_failure": self.dominant_failure,
            "failures": [dict(item) for item in self.failures],
            "attempt_digests": [dict(item) for item in self.attempt_digests],
            "note": self.note,
            RECORD_FIELD: self.call_cost.to_dict(),
        }


class StageCostMeter:
    """Open on stage entry, closed on every way out.

    Deliberately dumb about the manager: it is told what happened rather than inspecting
    anything, so the record cannot disagree with the branch that produced it. The manager
    holds at most one of these at a time — a stage visit is not re-entrant — and the meter
    carries the stage it was opened for so a note arriving from a nested call about a
    *different* stage is dropped rather than charged to the wrong row.
    """

    def __init__(
        self,
        stage: StageSpec,
        *,
        clock: Callable[[], float] = time.monotonic,
        started_at: str | None = None,
    ) -> None:
        self.stage = stage
        self._clock = clock
        self._start = clock()
        self.started_at = started_at or datetime.now().isoformat(timespec="seconds")
        self.attempts = 0
        self.polish_rounds = 0
        self.operator_invocations = 0
        self.review_invocations = 0
        self.auto_skipped = False
        self.exhausted = False
        self.outcome = OUTCOME_UNKNOWN
        self.note = ""
        self.costs: list[AttemptCost] = []
        #: What the backend has charged this visit so far. Starts unmeasured rather than
        #: at zero, so a visit whose every call reported nothing closes as unmeasured.
        self.call_cost = CallCost()

    # -- what the manager tells it -----------------------------------------
    def note_attempt(self) -> None:
        """One iteration of the attempt loop reached the backend."""
        self.attempts += 1

    def note_operator_call(self) -> None:
        self.operator_invocations += 1

    def note_review_call(self) -> None:
        self.review_invocations += 1

    def note_call_cost(self, cost: Any) -> None:
        """Add one backend call's own report of what it cost to this visit.

        Takes whatever the operator layer handed back rather than a
        :class:`~src.call_cost.CallCost`, and normalises through
        :func:`~src.call_cost.call_cost_of`. The manager charges the result of
        ``run_stage``, ``repair_stage_summary``, ``review_stage`` and the validity pass,
        and an operator that predates the field -- a third-party backend, a stub, a test
        double -- hands back an attribute that is not a report. The two things to do with
        it are to publish a number nobody measured or to record that nothing was measured,
        and this records that nothing was measured.

        Summed, because ``total_cost_usd`` is a per-call charge and not a running total.
        That is trap one in :mod:`src.call_cost`, and it is settled by the field not being
        monotone within a session id rather than by the field's name.
        """
        self.call_cost = self.call_cost + call_cost_of(cost)

    def note_polish_round(self, attempt_no: int) -> None:
        self.polish_rounds += 1
        self.costs.append(AttemptCost(attempt_no=attempt_no, kind=POLISH_ROUND, reason=""))

    def note_failure(self, attempt_no: int, kind: str, reason: str = "") -> None:
        """Record why this attempt did not settle the stage.

        An unknown kind is kept and filed as :data:`UNCLASSIFIED_REFUSAL` rather than
        rejected: losing the attempt would restore the hole, and a caller passing a kind
        this module does not know about is a wiring bug that should be visible in the
        census rather than fatal in the middle of a run.
        """
        if kind not in FAILURE_KINDS:
            reason = f"[{kind}] {reason}".strip()
            kind = UNCLASSIFIED_REFUSAL
        self.costs.append(AttemptCost(attempt_no=attempt_no, kind=kind, reason=reason))

    def note_outcome(self, outcome: str, *, note: str = "") -> None:
        if outcome not in OUTCOMES:
            outcome = OUTCOME_UNKNOWN
        self.outcome = outcome
        if note:
            self.note = note
        if outcome == OUTCOME_AUTO_SKIPPED:
            self.auto_skipped = True

    def note_exhausted(self) -> None:
        self.exhausted = True

    # -- what it can say ---------------------------------------------------
    def census(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for cost in self.costs:
            counts[cost.kind] = counts.get(cost.kind, 0) + 1
        return {kind: counts[kind] for kind in FAILURE_KINDS if kind in counts}

    def failure_groups(self) -> list[dict[str, Any]]:
        """One entry per distinct failure, most frequent first.

        Ties break on first appearance, so the list is stable for the same visit rather
        than dependent on dict ordering across interpreters.
        """
        groups: dict[str, dict[str, Any]] = {}
        for index, cost in enumerate(self.costs):
            if cost.kind == POLISH_ROUND:
                continue
            entry = groups.get(cost.digest)
            if entry is None:
                groups[cost.digest] = {
                    "digest": cost.digest,
                    "kind": cost.kind,
                    "count": 1,
                    "first_attempt": cost.attempt_no,
                    "last_attempt": cost.attempt_no,
                    "example": (cost.reason or "")[:FAILURE_EXAMPLE_CHARS],
                    "_order": index,
                }
                continue
            entry["count"] = int(entry["count"]) + 1
            entry["last_attempt"] = cost.attempt_no
        ordered = sorted(groups.values(), key=lambda item: (-int(item["count"]), int(item["_order"])))
        return [{key: value for key, value in item.items() if key != "_order"} for item in ordered]

    def attempt_digests(self) -> list[dict[str, Any]]:
        """Every recorded cause in the order it happened, as ``attempt/kind/digest``.

        Polish rounds are left out for the same reason :meth:`failure_groups` leaves them
        out: a round improving work that already passed is not a failure, and a reader
        counting repeats would otherwise see one interrupted by something that did not
        fail.
        """
        return [
            {"attempt": cost.attempt_no, "kind": cost.kind, "digest": cost.digest}
            for cost in self.costs
            if cost.kind != POLISH_ROUND
        ]

    def max_consecutive_repeat(self) -> int:
        """The longest unbroken run of one digest, over :meth:`attempt_digests`.

        0 for a visit that recorded nothing, 1 for a visit whose failures were all
        different. Computed here rather than by each reader so the "same failure again"
        rule has exactly one implementation, next to the digest it is defined over.
        """
        longest = 0
        run = 0
        previous: str | None = None
        for entry in self.attempt_digests():
            digest = str(entry["digest"])
            run = run + 1 if digest == previous else 1
            previous = digest
            longest = max(longest, run)
        return longest

    def describe_failures(self) -> str:
        """One sentence naming what the attempts were spent on.

        This is what goes into the exhaustion message. Written to be readable in a log
        line and to be false about nothing: a visit with no recorded cause says so
        explicitly rather than printing an empty list.
        """
        census = self.census()
        if not census:
            return "no attempt in this stage run recorded a cause"
        parts = [f"{kind} x{count}" for kind, count in census.items()]
        groups = self.failure_groups()
        if not groups:
            return "; ".join(parts)
        repeat = max(int(group["count"]) for group in groups)
        shape = (
            f"{len(groups)} distinct failure(s), the most repeated {repeat} time(s)"
            if repeat > 1
            else f"{len(groups)} distinct failure(s), none repeated"
        )
        return "; ".join(parts) + f" ({shape})"

    def close(self) -> StageCostRow:
        """The row for this visit, with :attr:`StageCostRow.visit` left at its placeholder.

        The meter cannot count visits: it is opened per visit and never sees the ledger.
        :func:`append_stage_cost_row` overwrites the field from what is already on disk, so
        a ``visit=`` argument here would be a second way to set a number the writer
        ignores — which is worse than no way at all, because a caller could pass one and
        watch it disappear.
        """
        census = self.census()
        groups = self.failure_groups()
        counts = [int(group["count"]) for group in groups]
        max_repeat = max(counts) if counts else 0
        refusals = {kind: count for kind, count in census.items() if kind != POLISH_ROUND}
        dominant = max(refusals, key=lambda kind: refusals[kind]) if refusals else None
        return StageCostRow(
            stage=self.stage.slug,
            stage_number=self.stage.number,
            visit=1,
            started_at=self.started_at,
            wall_seconds=round(max(self._clock() - self._start, 0.0), 3),
            attempts=self.attempts,
            polish_rounds=self.polish_rounds,
            operator_invocations=self.operator_invocations,
            review_invocations=self.review_invocations,
            auto_skipped=self.auto_skipped,
            outcome=self.outcome,
            exhausted=self.exhausted,
            attempts_with_a_recorded_cause=len(self.costs),
            failure_census=census,
            distinct_failures=len(groups),
            max_repeat=max_repeat,
            max_consecutive_repeat=self.max_consecutive_repeat(),
            repeated_failure=max_repeat > 1,
            dominant_failure=dominant,
            failures=groups,
            attempt_digests=self.attempt_digests(),
            note=self.note,
            call_cost=self.call_cost,
        )


def bypassed_row(stage: StageSpec, *, note: str) -> StageCostRow:
    """A row for a stage the run stepped over without entering.

    Zeroes everywhere a measurement would go, because nothing was spent — the point of
    the row is that the stage appears in the ledger at all. A ledger missing its bypassed
    stages is flatter than the run and would let a reader conclude the run visited only
    what it paid for.

    The one field that is *not* zeroed is :attr:`StageCostRow.call_cost`, which stays the
    unmeasured report. Nothing here is a measurement of zero: no backend was asked, so no
    backend answered, and writing ``$0.00`` in would be the derived number this module
    refuses. It makes no difference to any total — an absent measurement adds nothing —
    and it makes the difference to a reader, who can tell a stage that was free from a
    stage that was never called.
    """
    return StageCostRow(
        stage=stage.slug,
        stage_number=stage.number,
        visit=1,
        started_at=datetime.now().isoformat(timespec="seconds"),
        wall_seconds=0.0,
        attempts=0,
        polish_rounds=0,
        operator_invocations=0,
        review_invocations=0,
        auto_skipped=True,
        outcome=OUTCOME_BYPASSED,
        exhausted=False,
        attempts_with_a_recorded_cause=0,
        failure_census={},
        distinct_failures=0,
        max_repeat=0,
        max_consecutive_repeat=0,
        repeated_failure=False,
        dominant_failure=None,
        failures=[],
        attempt_digests=[],
        note=note,
    )


# ---------------------------------------------------------------------------
# The file
# ---------------------------------------------------------------------------


def stage_cost_ledger_path(paths: RunPaths) -> Path:
    """Where the ledger lives. Outside ``workspace/``; see this module's header."""
    return paths.stage_cost_ledger


def read_stage_cost_ledger(paths: RunPaths) -> list[dict[str, Any]]:
    """The rows written so far, oldest first. ``[]`` when there is nothing readable.

    Never raises. A reader of a spend record is usually running because something already
    went wrong, and a corrupt ledger must not be the thing that ends the run.
    """
    path = stage_cost_ledger_path(paths)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def append_stage_cost_row(paths: RunPaths, row: StageCostRow) -> bool:
    """Add one row. Returns whether it landed, and never raises.

    The visit number is assigned here rather than by the caller, from the rows already on
    disk, so it is right across a resume and right when two visits to one stage are
    separated by half a run.

    Bookkeeping may not fail the run: a stage that produced good work must not be lost
    because the account of it could not be written. Every failure mode — an unwritable
    run root, a disk that filled, a ledger someone truncated — returns ``False`` and
    leaves the caller to decide whether anyone should be told.
    """
    try:
        existing = read_stage_cost_ledger(paths)
        visit = sum(1 for item in existing if item.get("stage") == row.stage) + 1
        payload = {
            "version": STAGE_COST_LEDGER_VERSION,
            "rows": existing + [{**row.to_dict(), "visit": visit}],
        }
        path = stage_cost_ledger_path(paths)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        tmp.replace(path)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Reading it back
# ---------------------------------------------------------------------------


def summarize_stage_cost(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Run-level totals over a ledger's rows.

    Separate from the row so a supervisor gets the same arithmetic the run's own log
    reports, rather than two additions of one set of numbers.
    """
    census: dict[str, int] = {}
    for row in rows:
        row_census = row.get("failure_census")
        if not isinstance(row_census, Mapping):
            continue
        for kind, count in row_census.items():
            try:
                census[str(kind)] = census.get(str(kind), 0) + int(count)
            except (TypeError, ValueError):
                continue
    return {
        "visits": len(rows),
        "stages": len({row.get("stage") for row in rows}),
        # Attempts the run bought and did not get a judgement for. Separated because the
        # remedy is different in kind: more attempts at the research cannot fix a backend
        # that is not answering, and a run whose budget went here mostly did not fail at
        # the science.
        "degraded_attempts": sum(census.get(kind, 0) for kind in DEGRADED_FAILURE_KINDS),
        "wall_seconds": round(sum(_number(row.get("wall_seconds")) for row in rows), 3),
        "attempts": int(sum(_number(row.get("attempts")) for row in rows)),
        "polish_rounds": int(sum(_number(row.get("polish_rounds")) for row in rows)),
        "operator_invocations": int(sum(_number(row.get("operator_invocations")) for row in rows)),
        "review_invocations": int(sum(_number(row.get("review_invocations")) for row in rows)),
        "auto_skipped": sum(1 for row in rows if row.get("auto_skipped")),
        "exhausted": sum(1 for row in rows if row.get("exhausted")),
        "visits_with_a_repeated_failure": sum(1 for row in rows if row.get("repeated_failure")),
        # The worst run of one unchanging failure anywhere in the run. An observation, not
        # a threshold: a rule of the form "stop after N identical failures" has to be
        # measured against the distribution of this number, and it was not recorded before.
        "longest_run_of_one_failure": int(
            max((_number(row.get("max_consecutive_repeat")) for row in rows), default=0)
        ),
        "attempts_with_a_recorded_cause": int(
            sum(_number(row.get("attempts_with_a_recorded_cause")) for row in rows)
        ),
        "failure_census": census,
        # Summed rather than maximised or last-taken; see trap one in `src/call_cost.py`.
        # A row that recorded nothing contributes nothing and does not turn the total into
        # a measured zero.
        RECORD_FIELD: run_call_cost(rows).to_dict(),
    }


def run_call_cost(rows: Sequence[Mapping[str, Any]]) -> CallCost:
    """Every row's cost report, summed into one.

    Separate from :func:`summarize_stage_cost` so the run report and the ledger summary do
    one addition rather than two -- the same reason the summary itself is not done twice.
    """
    total = CallCost()
    for row in rows:
        total = total + CallCost.from_mapping(row.get(RECORD_FIELD))
    return total


def format_stage_cost_summary(rows: Sequence[Mapping[str, Any]]) -> str:
    """The ledger as a log entry: one line per visit, then the totals.

    Text rather than a table because it goes into ``logs.txt`` beside everything else a
    reader of a finished run has; the machine-readable copy is the ledger itself.
    """
    if not rows:
        return "No stage cost rows were recorded for this run."
    lines: list[str] = []
    for row in rows:
        census = row.get("failure_census")
        census_text = (
            ", ".join(f"{kind} x{count}" for kind, count in census.items())
            if isinstance(census, Mapping) and census
            else "no cause recorded"
        )
        lines.append(
            f"{row.get('stage', '?')} visit {row.get('visit', '?')}: "
            f"{_number(row.get('wall_seconds')):.0f}s, "
            f"{int(_number(row.get('attempts')))} attempt(s), "
            f"{int(_number(row.get('polish_rounds')))} polish, "
            f"{int(_number(row.get('operator_invocations')))} operator call(s), "
            f"{int(_number(row.get('review_invocations')))} review call(s), "
            f"outcome {row.get('outcome', OUTCOME_UNKNOWN)}"
            + (" [auto-skipped]" if row.get("auto_skipped") else "")
            + (" [repeated failure]" if row.get("repeated_failure") else "")
            + f" -- {census_text}"
        )
    totals = summarize_stage_cost(rows)
    lines.append("")
    lines.append(
        f"Run total: {totals['visits']} visit(s) over {totals['stages']} stage(s), "
        f"{totals['wall_seconds']:.0f}s, {totals['attempts']} attempt(s), "
        f"{totals['polish_rounds']} polish round(s), "
        f"{totals['operator_invocations']} operator call(s), "
        f"{totals['review_invocations']} review call(s), "
        f"{totals['auto_skipped']} auto-skipped, {totals['exhausted']} exhausted."
    )
    census = totals["failure_census"]
    lines.append(
        "Failure census: "
        + (", ".join(f"{kind} x{count}" for kind, count in census.items()) or "nothing recorded")
    )
    return "\n".join(lines)


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# What the run cost, for a human, once, at the end
# ---------------------------------------------------------------------------

#: The sentence that bounds the total. Printed every time the total is, because a bill that
#: does not say what it covers is read as covering everything, and this one does not: the
#: router's two backend calls happen at a stage *exit*, after
#: ``ResearchManager._run_stage`` has closed the meter, so there is no visit to charge them
#: to. ``tests/test_cost_is_recorded_and_unread.py`` derives the dispatch sites from the
#: syntax and fails when a new one appears in neither column.
COST_SCOPE_NOTE = (
    "Covers the operator, review and validity calls the manager dispatched inside a stage "
    "visit. The routing agent's calls happen at a stage exit, outside any visit, and are "
    "not in this total."
)

#: The line a run with nothing to report prints. Says which of the two it is: a run whose
#: ledger is empty and a run whose backend priced nothing look the same in a table of
#: dashes.
NO_COST_RECORDED = (
    "No backend reported a cost for this run. Nothing here is a measured zero."
)


def format_run_cost_report(rows: Sequence[Mapping[str, Any]]) -> str:
    """What the run cost: one line per stage visit, then the total. Terminal output.

    This is the one place the numbers are for a person, and the whole of what "report
    tokens and dollars at the end of the run" asks for. It is not written into
    ``workspace/report/``, not into the PDF, and not into ``logs.txt``: the deliverable does
    not change, and the machine-readable copy is the ledger itself.
    ``tests/test_cost_is_recorded_and_unread.py`` pins all three.

    Every line names the four token fields separately and the sum with its addends spelled
    out, because ``input_tokens`` alone is the uncached remainder and is five orders of
    magnitude below the truth on the measured runs -- see :mod:`src.call_cost`. There is
    deliberately no bare "tokens used" figure anywhere in this output.
    """
    if not rows:
        return NO_COST_RECORDED
    lines: list[str] = []
    for row in rows:
        cost = CallCost.from_mapping(row.get(RECORD_FIELD))
        lines.append(
            f"{row.get('stage', '?')} visit {row.get('visit', '?')}: {format_call_cost(cost)}"
        )
    total = run_call_cost(rows)
    lines.append("")
    lines.append(f"Run total: {format_call_cost(total)}")
    lines.append(describe_coverage(total))
    lines.append(COST_SCOPE_NOTE)
    return "\n".join(lines)
