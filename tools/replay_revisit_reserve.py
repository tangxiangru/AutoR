"""What would :data:`~src.stage_graph.DELIVERY_RESERVE` have refused, on runs that exist?

An instrument, not a test. It replays finished AutoR runs against the shipped
:func:`~src.stage_graph.revisit_would_strand_delivery` at every candidate reserve and
prints, per run, which backward moves that reserve would have withdrawn and whether
the run would still have ended the way it did.

Nothing here reimplements the rule. The predicate is imported, so a change to it
changes this output, and a reserve read off this table is a property of ``src/`` as
it stands rather than of a model of it. That is the same contract
``tools/archive_sample_complexity.py`` works under.

**What it reads, and why those two files.** Each run directory carries the walk in
``evolution/stage_graph.json`` — every visit, in order, with the move out of it, its
kind, and the choice set that was live at the moment of choosing — and the budget in
``logs.txt``, which stamps every auto-skip with its running count. Neither is
reconstructible from the other: the graph state never records the skip budget, and
the log never records what was on the menu.

**How the budget is dated.** The running count is read out of the log rather than
modelled, because the manager spends the pool two ways and only one of them is an
``unattended_auto_skip``:

* ``unattended_auto_skip`` prints ``auto_skip_used: N/M``, so the count after it is
  ``N`` and the ceiling is ``M``.
* ``routed_to_deliverable`` prints ``already_skipped: ...`` *before* appending the
  stage that failed, so the count after it is that list plus one.
* ``unattended_abort`` prints the final list and spends nothing.

A decision is dated at the visit's ``left_at``, which is when the router ran, and
carries whatever count the last event at or before it left behind.

**Two populations, and they answer different questions.** A reserve's cost is not
only the backward moves a run *took* — it is every backward move that was on the
menu and would have come off it. ``Visit.offered`` records the choice set, so both
are counted: ``taken`` is what the rule would have reversed, ``offered`` is what it
would have hidden from the agent that chose.

**When a withdrawal could have changed the ending.** A refused revisit can only
change how a run ends if it releases a unit the run went on to spend, so this reports
a withdrawal as consequential when an auto-skip fell strictly between the withdrawn
move and the abort. A run that was never cancelled, or one where no unit was spent
after the withdrawal, is reported as unchanged — which is the answer that keeps the
table honest about a rule that mostly refuses things nothing was going to need.

    python3 tools/replay_revisit_reserve.py \\
        /rmeng_data/robtang/rcb-trial-graph/workspaces/*/.autor/*/
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.stage_graph import (  # noqa: E402
    DELIVERY_RESERVE,
    GraphState,
    StageGraph,
    revisit_would_strand_delivery,
)
from src.utils import WRITING_STAGE  # noqa: E402

#: Candidate reserves the table is printed for. ``0`` is the weakest rule that is
#: still a rule — it refuses a backward move only once the pool is empty — and the
#: top of the range is ``--max-auto-skips``' own default, which refuses every
#: backward move even from an untouched pool. Both ends are in the table so the
#: chosen value is read off a range rather than defended on its own.
CANDIDATE_RESERVES = (0, 1, 2, 3)

_HEADER = re.compile(r"^=== ([0-9T:\-]+) \| (.+?) ===$", re.M)
_USED = re.compile(r"^auto_skip_used: (\d+)/(\d+)$", re.M)
_BUDGET = re.compile(r"^auto_skip_budget: (\d+)$", re.M)
_ALREADY = re.compile(r"^already_skipped: (.*)$", re.M)

#: Which targets out of a node are backward moves, from the shipped topology rather
#: than from the ordering. A run recorded under ``--stage-graph linear`` has none, and
#: reading that off the graph keeps the two arms of the trial on one rule.
_REVISIT_TARGETS: dict[str, set[str]] = {}
for _edge in StageGraph.adaptive().edges:
    if _edge.kind == "revisit":
        _REVISIT_TARGETS.setdefault(_edge.source, set()).add(_edge.target)


@dataclass
class BudgetEvent:
    at: str
    #: Units spent once this event is over.
    used: int
    kind: str


@dataclass
class Decision:
    """One routing decision, with the budget as it stood when it was made."""

    index: int
    stage: str
    at: str
    chose: str
    kind: str
    skips_used: int
    #: Backward targets that were live on this menu, from ``Visit.offered``.
    revisits_offered: tuple[str, ...]
    #: Had the stage that writes the deliverable already run when this was decided?
    #: The stronger rule this project declined to build — "no backward edge until a
    #: deliverable exists" — is exactly ``report_exists`` on every revisit edge, and
    #: this is the closest thing the recorded walk can say about it.
    deliverable_written: bool

    def skips_left(self, ceiling: int) -> int:
        return ceiling - self.skips_used


@dataclass
class Run:
    name: str
    topology: str
    ceiling: int
    cancelled: bool
    aborted_at: str
    decisions: list[Decision] = field(default_factory=list)
    budget_events: list[BudgetEvent] = field(default_factory=list)

    def spent_between(self, start: str, end: str) -> int:
        """Units spent strictly after ``start`` and at or before ``end``."""
        return sum(1 for event in self.budget_events if start < event.at <= end)


def read_run(directory: Path) -> Run:
    state = GraphState.from_dict(json.loads((directory / "evolution" / "stage_graph.json").read_text(encoding="utf-8")))
    config = json.loads((directory / "run_config.json").read_text(encoding="utf-8"))
    log = (directory / "logs.txt").read_text(encoding="utf-8", errors="replace")

    marks = list(_HEADER.finditer(log))
    events: list[BudgetEvent] = []
    ceiling = 0
    cancelled = False
    aborted_at = ""
    for position, mark in enumerate(marks):
        name = mark.group(2)
        body = log[mark.end() : marks[position + 1].start() if position + 1 < len(marks) else len(log)]
        if name.endswith("unattended_auto_skip"):
            used = _USED.search(body)
            if used is not None:
                events.append(BudgetEvent(mark.group(1), int(used.group(1)), "auto_skip"))
                ceiling = max(ceiling, int(used.group(2)))
        elif name.endswith("routed_to_deliverable"):
            already = _ALREADY.search(body)
            if already is not None:
                names = [item for item in already.group(1).split(", ") if item and item != "(none)"]
                events.append(BudgetEvent(mark.group(1), len(names) + 1, "routed_to_deliverable"))
        elif name.endswith("unattended_abort"):
            budget = _BUDGET.search(body)
            if budget is not None:
                ceiling = max(ceiling, int(budget.group(1)))
        elif name == "run_aborted":
            cancelled = True
            aborted_at = mark.group(1)

    decisions: list[Decision] = []
    written = False
    for index, visit in enumerate(state.path, start=1):
        if not visit.left_at:
            continue  # the visit the run was interrupted in: no decision was made
        # A visit that *left* the writing stage ran it, so by the time its own move is
        # chosen a deliverable exists. Set before the decision is recorded rather than
        # after, because the corpus's one backward move is the move out of that visit.
        written = written or visit.stage == WRITING_STAGE.slug
        used = next(
            (event.used for event in reversed(events) if event.at <= visit.left_at), 0
        )
        backward = tuple(
            sorted(target for target in visit.offered if target in _REVISIT_TARGETS.get(visit.stage, set()))
        )
        decisions.append(
            Decision(index, visit.stage, visit.left_at, visit.chose, visit.kind, used, backward, written)
        )

    return Run(
        name=directory.parent.parent.name,
        topology=str(config.get("stage_graph") or "?"),
        ceiling=ceiling or 3,
        cancelled=cancelled,
        aborted_at=aborted_at,
        decisions=decisions,
        budget_events=events,
    )


def replay(run: Run, reserve: int) -> dict[str, object]:
    """What this reserve withdraws from this run, and whether the ending moves."""
    taken: list[str] = []
    offered: list[str] = []
    consequential = False
    for decision in run.decisions:
        left = decision.skips_left(run.ceiling)
        if not revisit_would_strand_delivery(left, reserve):
            continue
        for target in decision.revisits_offered:
            offered.append(f"{decision.stage}->{target}@{left}")
        if decision.kind == "revisit":
            taken.append(f"#{decision.index} {decision.stage}->{decision.chose} (left {left})")
            if run.cancelled and run.spent_between(decision.at, run.aborted_at):
                consequential = True
    return {
        "blocked_taken": taken,
        "blocked_offered": offered,
        "still_cancelled": run.cancelled and not consequential,
    }


def table(runs: list[Run], reserves: tuple[int, ...] = CANDIDATE_RESERVES) -> str:
    lines = [
        f"shipped DELIVERY_RESERVE = {DELIVERY_RESERVE}",
        "",
        "run corpus",
        f"{'run':<34} {'graph':<9} {'ceiling':>7} {'decisions':>9} {'revisits':>8} "
        f"{'offers':>6} {'status':>10}",
    ]
    for run in runs:
        revisits = sum(1 for item in run.decisions if item.kind == "revisit")
        offers = sum(len(item.revisits_offered) for item in run.decisions)
        lines.append(
            f"{run.name:<34} {run.topology:<9} {run.ceiling:>7} {len(run.decisions):>9} "
            f"{revisits:>8} {offers:>6} {'cancelled' if run.cancelled else 'completed':>10}"
        )

    lines += ["", "per candidate reserve",
              f"{'reserve':>7} {'run':<34} {'revisits blocked':>16} {'offers withdrawn':>16} "
              f"{'still cancelled':>15}"]
    for reserve in reserves:
        for run in runs:
            result = replay(run, reserve)
            lines.append(
                f"{reserve:>7} {run.name:<34} {len(result['blocked_taken']):>16} "
                f"{len(result['blocked_offered']):>16} "
                f"{('yes' if result['still_cancelled'] else 'no') if run.cancelled else '-':>15}"
            )

    lines += ["", "the rule this project declined to build, priced on the same corpus",
              "  'no backward edge until a deliverable exists' == report_exists on every "
              "revisit edge"]
    forbidden = permitted = taken_forbidden = taken_permitted = 0
    for run in runs:
        for decision in run.decisions:
            if decision.deliverable_written:
                permitted += len(decision.revisits_offered)
                taken_permitted += decision.kind == "revisit"
            else:
                forbidden += len(decision.revisits_offered)
                taken_forbidden += decision.kind == "revisit"
    lines.append(
        f"  offers withdrawn {forbidden} of {forbidden + permitted}; "
        f"revisits withdrawn {taken_forbidden} of {taken_forbidden + taken_permitted}"
    )

    lines += ["", "what each reserve withdraws, named"]
    for reserve in reserves:
        withdrawn: list[str] = []
        for run in runs:
            result = replay(run, reserve)
            for item in result["blocked_taken"]:  # type: ignore[union-attr]
                withdrawn.append(f"  reserve {reserve}: TAKEN    {run.name} {item}")
            for item in result["blocked_offered"]:  # type: ignore[union-attr]
                withdrawn.append(f"  reserve {reserve}: offered  {run.name} {item}")
        lines += withdrawn or [f"  reserve {reserve}: nothing"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("runs", nargs="+", type=Path, help="run directories (…/.autor/<stamp>/)")
    args = parser.parse_args(argv)
    runs = [read_run(path) for path in sorted(args.runs) if (path / "evolution" / "stage_graph.json").is_file()]
    if not runs:
        print("no run directory carried evolution/stage_graph.json", file=sys.stderr)
        return 1
    print(table(runs))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
