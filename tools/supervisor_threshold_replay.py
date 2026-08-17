#!/usr/bin/env python3
"""Replay finished runs against the supervisor's rules, and report what would have fired.

The thresholds in :mod:`src.supervisor` are measured rather than chosen, and this is the
measurement. Point it at finished run directories and it reconstructs, per stage visit,
the attempt sequence and what each attempt was spent on, then reports for each candidate
threshold which visits the rule would have acted on and how many attempt-loop iterations
that would have cost or saved.

    python3 tools/supervisor_threshold_replay.py \
        /rmeng_data/robtang/rcb-trial-graph/workspaces/*/.autor/*/

**It calls the shipped predicates.** ``unchanging_failure``, ``disproportionate``,
``ration`` and ``failure_digest`` are imported, not reimplemented, so a threshold that
moves in ``src/supervisor.py`` moves here and a rule that changes shape cannot leave a
stale number behind in a docstring. Reimplementing the rule in the instrument that
measures it is how a measurement comes out right about a program that does something else.

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
    countable_digests,
    disproportionate,
    longest_unchanged_run,
    ration,
    unchanging_failure,
)

ENTRY = re.compile(r"^=== ([0-9T:\-]+) \| (.*?) ===$", re.M)
ATTEMPT = re.compile(r"^(\d\d_[a-z_]+) attempt (\d+) (.*)$")
SKIP = re.compile(r"^(\d\d_[a-z_]+) unattended_auto_skip$")

#: Stage number of the node that writes the deliverable, for the last-resort rule. The
#: replayed runs all ran to `WRITING_STAGE`, whose number is read from the shipped stage
#: list rather than spelled here.
DELIVERABLE_NUMBER = next(stage.number for stage in STAGES if stage.slug == "07_writing")


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
    """One entry per stage visit: its slug, and one record per attempt.

    A visit is a maximal run of consecutive attempt entries carrying the same slug, which
    is what a stage visit looks like in the log: the manager writes nothing for another
    stage while one is open.
    """
    sequence: list[tuple[str, int, str, str]] = []
    #: Auto-skips the run had spent by the time each attempt entry was written. The run
    #: log records one `unattended_auto_skip` per unit, so counting them forward gives the
    #: state the last-resort rule reads at every boundary.
    skips_at: dict[int, int] = {}
    spent = 0
    for _, heading, body in _entries(path):
        if SKIP.match(heading):
            spent += 1
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
                }
            )
        number = next((item.number for item in STAGES if item.slug == slug), 0)
        out.append(
            {
                "stage": slug,
                "stage_number": number,
                "skips_before": skips_before,
                "attempts": attempts,
            }
        )
    return out


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
                    fires.append(
                        {
                            "run": name,
                            "stage": visit["stage"],
                            "cut_after": item["attempt"],
                            "visit_ran_to": visit["attempts"][-1]["attempt"],
                            "iterations": len(visit["attempts"]),
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
    """
    fires: list[dict[str, Any]] = []
    for name, walk in runs:
        closed: dict[str, int] = {}
        for visit in walk:
            slug = visit["stage"]
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
                spent = closed.get(slug, 0) + charged(visit, through=item["attempt"])
                keep = ration(spent, others) if others else 0
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
                        }
                    )
                    break
            closed[slug] = closed.get(slug, 0) + charged(visit)
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

    if args.per_visit:
        for name, walk in runs:
            print(f"\n### {name}")
            for visit in walk:
                digests = failure_digests(visit)
                print(
                    f"  {visit['stage']:26s} iterations={len(visit['attempts']):2d} "
                    f"charged={charged(visit):2d} distinct={len(set(digests)):2d} "
                    f"longest_unchanged_run={longest_unchanged_run(digests)}"
                )

    print(
        f"\n== stop_spending: identical failure digests in a row "
        f"(shipped value {STOP_AFTER_IDENTICAL_FAILURES}, at stake {MIN_ATTEMPTS_AT_STAKE}) =="
    )
    for stake in (0, MIN_ATTEMPTS_AT_STAKE):
        label = "any saving" if not stake else f"{stake} attempt(s) at stake"
        for repeats in (2, 3, 4, 5):
            fires = stop_fires(runs, repeats, ceiling=args.max_attempts, at_stake=stake)
            saved = sum(fire["iterations"] - fire["cut_after"] for fire in fires)
            print(
                f"  N={repeats}, {label}: {len(fires)} of {total_visits} visits, "
                f"{saved} iteration(s) not bought"
            )
            for fire in fires:
                print(
                    f"        {fire['run']:30s} {fire['stage']:24s} cut after attempt "
                    f"{fire['cut_after']:2d}; the visit ran to {fire['iterations']} iteration(s)"
                )

    print("\n== control: the same rule on the failure KIND rather than the digest ==")
    for repeats in (2, 3, 4):
        fires = stop_fires(
            runs, repeats, ceiling=args.max_attempts, at_stake=MIN_ATTEMPTS_AT_STAKE, on_kinds=True
        )
        saved = sum(fire["iterations"] - fire["cut_after"] for fire in fires)
        print(
            f"  N={repeats} on kinds: {len(fires)} of {total_visits} visits, "
            f"{saved} iteration(s) not bought"
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
                        f"the visit went on to charge {fire['visit_spent']}"
                    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
