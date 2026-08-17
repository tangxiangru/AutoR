#!/usr/bin/env python3
"""Replay finished runs against the supervisor's rules, and report what would have fired.

The thresholds in :mod:`src.supervisor` are measured rather than chosen, and this is the
measurement. Point it at finished run directories and it reconstructs, per stage visit,
the attempt sequence, what each attempt was spent on, **what each attempt produced**, and
how the visit ended; then reports for each candidate threshold which visits the rule would
have acted on and what cutting there would have cost.

The invocation every number in ``src/supervisor.py``'s docstring comes from is the three
finished runs, named rather than globbed -- see :data:`MEASURED_RUNS`::

    python3 tools/supervisor_threshold_replay.py \
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Astronomy_000_20260814_175426/.autor/*/ \
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Astronomy_000_20260815_074118/.autor/*/ \
        /rmeng_data/robtang/rcb-trial-graph/workspaces/Chemistry_000_20260816_011751/.autor/*/

The first two lines of the report say which population was loaded and whether it is that
one. ``workspaces/*/.autor/*/`` picks up a fourth run that is still being written and is a
different population every day; the report refuses to compare against it.

**Counting iterations is not measuring a saving.** The first version of this instrument
reported, per candidate threshold, how many attempt-loop iterations the rule would not
have bought -- and nothing about what those iterations produced. Chosen against that
column, ``STOP_AFTER_IDENTICAL_FAILURES = 2`` looked like it saved 17 iterations; 16 of
them came out of two visits that were, at the time, repairing the validation failure,
promoting a validated draft and discharging obligations, and both of those visits ended
auto-skipped with the rescued draft as the stage's output. :func:`bought` and
:func:`draft_was_valid` are the missing columns, and ``inert`` -- iterations that produced
nothing -- is the one a threshold may be chosen against.

**It calls the shipped predicates.** ``unchanging_failure``, ``disproportionate``,
``ration``, ``unsettled_visits`` and ``failure_digest`` are imported, not reimplemented, so
a threshold that moves in ``src/supervisor.py`` moves here and a rule that changes shape
cannot leave a stale number behind in a docstring. Reimplementing the rule in the
instrument that measures it is how a measurement comes out right about a program that does
something else.

**Why it reads ``logs.txt``.** The per-stage cost ledger this replay is *about* did not
exist when these runs were walked, so the only record of what each attempt was spent on is
the run's own log. The reconstruction below mirrors :func:`src.stage_cost.classify_refusal`
and the attempt loop's control flow: an attempt is charged to the validators when local
normalisation failed after repair, to the cross-model reviewer when the audit disagreed,
to the polish loop when the evolution controller directed another round, and to the
approval gate when the reviewer's choice was not an approval. It is a reconstruction, and
the flag ``--per-visit`` prints it in full so a reader can check it against the log rather
than take it on trust.
"""

from __future__ import annotations

import argparse
import glob
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stage_cost import (  # noqa: E402
    CROSS_REVIEW_VETOED,
    POLISH_ROUND,
    REVIEWER_REFUSED,
    VALIDATORS_REFUSED,
    failure_digest,
)
from src.utils import STAGES  # noqa: E402
from src.supervisor import (  # noqa: E402
    DISPROPORTIONATE_MULTIPLE,
    MIN_ATTEMPTS_AT_STAKE,
    MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION,
    STOP_AFTER_IDENTICAL_FAILURES,
    UNSETTLED_VISITS_BEFORE_A_REDIRECT,
    countable_digests,
    disproportionate,
    longest_unchanged_run,
    ration,
    unchanging_failure,
    unsettled_visits,
)

ENTRY = re.compile(r"^=== ([0-9T:\-]+) \| (.*?) ===$", re.M)
ATTEMPT = re.compile(r"^(\d\d_[a-z_]+) attempt (\d+) (.*)$")
SKIP = re.compile(r"^(\d\d_[a-z_]+) unattended_auto_skip$")
#: How a visit ended, as the manager writes it. `approved` is the only one
#: :data:`~src.supervisor.SETTLED_OUTCOMES` counts as settled, which is what the redirect
#: column below has to know per visit.
CLOSED = re.compile(r"^(\d\d_[a-z_]+) (approved|max_attempts_exceeded|stage_stuck|skipped)$")

