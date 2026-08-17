"""What a backend call cost, carried from the operator layer to the ledger.

The backend already publishes this. Every Claude Code invocation ends with a
``{"type": "result"}`` event carrying ``total_cost_usd`` and a ``usage`` block, and
``ClaudeOperator._run_streaming_command`` writes every stream line to ``logs_raw.jsonl``.
What did not exist was a path from that event to the manager:
:class:`~src.utils.OperatorResult` carried ``success, exit_code, stdout, stderr,
stage_file_path, session_id`` and nothing about money, so ``src/stage_cost.py``'s row
deliberately had no dollar figure and its own note said what would have to change --
*"wire it through ``OperatorResult`` and ``ReviewDecision`` first"*. This module is that
path, and it is deliberately **not** a second reader of ``logs_raw.jsonl``: a number
scraped at read time makes every reader re-implement the two traps below, and the second
of them is invisible until somebody checks it.

Trap one: ``total_cost_usd`` is per call and the values sum
-----------------------------------------------------------
It is a per-invocation charge, not a running total, so a run's bill is the **sum** over
result events. That is not obvious from the field and it is not obvious from one event
either -- it is settled by the values not being monotone within a session id.
:func:`tools.log_cost_census.session_monotonicity` counts the descending steps and
``tools/log_cost_census.py`` prints them: over the three finished runs of the first live
paired trial (``tools.log_cost_census.MEASURED_RUNS``) there are 22, 23 and 27 places
where the next event of the same ``session_id`` charges *less* than the one before, so no
reading of the field as cumulative survives.

Getting it wrong is not a small error and it is not visibly wrong. The census prints both
readings side by side: summing per call gives $574.67, $744.99 and $643.42, and taking the
last value per session id -- the reading a cumulative field would deserve -- gives $212.68,
$254.87 and $191.09. Between 2.7 and 3.4 times too small, and every one of the six numbers
is a plausible bill for a multi-hour run.

Trap two: ``input_tokens`` is the uncached remainder only
----------------------------------------------------------
The ``usage`` block splits its input four ways, and ``input_tokens`` is only the part that
was neither written to nor read from the prompt cache. On the same three runs it is 5,117,
7,845 and 5,712 against cache reads of 644,146,902, 908,452,140 and 719,039,242 -- ratios
of 125,884x, 115,800x and 125,882x. A "tokens used" figure that reads ``input_tokens``
alone is wrong by five orders of magnitude and looks like a modest number rather than like
an error.

So there is no field on :class:`CallCost` called ``tokens``. The four are recorded
separately, they are named in :data:`TOKEN_FIELDS` once, and the only single figure this
module will produce is :func:`billed_tokens`, whose name says it is a sum and whose
formatter prints the four addends beside it.

Absent is not zero
------------------
A field the backend did not report is ``None``, never ``0``. The fake operator makes no
backend call at all and must not report ``$0.00`` as though a measurement had been taken;
the Gemini cross-reviewer answers through a different client that publishes no
``total_cost_usd``; a Codex stream carries no ``usage`` block in this shape. All three are
*unmeasured*, and a run whose reviewer is free is *measured at zero* -- the two look
identical the moment either is written down as a number. :attr:`CallCost.result_events` and
:attr:`CallCost.priced_events` are what tell them apart: a report with
``priced_events == 0`` has nothing to publish, and one with ``priced_events == 1`` and
``total_cost_usd == 0.0`` has a measured zero. :func:`format_call_cost` renders the first
as :data:`NOT_MEASURED` and the second as ``$0.00``.

:func:`call_cost_of` is the same discipline on the way in. The manager charges whatever the
operator layer hands back, and an operator that predates this field -- a stub, a
third-party backend, a test double -- hands back something that is not a report. Reading
that as zero would publish a measurement nobody took.

Recorded and provably unread
----------------------------
Everything here is inert by construction. The names in :data:`INERT_NAMES` may appear in a
record, in a summary and in a formatter, and never in a condition anywhere under ``src/``:
``tests/test_cost_is_recorded_and_unread.py`` walks the syntax of every module and fails on
a comparison, a boolean operator, an ``if``, a comprehension filter, a ``sorted`` key or a
``max`` over any of them. That is the same shape ``tests/test_router_budget.py`` uses to
assert ``StageRouter.choose`` never branches on a budget it is only handed.

The discipline that makes it satisfiable is worth stating, because it is not an accident of
this file: **nothing here branches on a named field.** Summing, serialising and formatting
all iterate :data:`COST_FIELDS`, so the value under test is a local called ``value`` and the
field name is never in the test. A new field is added to that tuple and inherits the
arithmetic, the record and the gate at once; a new field spelled into a branch instead
fails the gate rather than joining it quietly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


#: The four halves of the ``usage`` block, in the order the census reports them.
#:
#: All four, because no one of them is "the token count". ``input_tokens`` is the uncached
#: remainder, ``cache_creation_input_tokens`` is what was written into the prompt cache,
#: ``cache_read_input_tokens`` is what was served from it, and ``output_tokens`` is what the
#: model produced. The first is five orders of magnitude below the third on the measured
#: runs; see this module's header.
TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "output_tokens",
)

#: The dollar figure the backend charges for one call. Named here rather than spelled at
#: the point it is read, so the literal appears once and a condition cannot reach it by
#: writing the string out again.
DOLLAR_FIELD = "total_cost_usd"

#: The key the ``usage`` block sits under on a result event.
USAGE_KEY = "usage"

#: The event type that carries a cost report.
RESULT_EVENT_TYPE = "result"

#: The key the event's own type sits under.
EVENT_TYPE_KEY = "type"

#: Every measured quantity, absent-or-present. The one place the fields are named: the
#: arithmetic, the record, the formatter and the gate all read this tuple rather than
#: spelling the names again, so a field added here joins all four at once.
COST_FIELDS: tuple[str, ...] = TOKEN_FIELDS + (DOLLAR_FIELD,)

#: The two counts that say whether anything was measured at all. Plain integers rather than
#: absent-or-present, because "no result event was seen" is itself an observation and zero
#: is the honest value for it.
COUNTER_FIELDS: tuple[str, ...] = ("result_events", "priced_events")

#: The field a :class:`CallCost` is carried under, on ``OperatorResult``, on
#: ``ReviewDecision``, on ``ValidityReviewOutcome``, on a ledger row and in the run summary.
#: One spelling everywhere, so the gate can watch one name.
RECORD_FIELD = "call_cost"

#: What a formatter prints where a number would go when nothing was measured.
#:
#: Not ``0``, not ``$0.00``, not an empty cell. A run whose reviewer really is free is a
#: different fact from a run nobody metered, and a formatter that renders them the same way
#: destroys the distinction the rest of this module exists to keep.
NOT_MEASURED = "not measured"

#: A short label per token field, for a terminal line. Keyed by the field name rather than
#: parallel to :data:`TOKEN_FIELDS`, so a field added to that tuple without a label here
#: fails ``tests/test_cost_is_recorded_and_unread.py`` instead of printing its own
#: identifier at a reader.
TOKEN_LABELS: dict[str, str] = {
    "input_tokens": "input",
    "cache_creation_input_tokens": "cache_write",
    "cache_read_input_tokens": "cache_read",
    "output_tokens": "output",
}

#: The addends :func:`billed_tokens` sums, spelled for a human and derived from the labels
#: rather than written out again. Printed beside the total every time, because "tokens
#: used" is the figure trap two ruins: on the measured runs the same invocation is 5,117
#: tokens or 674 million depending on which fields are in the sum.
TOKEN_SUM_LABEL = " + ".join(TOKEN_LABELS[name] for name in TOKEN_FIELDS)

#: Every name no condition under ``src/`` may read.
#:
#: The measured fields, the counters that say whether they were measured, the attribute they
#: are carried under, and the constants that declare them -- because a rule reading
#: ``COST_FIELDS`` in a branch is deciding on cost just as surely as one reading
#: ``total_cost_usd``, and it is the shape a new field would be smuggled past the list in.
#:
#: :class:`CallCost` itself is deliberately **not** here, and the carve-out is narrow and
#: written down: ``isinstance(value, CallCost)`` in :func:`call_cost_of` is a type test, not
#: a decision about an amount, and it is precisely the check that keeps an unmeasured report
#: out of the arithmetic. A gate that forbade it would forbid the mechanism that enforces
#: "absent, not zero".
INERT_NAMES: tuple[str, ...] = COST_FIELDS + COUNTER_FIELDS + (
    RECORD_FIELD,
    "TOKEN_FIELDS",
    "COST_FIELDS",
    "COUNTER_FIELDS",
    "DOLLAR_FIELD",
    "INERT_NAMES",
    "billed_tokens",
)


def _sum(left: Any, right: Any) -> Any:
    """Add two absent-or-present measurements.

    Absent plus absent is absent. Absent plus a number is that number: a visit whose fake
    reviewer reported nothing and whose operator reported $3 cost $3 as far as anybody
    measured, and writing the reviewer's silence down as a zero would be the claim this
    module refuses. The counters say how much of the visit the number covers.

    Written over two anonymous operands rather than per field, so no cost field's name ever
    appears in the comparison -- which is what makes the gate satisfiable at all.
    """
    if left is None:
        return right
    if right is None:
        return left
    return left + right


def _whole(value: Any) -> int | None:
    """A token count, or ``None`` when the backend did not report one.

    Booleans are rejected along with everything else that is not an ``int``: ``True`` is an
    ``int`` in Python and a usage block that carried one would otherwise add 1 to a token
    total.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _money(value: Any) -> float | None:
    """A dollar figure, or ``None`` when the backend did not report one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


@dataclass(frozen=True)
class CallCost:
    """What one or more backend calls reported spending.

    The default is the unmeasured report: no result event seen, nothing priced, every
    measurement absent. That is what a fake operator, a stubbed operator and a backend
    without a usage block all produce, and it is deliberately not a row of zeroes.
    """

    #: ``{"type": "result"}`` events observed. Not dispatched invocations: on the measured
    #: runs the two come apart -- ``tools/log_cost_census.py`` counts 82, 95 and 95 dispatch
    #: records against 82, 99 and 100 result events, so two of the three runs saw
    #: invocations that ended with more than one result. Summing over events is right
    #: either way, and the counter is named for what it counts.
    result_events: int = 0
    #: Of those, how many carried at least one of :data:`COST_FIELDS`. Zero means nothing
    #: here was measured, however many events went by.
    priced_events: int = 0
    input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    output_tokens: int | None = None
    total_cost_usd: float | None = None

    def __add__(self, other: object) -> "CallCost":
        """Sum two reports field by field, absent-aware.

        This is the whole of trap one. ``total_cost_usd`` is a per-call charge, so a visit's
        bill is the sum of its calls' and a run's is the sum of its visits'. Nothing
        anywhere takes a maximum or a last value.
        """
        if not isinstance(other, CallCost):
            return NotImplemented
        merged: dict[str, Any] = {
            name: getattr(self, name) + getattr(other, name) for name in COUNTER_FIELDS
        }
        merged.update(
            {name: _sum(getattr(self, name), getattr(other, name)) for name in COST_FIELDS}
        )
        return CallCost(**merged)

    @classmethod
    def from_result_event(cls, event: Mapping[str, Any]) -> "CallCost":
        """One event's report. Every field the event did not carry stays absent.

        The caller has already decided the event is a result; :func:`is_result_event` is
        the one place that test lives.
        """
        usage = event.get(USAGE_KEY)
        block: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
        measured: dict[str, Any] = {name: _whole(block.get(name)) for name in TOKEN_FIELDS}
        measured[DOLLAR_FIELD] = _money(event.get(DOLLAR_FIELD))
        present = sum(1 for name in COST_FIELDS if measured[name] is not None)
        return cls(result_events=1, priced_events=1 if present else 0, **measured)

    @classmethod
    def from_mapping(cls, payload: Any) -> "CallCost":
        """Rebuild a report from its serialised form, or the unmeasured one.

        Never raises and never guesses. A ledger written by an older version has no such
        key at all, and reading its absence as a row of zeroes is exactly the mistake
        ``STAGE_COST_LEDGER_VERSION`` exists to make visible.
        """
        if not isinstance(payload, Mapping):
            return cls()
        counters = {name: _whole(payload.get(name)) or 0 for name in COUNTER_FIELDS}
        measured: dict[str, Any] = {name: _whole(payload.get(name)) for name in TOKEN_FIELDS}
        measured[DOLLAR_FIELD] = _money(payload.get(DOLLAR_FIELD))
        return cls(**counters, **measured)

    def to_dict(self) -> dict[str, Any]:
        """The serialised form. Absent fields are written as ``null``, not dropped.

        Written rather than omitted so a reader meets the absence instead of having to
        notice it: a missing key reads as "this version had no such field" and an explicit
        ``null`` reads as "this call reported nothing", and only one of those is true here.
        """
        payload: dict[str, Any] = {name: getattr(self, name) for name in COUNTER_FIELDS}
        payload.update({name: getattr(self, name) for name in COST_FIELDS})
        return payload


def is_result_event(event: Any) -> bool:
    """Whether a stream line is the event that carries a cost report."""
    return isinstance(event, Mapping) and event.get(EVENT_TYPE_KEY) == RESULT_EVENT_TYPE


def call_cost_of(value: Any) -> CallCost:
    """*value* if it is a report, and the unmeasured report otherwise.

    The manager charges whatever the operator layer hands back. An operator written before
    this field existed -- a third-party backend, a stub in a test, a ``MagicMock`` standing
    in for a result -- hands back an attribute that is not a :class:`CallCost`, and the only
    two things to do with it are to publish a number nobody measured or to say nothing was
    measured. This says nothing was measured.
    """
    return value if isinstance(value, CallCost) else CallCost()


def cost_from_stream_meta(meta: Any) -> CallCost:
    """The report ``_run_streaming_command`` left in its ``stream_meta``.

    The cost rides in that mapping rather than in a sixth return value because
    ``stream_meta`` is already the channel for everything the stream said about itself, is
    already written into the per-attempt record under ``operator_state/``, and is already
    threaded through every caller. A sixth element would have to be unpacked at nine call
    sites, three of which belong to panels whose fan-out the ledger deliberately does not
    charge.
    """
    if not isinstance(meta, Mapping):
        return CallCost()
    return CallCost.from_mapping(meta.get(RECORD_FIELD))


class CostTally:
    """A sink a callee adds to, for the one caller that charges what it spent.

    ``AutomatedReviewer.run_prompt`` is reached by the approval gate, by the review panel's
    seats, by the deliberation panel's voices and by the ideation panel's lenses. Only the
    first of those is inside the boundary ``StageCostRow.review_invocations`` counts -- the
    panels' fan-out happens below it and is deliberately not claimed -- so widening the
    return type would make eight call sites restate a number seven of them do not charge.
    An explicit sink, passed by the caller that does charge it, keeps the change where the
    charge is.
    """

    def __init__(self) -> None:
        self.total = CallCost()

    def add(self, cost: CallCost) -> None:
        self.total = self.total + cost


def billed_tokens(cost: CallCost) -> int | None:
    """The four token fields, summed, or ``None`` when none of them was reported.

    Named for the sum rather than called ``tokens`` on purpose. The single figure a reader
    wants is the one trap two ruins, and there is no honest way to publish it except beside
    the addends -- which is why :func:`format_call_cost` prints :data:`TOKEN_SUM_LABEL`
    every time it prints this number.
    """
    total: int | None = None
    for name in TOKEN_FIELDS:
        total = _sum(total, getattr(cost, name))
    return total


def _count(value: Any) -> str:
    return NOT_MEASURED if value is None else f"{value:,}"


def _dollars(value: Any) -> str:
    return NOT_MEASURED if value is None else f"${value:,.2f}"


def format_call_cost(cost: CallCost) -> str:
    """One line: the dollars, the four token fields, and the sum with its addends named.

    Every branch here is on a local, never on a field: the field names come out of
    :data:`TOKEN_FIELDS` and the value under test is anonymous, which is what lets this
    formatter live in ``src/`` under the gate.
    """
    parts = [f"{TOKEN_LABELS[name]} {_count(getattr(cost, name))}" for name in TOKEN_FIELDS]
    return (
        f"{_dollars(cost.total_cost_usd)}; "
        + ", ".join(parts)
        + f"; {TOKEN_SUM_LABEL} = {_count(billed_tokens(cost))} tokens"
    )


def describe_coverage(cost: CallCost) -> str:
    """How many of the events the numbers above came from actually carried a price.

    Both counts, always, because the interesting case is the one where they differ: a
    backend that answered and said nothing about money prints ``0 of 3`` and a total of
    :data:`NOT_MEASURED`, which is a different fact from a run that made no call at all and
    prints ``0 of 0``.

    Deliberately **not** divided by the manager's own invocation counters. Those count
    dispatches and this counts result events, and the two are not the same number: over the
    three measured runs ``tools/log_cost_census.py`` finds 82, 95 and 95 dispatch records
    against 82, 99 and 100 result events, so two of the three saw invocations that ended
    with more than one result. A line reading "99 of 95" would look like a bug in the
    accounting rather than a fact about the stream.
    """
    return (
        f"{cost.priced_events} of {cost.result_events} backend result event(s) "
        "carried a cost report"
    )