#: Stage number of the node that writes the deliverable, for the last-resort rule. The
#: replayed runs all ran to `WRITING_STAGE`, whose number is read from the shipped stage
#: list rather than spelled here.
DELIVERABLE_NUMBER = next(stage.number for stage in STAGES if stage.slug == "07_writing")

# ---------------------------------------------------------------------------
# The population the shipped numbers were measured over
# ---------------------------------------------------------------------------

#: The three finished runs of the first live paired trial, named rather than globbed.
#:
#: The glob in the usage line above is a *moving target* and quoting a number from it is
#: how ``src/supervisor.py`` came to claim a denominator no invocation printed. A fourth
#: run under the same trial directory was still walking when the thresholds were measured
#: and is still walking now: ``workspaces/*/.autor/*/`` gave 26 visits / 166 iterations
#: when the branch was written and 27 / 167 the next day, and neither is the population
#: any threshold here was chosen against. These three have a terminal ``run_complete``,
#: ``run_aborted`` or ``unattended_abort`` entry in their logs and cannot move again.
MEASURED_RUNS: tuple[str, ...] = (
    "Astronomy_000_20260814_175426",
    "Astronomy_000_20260815_074118",
    "Chemistry_000_20260816_011751",
)

#: What :data:`MEASURED_RUNS` reconstructs to. Every population figure in
#: ``src/supervisor.py``'s docstring is one of these two, and
#: :func:`population_matches` is what makes running the tool on the documented
#: invocation refuse to print a different one in silence.
MEASURED_VISITS = 22
MEASURED_ITERATIONS = 141

# ---------------------------------------------------------------------------
# What an iteration bought
# ---------------------------------------------------------------------------

#: An attempt's own productive outcome, if it had one, most decisive first.
#:
#: This column is the one the first version of this instrument did not have, and its
#: absence is what made ``STOP_AFTER_IDENTICAL_FAILURES`` look measured when it was not.
#: The old report counted iterations a candidate ``N`` would not have bought and stopped
#: there. "Not bought" is a cost only if the iteration produced nothing; the two visits
#: carrying 16 of the 17 iterations ``N=2`` claimed to save each contain a repair that
#: cleared the validation failure, a promoted draft, and obligations discharged, and both
#: ended auto-skipped with the validated draft rescued rather than the 1.9KB stub. An
#: iteration that produced the stage's output is not a saving.
#:
#: Each label is a log entry the manager writes at a moment nothing else writes it:
#:
#: * ``repair_cleared_validation`` -- the attempt failed validation and did *not* go on to
#:   record ``local_normalization_failed``, which is the manager's own record that repair
#:   or local normalisation put the draft back inside the gate. This is the state the
#:   attempt loop calls a cleared failure, so a cut before it throws away a fix that worked.
#: * ``draft_promoted`` -- ``evolution_promoted`` or ``evolution_first``: a validated draft
#:   entered or won the champion slot, which is exactly what ``_validated_draft_for_skip``
#:   looks for when a visit is auto-skipped.
#: * ``reviewer_approved`` -- the approval gate returned an approval on this attempt.
#: * ``obligations_discharged`` -- ``obligation_discharged``, one per obligation closed.
PRODUCED_REPAIR = "repair_cleared_validation"
PRODUCED_DRAFT = "draft_promoted"
PRODUCED_APPROVAL = "reviewer_approved"
PRODUCED_OBLIGATIONS = "obligations_discharged"
PRODUCED_NOTHING = "nothing"

PRODUCTIVE_OUTCOMES: tuple[str, ...] = (
    PRODUCED_APPROVAL,
    PRODUCED_DRAFT,
    PRODUCED_REPAIR,
    PRODUCED_OBLIGATIONS,
)


def _entries(path: Path) -> list[tuple[str, str, str]]:
    """Every ``=== timestamp | heading ===`` block in a run log, with its body."""
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[tuple[str, str, str]] = []
    last: tuple[str, str, int] | None = None
    for match in ENTRY.finditer(text):
        if last is not None:
            out.append((last[0], last[1], text[last[2] : match.start()]))
        last = (match.group(1), match.group(2), match.end())
    if last is not None:
        out.append((last[0], last[1], text[last[2] :]))
    return out


def _field(body: str, name: str) -> str:
    match = re.search(rf"^{name}:\s*(.*)$", body, re.M)
    return match.group(1).strip() if match else ""


def _reason(body: str) -> str:
    match = re.search(r"^reason:\s*(.*)", body, re.M | re.S)
    return match.group(1).strip() if match else ""


def visits(path: Path) -> list[dict[str, Any]]:
    """One entry per stage visit: its slug, how it ended, and one record per attempt.

    A visit is a maximal run of consecutive attempt entries carrying the same slug, which
    is what a stage visit looks like in the log: the manager writes nothing for another
    stage while one is open. ``outcome`` is the closing entry that follows those attempts
    -- ``approved`` or one of the three ways a visit ends without one -- and it is what
    the redirect column reads through the shipped :func:`~src.supervisor.unsettled_visits`.
    """
    sequence: list[tuple[str, int, str, str]] = []
    #: Auto-skips the run had spent by the time each attempt entry was written. The run
    #: log records one `unattended_auto_skip` per unit, so counting them forward gives the
    #: state the last-resort rule reads at every boundary.
    skips_at: dict[int, int] = {}
    #: How the visit that owned each attempt ended, keyed the same way: the closing entry
    #: is written after the attempts, so it is attached backwards to the open group.
    closed_at: dict[int, str] = {}
    spent = 0
    for _, heading, body in _entries(path):
        if SKIP.match(heading):
            spent += 1
            continue
        ending = CLOSED.match(heading)
        if ending is not None:
            closed_at[len(sequence)] = ending.group(2)
            continue
        match = ATTEMPT.match(heading)
        if match:
            skips_at[len(sequence)] = spent
            sequence.append((match.group(1), int(match.group(2)), match.group(3), body))

    grouped: list[tuple[str, list[tuple[int, str, str]]]] = []
    for slug, number, kind, body in sequence:
        if not grouped or grouped[-1][0] != slug:
            grouped.append((slug, []))
        grouped[-1][1].append((number, kind, body))

    seen = 0
    out: list[dict[str, Any]] = []
    for slug, items in grouped:
        skips_before = skips_at.get(seen, 0)
        seen += len(items)
        by_attempt: dict[int, dict[str, str]] = defaultdict(dict)
        order: list[int] = []
        for number, kind, body in items:
            if number not in by_attempt:
                order.append(number)
            by_attempt[number][kind] = body
        attempts: list[dict[str, Any]] = []
        for number in order:
            entry = by_attempt[number]
            kind, reason = _classify(entry)
            attempts.append(
                {
                    "attempt": number,
                    "kind": kind,
                    "digest": failure_digest(kind, reason) if kind else "",
                    "bought": bought(entry),
                    "draft_valid": draft_was_valid(entry),
                }
            )
        number = next((item.number for item in STAGES if item.slug == slug), 0)
        out.append(
            {
                "stage": slug,
                "stage_number": number,
                "skips_before": skips_before,
                # `approved` is the only settled outcome; a visit whose closing entry is
                # missing from the log (a run killed mid-visit) is not an approval either,
                # and reading it as one would be the unsafe direction.
                "outcome": closed_at.get(seen, ""),
                "attempts": attempts,
            }
        )
    return out


def bought(entry: dict[str, str]) -> tuple[str, ...]:
    """What one attempt produced, from the entries the manager wrote for it.

    Empty for an attempt that produced nothing. An attempt can buy more than one thing --
    the promoted draft and the obligations discharged beside it are one attempt in both of
    the visits ``N=2`` would have cut -- so this is a tuple ordered by
    :data:`PRODUCTIVE_OUTCOMES` rather than a single label.

    Two deliberate conservatisms, both in the direction that makes the *rule* look better
    rather than worse, because the point of this column is to stop the rule being credited
    with a saving it did not make:

    * an approval the cross-model reviewer then vetoed is not an approval. Six attempts in
      this population have ``reviewer_choice: 5`` and ``cross_review`` reading
      ``agrees: False`` on the same attempt; the veto is what the loop acted on, so the
      attempt bought nothing.
    * ``obligation_recorded`` and ``obligations_deferred`` are not discharges. Only
      ``obligation_discharged`` counts.
    """
    produced: list[str] = []
    gate = entry.get("reviewer_choice")
    audit = entry.get("cross_review")
    vetoed = audit is not None and _field(audit, "agrees") == "False"
    if not vetoed and ("approved" in entry or (gate is not None and _field(gate, "choice") == "5")):
        produced.append(PRODUCED_APPROVAL)
    if "evolution_promoted" in entry or "evolution_first" in entry:
        produced.append(PRODUCED_DRAFT)
    if "validation_failed" in entry and "local_normalization_failed" not in entry:
        produced.append(PRODUCED_REPAIR)
    if "obligation_discharged" in entry:
        produced.append(PRODUCED_OBLIGATIONS)
    return tuple(label for label in PRODUCTIVE_OUTCOMES if label in produced)


def draft_was_valid(entry: dict[str, str]) -> bool:
    """Whether the draft on disk was inside the gate when this attempt ended.

    The decisive column, and the one behind the harm ``N=2`` would have done. When a visit
    is auto-skipped, :meth:`~src.manager.ResearchManager._validated_draft_for_skip` reads
    the tmp draft and keeps it as the stage's output if it still passes the markdown and
    artifact gates; otherwise the 1.9KB skip stub becomes the output every downstream
    stage reads. ``local_normalization_failed`` is the manager's own record that the draft
    did *not* pass, so an attempt that ends there is an attempt after which there is
    nothing to rescue.

    That is a structural fact about ``stop_spending`` and not a fact about this data: the
    rule cuts on a *repeated* failure, and a repeated validator refusal is by construction
    a moment at which the draft is outside the gate.
    """
    return "local_normalization_failed" not in entry


def _classify(entry: dict[str, str]) -> tuple[str, str]:
    """What one attempt was spent on, in :mod:`src.stage_cost`'s vocabulary.

    Ordered as the attempt loop is: a draft that failed validation, repair and local
    normalisation is charged to the validators before anything else looks at it; a
    cross-model veto overrides an approval the primary gave, so it is read before the
    primary's own choice; a directed polish round is not a failure and is charged to the
    polish budget.
    """
    if "local_normalization_failed" in entry:
        return VALIDATORS_REFUSED, entry.get("validation_failed", entry["local_normalization_failed"])
    audit = entry.get("cross_review")
    if audit is not None and _field(audit, "agrees") == "False":
        return CROSS_REVIEW_VETOED, _reason(audit)
    if "evolution_directed" in entry:
        return POLISH_ROUND, ""
    gate = entry.get("reviewer_choice")
    if gate is not None and _field(gate, "choice") not in {"5", "6", ""}:
        return REVIEWER_REFUSED, _reason(gate)
    return "", ""


def charged(visit: dict[str, Any], through: int | None = None) -> int:
    """Attempts in *visit* that the loop charges against ``--max-attempts``."""
    return sum(
        1
        for item in visit["attempts"]
        if item["kind"] != POLISH_ROUND and (through is None or item["attempt"] <= through)
    )


def failure_digests(visit: dict[str, Any], through: int | None = None) -> list[str]:
    """The visit's countable failure digests in order, filtered by the shipped rule."""
    return countable_digests(
        [
            item
            for item in visit["attempts"]
            if item["kind"]
            and item["kind"] != POLISH_ROUND
            and (through is None or item["attempt"] <= through)
        ]
    )


def kind_runs(visit: dict[str, Any], through: int | None = None) -> list[str]:
    """The visit's failure *kinds* in order: the looser rule, for the control column.

    "The reviewer refused three times running" is a weaker claim than "the reviewer made
    the same objection three times running", and the report prints what the weaker one
    would have cost so the choice of digest is a measured one rather than an assumed one.
    """
    return [
        item["kind"]
        for item in visit["attempts"]
        if item["kind"]
        and item["kind"] != POLISH_ROUND
        and (through is None or item["attempt"] <= through)
    ]


def stop_fires(
    runs: Sequence[tuple[str, list[dict[str, Any]]]],
    repeats: int,
    *,
    ceiling: int | None = None,
    at_stake: int = 0,
    on_kinds: bool = False,
) -> list[dict[str, Any]]:
    """Where ``stop_spending`` would have cut, at *repeats* identical failures.

    *at_stake* replays the second half of the rule: the intervention is declined when the
    run's own ``--max-attempts`` is within that many attempts of ending the visit anyway.
    Zero replays the rule without it, which is what the two columns in the report compare.
    """
    fires: list[dict[str, Any]] = []
    for name, walk in runs:
        for visit in walk:
            for item in visit["attempts"]:
                if not item["kind"] or item["kind"] == POLISH_ROUND:
                    continue
                window = (
                    kind_runs(visit, through=item["attempt"])
                    if on_kinds
                    else failure_digests(visit, through=item["attempt"])
                )
                if ceiling is not None and at_stake:
                    left = max(ceiling - charged(visit, through=item["attempt"]), 0)
                    if left < at_stake:
                        continue
                if unchanging_failure(window, repeats=repeats):
                    cut = [
                        other
                        for other in visit["attempts"]
                        if other["attempt"] > item["attempt"]
                    ]
                    produced = [label for other in cut for label in other["bought"]]
                    fires.append(
                        {
                            "run": name,
                            "stage": visit["stage"],
                            "cut_after": item["attempt"],
                            "visit_ran_to": visit["attempts"][-1]["attempt"],
                            "iterations": len(visit["attempts"]),
                            # The column the first version of this instrument did not
                            # have. `cut_iterations` is what the old report called
                            # "not bought"; the two beside it split that number by
                            # whether the iteration produced anything.
                            "cut_iterations": len(cut),
                            "cut_productive": sum(1 for other in cut if other["bought"]),
                            "cut_inert": sum(1 for other in cut if not other["bought"]),
                            "produced": produced,
                            "outcome": visit["outcome"],
                            # Whether the visit would still have had something to rescue
                            # if it had ended here. See `draft_was_valid`.
                            "draft_valid_at_cut": item["draft_valid"],
                            "draft_valid_at_end": visit["attempts"][-1]["draft_valid"],
                        }
                    )
                    break
    return fires


def reallocate_fires(
    runs: Sequence[tuple[str, list[dict[str, Any]]]],
    *,
    multiple: float,
    minimum_population: int,
    shadowed_by_stop: bool,
    ceiling: int | None = None,
) -> list[dict[str, Any]]:
    """Where ``reallocate`` would have fired, on the run's own distribution.

    *shadowed_by_stop* replays the rules in the order the supervisor asks them: a visit
    ``stop_spending`` has already cut cannot also be reallocated, and a proportionality
    rule that counts those visits is taking credit for another rule's work.

    The two spends here are deliberately different numbers, because the rule asks two
    different questions with them, and the supervisor passes the same two:

    * the *trigger* is the stage's charged attempts summed over all its visits against the
      median of the stages that have closed -- lifetime against lifetime, which is what
      "disproportionate on the run's own terms" means;
    * the *amount* is what this **visit** has charged plus that median, because the pool
      is denominated in per-visit allowances. Comparing a per-visit allowance against a
      lifetime spend is how a rule stops firing on exactly the revisits it was written
      for: on a second visit the lifetime spend already exceeds the ceiling and the
      surplus is always zero.
    """
    fires: list[dict[str, Any]] = []
    for name, walk in runs:
        closed: dict[str, int] = {}
        for index, visit in enumerate(walk):
            slug = visit["stage"]
            # What the stage's *later* visits went on to charge. A transfer lowers the
            # donor's per-visit allowance for good, so whether the intervention cost the
            # run anything is a question about the visits after it, not about this one.
            later = [
                charged(other) for other in walk[index + 1 :] if other["stage"] == slug
            ]
            cut = None
            if shadowed_by_stop:
                stops = stop_fires(
                    [(name, [visit])],
                    STOP_AFTER_IDENTICAL_FAILURES,
                    ceiling=ceiling,
                    at_stake=MIN_ATTEMPTS_AT_STAKE,
                )
                cut = stops[0]["cut_after"] if stops else None
            others = [value for other, value in closed.items() if other != slug]
            for item in visit["attempts"]:
                if cut is not None and item["attempt"] > cut:
                    break
                in_visit = charged(visit, through=item["attempt"])
                spent = closed.get(slug, 0) + in_visit
                keep = ration(in_visit, others) if others else 0
                surplus = max((ceiling or 0) - keep, 0)
                unentered = [
                    item.slug
                    for item in STAGES
                    if item.slug not in closed and item.slug != slug
                ]
                if (
                    surplus > 0
                    and unentered
                    and disproportionate(
                        spent, others, multiple=multiple, minimum_population=minimum_population
                    )
                ):
                    fires.append(
                        {
                            "run": name,
                            "stage": slug,
                            "at_attempt": item["attempt"],
                            "charged": spent,
                            "median": statistics.median(others),
                            "ration": keep,
                            "moves": surplus,
                            "to": unentered,
                            "visit_spent": charged(visit),
                            "later_visits": later,
                            # Whether the narrowed per-visit allowance would have bound:
                            # this visit's remaining spend, or any later visit's.
                            "binds": charged(visit) > keep or any(spent > keep for spent in later),
                        }
                    )
                    break
            closed[slug] = closed.get(slug, 0) + charged(visit)
    return fires


def redirect_fires(
    runs: Sequence[tuple[str, list[dict[str, Any]]]],
    *,
    unsettled_before: int = UNSETTLED_VISITS_BEFORE_A_REDIRECT,
) -> list[dict[str, Any]]:
    """Where ``redirect`` would have been reached, at each stage exit.

    This column did not exist, and two sentences in :mod:`src.supervisor` credited this
    file with producing it anyway. The rule is ``unsettled_visits(rows, slug) >=
    UNSETTLED_VISITS_BEFORE_A_REDIRECT`` evaluated where the manager evaluates it -- on
    the way out of a stage, over the ledger rows closed *including* the visit that has
    just ended, because ``_run_stage`` appends the row before ``_advance_from`` asks.

    ``unsettled_visits`` is imported, not reimplemented, so this reports on the shipped
    predicate; what the replay supplies is the ``outcome`` per visit, reconstructed from
    the closing entry in the log. The rows are shaped as
    :func:`~src.stage_cost.read_stage_cost_ledger` returns them for the same reason.

    What is *not* replayed is the second half of the rule -- whether the graph left a
    forward edge open at that exit -- because the admissible set is computed from live
    graph state the log does not carry. That only ever removes firings, so a count of
    zero here is a count of zero for the whole rule, and any non-zero count is an upper
    bound. The report says so beside the number.
    """
    fires: list[dict[str, Any]] = []
    for name, walk in runs:
        rows: list[dict[str, Any]] = []
        for visit in walk:
            # The log's closing entry is already the ledger's vocabulary for the one
            # outcome that matters here: `approved` is `OUTCOME_APPROVED`, and every
            # other closing entry is one of the ways a visit ends without an approval.
            rows.append({"stage": visit["stage"], "outcome": visit["outcome"]})
            unsettled = unsettled_visits(rows, visit["stage"])
            if unsettled >= unsettled_before:
                fires.append(
                    {
                        "run": name,
                        "stage": visit["stage"],
                        "unsettled": unsettled,
                        "visits": sum(1 for row in rows if row["stage"] == visit["stage"]),
                    }
                )
    return fires


def escalate_fires(
    runs: Sequence[tuple[str, list[dict[str, Any]]]],
    *,
    ceiling: int,
    max_auto_skips: int,
) -> list[dict[str, Any]]:
    """Where the last resort would have been reached, and what it would have cost.

    The three conditions in :mod:`src.supervisor`'s ``no_recovery_left``, replayed: the
    skip budget spent, the run at or past the node that writes the deliverable, and the
    visit with nothing left to buy. ``cost`` is how many attempt-loop iterations the
    ruling would have taken away, and zero is the answer the third condition exists to
    produce.
    """
    fires: list[dict[str, Any]] = []
    for name, walk in runs:
        for visit in walk:
            if visit["skips_before"] < max_auto_skips or visit["stage_number"] < DELIVERABLE_NUMBER:
                continue
            for item in visit["attempts"]:
                spent = charged(visit, through=item["attempt"])
                at_stake = max(ceiling - spent, 0)
                window = failure_digests(visit, through=item["attempt"])
                if at_stake <= 0 or unchanging_failure(window):
                    fires.append(
                        {
                            "run": name,
                            "stage": visit["stage"],
                            "at_attempt": item["attempt"],
                            "skips_before": visit["skips_before"],
                            "cost": len(visit["attempts"]) - item["attempt"],
                        }
                    )
                    break
    return fires


def population_matches(names: Sequence[str], visits_seen: int, iterations: int) -> str:
    """One line saying whether this invocation is the documented one, and whether it drifted.

    Three answers, and the middle one is the whole point of the function. If *names* is
    not :data:`MEASURED_RUNS` the report says so and claims nothing: a reader who globbed
    a directory containing a run still being written is looking at a different population
    from the one the thresholds were chosen against, and no comparison is offered. If it
    *is* :data:`MEASURED_RUNS` and the totals differ from :data:`MEASURED_VISITS` and
    :data:`MEASURED_ITERATIONS`, the line says ``DRIFTED`` and prints both -- which is the
    only mechanism by which a number written into ``src/supervisor.py``'s docstring can
    stop being true out loud rather than quietly.
    """
    if tuple(names) != MEASURED_RUNS:
        return (
            "population: not the recorded one "
            f"({len(names)} run(s)); the recorded population is "
            f"{', '.join(MEASURED_RUNS)}, and no docstring figure describes this one"
        )
    if (visits_seen, iterations) != (MEASURED_VISITS, MEASURED_ITERATIONS):
        return (
            f"population: DRIFTED -- the recorded population is {MEASURED_VISITS} visit(s) "
            f"and {MEASURED_ITERATIONS} iteration(s), this reconstruction is {visits_seen} "
            f"and {iterations}; src/supervisor.py's docstring is now wrong"
        )
    return (
        f"population: as recorded -- {MEASURED_VISITS} visit(s), "
        f"{MEASURED_ITERATIONS} iteration(s) over {len(MEASURED_RUNS)} finished run(s)"
    )


def _stop_totals(fires: Sequence[dict[str, Any]], total_visits: int) -> str:
    """The two columns, side by side, so neither can be quoted without the other.

    The first version of this report printed only ``cut``. That number is what the rule
    *stops*, not what it *saves*, and the difference is the whole of item 2 of the fix:
    16 of the 17 iterations ``N=2`` claimed came out of two visits that were producing
    the stage's output at the time.
    """
    cut = sum(fire["cut_iterations"] for fire in fires)
    inert = sum(fire["cut_inert"] for fire in fires)
    productive = sum(fire["cut_productive"] for fire in fires)
    return (
        f"{len(fires)} of {total_visits} visits, {cut} iteration(s) cut "
        f"({inert} inert, {productive} productive)"
    )


def load(paths: Iterable[str]) -> list[tuple[str, list[dict[str, Any]]]]:
    runs: list[tuple[str, list[dict[str, Any]]]] = []
    for pattern in paths:
        for match in sorted(glob.glob(pattern)):
            log = Path(match) / "logs.txt" if Path(match).is_dir() else Path(match)
            if log.exists():
                runs.append((log.parent.parent.parent.name, visits(log)))
    return runs


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", help="run directories, or logs.txt paths")
    parser.add_argument("--per-visit", action="store_true", help="print the reconstruction itself")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=8,
        help="the per-visit ceiling the replayed runs walked under. The trial's four runs "
             "were driven by rcb_agent.py, whose DEFAULT_MAX_ATTEMPTS is 8, and their logs "
             "say 'Exceeded 8 attempts'. Defaults to 8.",
    )
    parser.add_argument(
        "--max-auto-skips",
        type=int,
        default=3,
        help="the auto-skip budget the replayed runs walked under. Defaults to 3, which is "
             "ResearchManager's own default and what the trial's four runs report in their "
             "skip stubs.",
    )
    args = parser.parse_args(argv)

    runs = load(args.runs)
    if not runs:
        print("no runs found")
        return 1
    total_visits = sum(len(walk) for _, walk in runs)
    total_iterations = sum(len(visit["attempts"]) for _, walk in runs for visit in walk)
    print(f"{len(runs)} run(s), {total_visits} stage visit(s), {total_iterations} attempt-loop iteration(s)")
    print(population_matches([name for name, _ in runs], total_visits, total_iterations))

    if args.per_visit:
        for name, walk in runs:
            print(f"\n### {name}")
            for visit in walk:
                digests = failure_digests(visit)
                print(
                    f"  {visit['stage']:26s} iterations={len(visit['attempts']):2d} "
                    f"charged={charged(visit):2d} distinct={len(set(digests)):2d} "
                    f"longest_unchanged_run={longest_unchanged_run(digests)} "
                    f"outcome={visit['outcome'] or 'unclosed'} "
                    f"productive_iterations="
                    f"{sum(1 for item in visit['attempts'] if item['bought'])}"
                )

    print(
        f"\n== stop_spending: identical failure digests in a row "
        f"(shipped value {STOP_AFTER_IDENTICAL_FAILURES}, at stake {MIN_ATTEMPTS_AT_STAKE}) ==\n"
        "   `cut` is how many attempt-loop iterations the rule would not have bought.\n"
        "   `inert` is how many of those produced nothing, and it is the column N is\n"
        "   chosen against: an iteration that repaired the failure, promoted a validated\n"
        "   draft, won an approval or discharged an obligation is not a saving."
    )
    for stake in (0, MIN_ATTEMPTS_AT_STAKE):
        label = "any saving" if not stake else f"{stake} attempt(s) at stake"
        for repeats in (2, 3, 4, 5):
            fires = stop_fires(runs, repeats, ceiling=args.max_attempts, at_stake=stake)
            print(f"  N={repeats}, {label}: {_stop_totals(fires, total_visits)}")
            for fire in fires:
                print(
                    f"        {fire['run']:30s} {fire['stage']:24s} cut after attempt "
                    f"{fire['cut_after']:2d}; the visit ran to {fire['iterations']} "
                    f"iteration(s) and ended {fire['outcome'] or 'unclosed'}; "
                    f"cut {fire['cut_iterations']} "
                    f"({fire['cut_inert']} inert, {fire['cut_productive']} productive"
                    + (f": {', '.join(sorted(set(fire['produced'])))}" if fire["produced"] else "")
                    + f"); draft inside the gate at the cut: "
                    + ("yes" if fire["draft_valid_at_cut"] else "NO")
                    + ", at the visit's real end: "
                    + ("yes" if fire["draft_valid_at_end"] else "no")
                )

    print("\n== control: the same rule on the failure KIND rather than the digest ==")
    for repeats in (2, 3, 4):
        fires = stop_fires(
            runs, repeats, ceiling=args.max_attempts, at_stake=MIN_ATTEMPTS_AT_STAKE, on_kinds=True
        )
        print(f"  N={repeats} on kinds: {_stop_totals(fires, total_visits)}")

    print(
        f"\n== redirect: visits that ended without an approval, per stage "
        f"(shipped value {UNSETTLED_VISITS_BEFORE_A_REDIRECT}) ==\n"
        "   An upper bound: the admissible forward set is live graph state the log does\n"
        "   not carry, and requiring it can only remove firings."
    )
    for unsettled_before in (1, 2, 3):
        fires = redirect_fires(runs, unsettled_before=unsettled_before)
        print(
            f"  {unsettled_before} unsettled visit(s): {len(fires)} of {total_visits} "
            f"stage exits reach the threshold"
        )
        for fire in fires:
            print(
                f"        {fire['run']:30s} {fire['stage']:24s} "
                f"{fire['unsettled']} unsettled of {fire['visits']} visit(s)"
            )

    print("\n== escalate: the last resort, and what taking it would have cost ==")
    fires = escalate_fires(runs, ceiling=args.max_attempts, max_auto_skips=args.max_auto_skips)
    print(f"  {len(fires)} of {total_visits} visits")
    for fire in fires:
        print(
            f"        {fire['run']:30s} {fire['stage']:24s} at attempt {fire['at_attempt']:2d} "
            f"with {fire['skips_before']} skip(s) already spent; "
            f"{fire['cost']} iteration(s) taken away"
        )

    print(
        f"\n== reallocate: a stage's charged attempts vs the run's own median "
        f"(shipped values {DISPROPORTIONATE_MULTIPLE}x, {MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION} closed stages) =="
    )
    for multiple in (1.5, 2, 2.5, 3):
        for population in (2, 3):
            for shadowed in (False, True):
                fires = reallocate_fires(
                    runs,
                    multiple=multiple,
                    minimum_population=population,
                    shadowed_by_stop=shadowed,
                    ceiling=args.max_attempts,
                )
                print(
                    f"  {multiple}x  min_closed_stages={population}  "
                    f"after_stop_spending={'yes' if shadowed else 'no ':3s}: "
                    f"{len(fires)} of {total_visits} visits"
                )
                for fire in fires:
                    print(
                        f"        {fire['run']:30s} {fire['stage']:24s} at attempt "
                        f"{fire['at_attempt']:2d}: {fire['charged']} charged vs median "
                        f"{fire['median']}, ration {fire['ration']}, moving "
                        f"{fire['moves']} unit(s) to {', '.join(fire['to']) or 'nobody'}; "
                        f"the visit charged {fire['visit_spent']} in total and this "
                        f"stage's later visits charged "
                        f"{', '.join(str(item) for item in fire['later_visits']) or 'nothing'}"
                        f"; the narrowed per-visit allowance "
                        + ("BINDS" if fire["binds"] else "binds nothing")
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
