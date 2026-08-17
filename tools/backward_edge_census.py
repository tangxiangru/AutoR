"""How many of the thirteen backward edges survive the machinery built around them?

An instrument, not a test. The graph is this project's contribution -- a run navigating
its own topology, with a backward move first-class -- and every mechanism added around it
pushes the same way: ``STOP_SPENDING`` cuts a visit short, ``REALLOCATE`` moves budget
between stages, ``REDIRECT`` returns a routing decision before the agent is asked,
``DELIVERY_RESERVE`` withdraws backward moves outright. Each is separately measured and
separately argued. This prints their *sum*, per edge, as two columns and a reason::

    python3 tools/backward_edge_census.py

Nothing here reimplements a rule. The topology comes from
:data:`~src.stage_graph.REVISIT_EDGES`, the menu from
:meth:`~src.stage_graph.StageGraph.moves` by way of the real
:meth:`~src.router.StageRouter.choose`, and the supervisor's redirect from a real
:class:`~src.supervisor.RunSupervisor`, so a change to any of them changes this output. It
is the same contract ``tools/replay_revisit_reserve.py`` works under. It is also why the
*stack* column is read off the router: ``choose`` computes ``live`` from ``moves`` and
then records ``offered`` off it, and a narrowing between those two points would be
invisible to an instrument that stopped at the graph.

**The two columns.**

``bare``
    :meth:`~src.stage_graph.StageGraph.moves` asked at the edge's source node with
    nothing the manager supplies: no auto-skip pool, no ``--final-stage``, no supervisor.
    Guards still run, because a guard is the *graph* declining a move rather than the
    machinery taking one away, and it is present in both columns.
``stack``
    The same node, the same instant of the same workspace, with everything on: the
    auto-skip pool at ``--skips-left``, ``--final-stage``, and a supervisor asked for a
    ruling at the stage exit -- and read off the router rather than the graph, because
    the router is where a narrowing could hide. The two columns therefore do *not* share
    a reader, on purpose: see :attr:`Stack.through_the_router`.

**The third column is the point.** Where the two disagree, the census names the declared
block kind -- one of :data:`~src.stage_graph.BLOCK_KINDS` -- that the run's own record
carries for that edge. A difference with no kind behind it is printed as ``undeclared``,
which is a capability removed with nothing on the record saying so, and is the shape of
the defect this was written for.

**Why the workspace is furnished by default.** An empty workspace shuts the content guards
on four of the thirteen edges, in both columns, which tells a reader nothing about the
machinery. ``--workspace empty`` is there for the contrast; the furnished state is the one
in which every difference between the columns is attributable.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.router import SUPERVISOR_PREEMPTION, StageRouter  # noqa: E402
from src.stage_graph import (  # noqa: E402
    BLOCK_KINDS,
    DELIVERY_RESERVE,
    REVISIT_EDGES,
    GraphState,
    StageGraph,
    stage_for_slug,
)
from src.stage_cost import (  # noqa: E402
    OUTCOME_AUTO_SKIPPED,
    StageCostMeter,
    append_stage_cost_row,
)
from src.supervisor import REDIRECT, RunSupervisor  # noqa: E402
from src.utils import (  # noqa: E402
    STAGES,
    WRITING_STAGE,
    build_run_paths,
    ensure_run_layout,
    write_text,
)


#: The nodes at least one backward edge leaves from. Derived, so an edge added to the
#: topology is measured without touching this file.
BACKWARD_SOURCES = tuple(sorted({edge.source for edge in REVISIT_EDGES}))

#: ``--max-auto-skips``' shipped default, and the pool an unattended run starts with.
DEFAULT_POOL = 3


@dataclass(frozen=True)
class Stack:
    """Which of the machinery is switched on for one column.

    A record rather than four arguments because the column heading has to be able to say
    what it measured: a table whose two columns differ in an unstated way is a comparison
    a reader cannot check.
    """

    label: str
    #: ``max_auto_skips - len(auto_skipped_stages)``, or ``None`` for a caller with no
    #: pool to declare -- a topology inspected outside a run, or an attended one.
    skips_left: int | None = None
    #: ``--final-stage``, by slug. Empty for a run that asked for the whole pipeline.
    final_stage: str = ""
    #: Whether a :class:`~src.supervisor.RunSupervisor` is asked for a ruling at the
    #: stage exit, and its redirect handed to the router as ``required``.
    supervisor: bool = False
    #: Visits to the node that closed without an approval, written to the cost ledger
    #: before the supervisor is asked. The redirect threshold is
    #: :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT`, so this is how a run
    #: that reached it is reproduced.
    unsettled: int = 0
    routing_mode: str = "auto"
    #: Whether the menu is read off :meth:`~src.router.StageRouter.choose` or off
    #: :meth:`~src.stage_graph.StageGraph.moves`.
    #:
    #: **The two columns must not share this**, and that asymmetry is the whole
    #: measurement rather than an implementation detail. The stack column has to go
    #: through the router, because ``choose`` computes ``live`` from ``moves`` and then
    #: records ``offered`` off it, and three lines between those points would take a
    #: backward move off the agent's menu with nothing on the record. But if the *bare*
    #: column went through the same function, that narrowing would appear in both columns
    #: and cancel out of the difference -- the comparison would read "no change" about a
    #: capability that had just been removed. So the bare column asks the graph, which is
    #: what "the offered set is a function of the graph and the declared block kinds"
    #: means when it is written down as an instrument.
    through_the_router: bool = False


#: The graph on its own, in the same workspace state as the other column.
BARE = Stack(label="bare")


def full_stack(
    *,
    skips_left: int | None = DELIVERY_RESERVE + 1,
    final_stage: str = WRITING_STAGE.slug,
    supervisor: bool = True,
    unsettled: int = 0,
    routing_mode: str = "auto",
) -> Stack:
    """Every mechanism on at once, with the pool and the final stage the caller chose.

    The defaults are the state a ResearchClawBench run walks in: ``--final-stage
    07_writing`` is that harness's own setting, and one unit above
    :data:`~src.stage_graph.DELIVERY_RESERVE` is the smallest pool at which the reserve
    is not already taking every backward move.
    """
    return Stack(
        label="stack",
        skips_left=skips_left,
        final_stage=final_stage,
        supervisor=supervisor,
        unsettled=unsettled,
        routing_mode=routing_mode,
        through_the_router=True,
    )


def furnish(paths) -> None:
    """Write the artifacts the content guards on the backward edges read.

    One file per guard in :data:`~src.stage_graph.GUARDS` that a revisit edge names, plus
    the two the forward guards read at the same nodes. Enough for every backward edge to
    be open on the bare graph, which is the state in which the two columns are comparable.
    """
    write_text(paths.code_dir / "run.py", "print(1)\n")
    write_text(paths.results_dir / "metrics.json", json.dumps({"accuracy": 0.71}))
    write_text(
        paths.experiment_manifest, json.dumps({"result_artifacts": ["metrics.json"]})
    )
    write_text(paths.data_dir / "design.json", json.dumps({"conditions": 2}))
    write_text(paths.experimental_protocol, json.dumps({"baselines": ["random"]}))
    write_text(paths.figures_dir / "figure_1.png", "not really a png")
    write_text(
        paths.hypothesis_manifest,
        json.dumps({"empirical_hypotheses": [{"id": "H1", "statement": "it helps"}]}),
    )
    write_text(paths.report_file, "# Report\n\nBody.\n")


def _required_target(paths, graph: StageGraph, slug: str, final, stack: Stack):
    """The supervisor's redirect for this node, or ``None``.

    Asked exactly the way ``ResearchManager._advance_from`` asks it: the admissible
    forward set is computed off the graph and handed in, so the ruling can only ever name
    a move the guards already left open.
    """
    if not stack.supervisor:
        return None
    node = stage_for_slug(slug)
    if node is None:
        return None
    for _ in range(stack.unsettled):
        meter = StageCostMeter(node)
        meter.note_attempt()
        meter.note_outcome(OUTCOME_AUTO_SKIPPED)
        append_stage_cost_row(paths, meter.close())
    supervisor = RunSupervisor(
        stage_slugs=[stage.slug for stage in STAGES], max_auto_skips=DEFAULT_POOL
    )
    ruling = supervisor.review_stage_exit(
        paths=paths,
        stage_slug=slug,
        admissible_forward=[
            move.target
            for move in graph.moves(paths, slug, GraphState(), final_stage=final)
            if move.admissible and move.edge.kind in {"advance", "finish"}
        ],
    )
    if ruling.kind != REDIRECT:
        return None
    return (ruling.target, ruling.because)


def decide(paths, slug: str, stack: Stack):
    """One real routing decision at *slug* under *stack*.

    Through :meth:`~src.router.StageRouter.choose` with no operator behind it: the router
    computes the menu, records what was offered and what was blocked, and then takes the
    default because there is nobody to ask. That is the whole of what a census needs, and
    it means the offered set measured here is the one an agent would have been shown.
    """
    node = stage_for_slug(slug)
    if node is None:
        raise ValueError(f"{slug!r} is not a stage")
    graph = StageGraph.adaptive()
    state = GraphState()
    final = stage_for_slug(stack.final_stage) if stack.final_stage else None
    required = _required_target(paths, graph, slug, final, stack)
    return StageRouter(None, mode=stack.routing_mode).choose(
        paths=paths,
        stage=node,
        graph=graph,
        state=state,
        final_stage=final,
        skips_left=stack.skips_left,
        required=required,
    )


def offered_backward(paths, slug: str, stack: Stack) -> tuple[set[str], dict[str, str]]:
    """The backward moves offered at *slug*, and the declared kind behind every block.

    Restricted to the targets the topology declares a ``revisit`` edge to, so the forward
    half of the menu -- which is not what the graph's contribution rests on -- does not
    dilute either column.

    Read off the router under a stack and off the graph without one; see
    :attr:`Stack.through_the_router` for why the two columns may not share a reader.
    """
    backward = {edge.target for edge in REVISIT_EDGES if edge.source == slug}
    if stack.through_the_router:
        decision = decide(paths, slug, stack)
        offered = {target for target in decision.offered if target in backward}
        blocked = {
            target: kind for target, kind in decision.blocked.items() if target in backward
        }
        return offered, blocked
    final = stage_for_slug(stack.final_stage) if stack.final_stage else None
    moves = StageGraph.adaptive().moves(
        paths, slug, GraphState(), final_stage=final, skips_left=stack.skips_left
    )
    return (
        {move.target for move in moves if move.admissible and move.target in backward},
        {
            move.target: move.blocked_kind
            for move in moves
            if move.blocked_kind and move.target in backward
        },
    )


def undeclared_narrowings(
    bare: set[str], stack: set[str], blocked: dict[str, str]
) -> list[str]:
    """Backward moves the stack removed with nothing on the record saying so.

    The whole arithmetic of the claim "the offered set is a function of the graph and the
    declared block kinds, and nothing else", in one function so the instrument and the
    gate over it cannot drift, and so a control can hand it a laundered pair and watch it
    fire. A kind outside :data:`~src.stage_graph.BLOCK_KINDS` counts as nothing recorded:
    a heading no reader can interpret is not a declaration.
    """
    return [
        target for target in sorted(bare - stack) if blocked.get(target, "") not in BLOCK_KINDS
    ]


@dataclass(frozen=True)
class Row:
    """One backward edge, in both columns, with the reason for any difference."""

    source: str
    target: str
    bare: bool
    stack: bool
    #: The declared block kind the run's own record carries for this edge under the
    #: stack, or empty. Only meaningful where the columns differ.
    kind: str

    @property
    def undeclared(self) -> bool:
        """A move the stack took off the menu with nothing on the record saying so.

        The one cell in this table that is a defect rather than a measurement.
        """
        return bool(
            undeclared_narrowings(
                {self.target} if self.bare else set(),
                {self.target} if self.stack else set(),
                {self.target: self.kind} if self.kind else {},
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "edge": f"{self.source}->{self.target}",
            "bare": self.bare,
            "stack": self.stack,
            "kind": self.kind,
            "undeclared": self.undeclared,
        }


def census(paths, *, skips_left: int | None = DELIVERY_RESERVE + 1, **stack_kwargs) -> list[Row]:
    """One :class:`Row` per edge of :data:`~src.stage_graph.REVISIT_EDGES`."""
    stack = full_stack(skips_left=skips_left, **stack_kwargs)
    rows: list[Row] = []
    bare_cache: dict[str, tuple[set[str], dict[str, str]]] = {}
    stack_cache: dict[str, tuple[set[str], dict[str, str]]] = {}
    for edge in REVISIT_EDGES:
        if edge.source not in bare_cache:
            bare_cache[edge.source] = offered_backward(paths, edge.source, BARE)
            stack_cache[edge.source] = offered_backward(paths, edge.source, stack)
        bare_offered, _bare_blocked = bare_cache[edge.source]
        stack_offered, stack_blocked = stack_cache[edge.source]
        rows.append(
            Row(
                source=edge.source,
                target=edge.target,
                bare=edge.target in bare_offered,
                stack=edge.target in stack_offered,
                kind=stack_blocked.get(edge.target, ""),
            )
        )
    return rows


def preemptions(paths, *, skips_left: int | None = DELIVERY_RESERVE + 1, **stack_kwargs) -> int:
    """Nodes at which the supervisor returned the decision before the agent was asked.

    The same number :func:`~src.router.routing_summary` publishes as ``preempted`` over a
    finished run, computed here per node of the topology rather than per visit of a walk.
    """
    stack = full_stack(skips_left=skips_left, **stack_kwargs)
    return sum(
        1
        for slug in BACKWARD_SOURCES
        if decide(paths, slug, stack).preempted_by == SUPERVISOR_PREEMPTION
    )


def table(paths, *, skips_left: int | None = DELIVERY_RESERVE + 1, **stack_kwargs) -> str:
    """The census as a human reads it."""
    rows = census(paths, skips_left=skips_left, **stack_kwargs)
    stack = full_stack(skips_left=skips_left, **stack_kwargs)
    lines = [
        f"state: adaptive topology, workspace as given, --final-stage "
        f"{stack.final_stage or '(none)'}, auto-skip pool {stack.skips_left} left, "
        f"supervisor {'on' if stack.supervisor else 'off'} "
        f"({stack.unsettled} unsettled visit(s) seeded)",
        "",
        f"{'edge':<48} {'bare':<6} {'stack':<6} declared kind",
    ]
    for row in rows:
        kind = row.kind or ("undeclared" if row.undeclared else "-")
        lines.append(
            f"{row.source + '->' + row.target:<48} "
            f"{'yes' if row.bare else 'no':<6} {'yes' if row.stack else 'no':<6} {kind}"
        )
    offered_bare = sum(1 for row in rows if row.bare)
    offered_stack = sum(1 for row in rows if row.stack)
    by_kind: dict[str, int] = {}
    for row in rows:
        if row.bare and not row.stack:
            by_kind[row.kind or "undeclared"] = by_kind.get(row.kind or "undeclared", 0) + 1
    lines += [
        "",
        f"{len(rows)} backward edge(s): {offered_bare} offered bare, "
        f"{offered_stack} offered with the full stack",
        "differences by declared kind: "
        + (", ".join(f"{kind} {count}" for kind, count in sorted(by_kind.items())) or "none"),
        f"undeclared narrowings: {sum(1 for row in rows if row.undeclared)}",
        f"nodes whose routing decision the supervisor pre-empted: "
        f"{preemptions(paths, skips_left=skips_left, **stack_kwargs)} of "
        f"{len(BACKWARD_SOURCES)}",
    ]
    unknown = sorted({row.kind for row in rows if row.kind and row.kind not in BLOCK_KINDS})
    if unknown:
        lines.append(f"WARNING: block kinds outside BLOCK_KINDS: {', '.join(unknown)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--skips-left",
        type=int,
        action="append",
        help=(
            "auto-skip units left when the decision is made; repeatable. "
            f"Default: {DELIVERY_RESERVE + 1} and {DELIVERY_RESERVE}."
        ),
    )
    parser.add_argument(
        "--workspace",
        choices=("furnished", "empty"),
        default="furnished",
        help="whether the content guards on the backward edges are satisfied",
    )
    parser.add_argument(
        "--final-stage",
        default=WRITING_STAGE.slug,
        help="the --final-stage the stack column runs under; '' for none",
    )
    parser.add_argument(
        "--unsettled",
        type=int,
        default=0,
        help="visits that closed without an approval, seeded before the supervisor is asked",
    )
    parser.add_argument("--json", action="store_true", help="emit rows as JSON")
    args = parser.parse_args(argv)

    pools = args.skips_left or [DELIVERY_RESERVE + 1, DELIVERY_RESERVE]
    for index, pool in enumerate(pools):
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "runs" / "run_0001")
            ensure_run_layout(paths)
            write_text(paths.user_input, "A census of the backward edges.")
            if args.workspace == "furnished":
                furnish(paths)
            if args.json:
                print(
                    json.dumps(
                        {
                            "skips_left": pool,
                            "workspace": args.workspace,
                            "rows": [
                                row.to_dict()
                                for row in census(
                                    paths,
                                    skips_left=pool,
                                    final_stage=args.final_stage,
                                    unsettled=args.unsettled,
                                )
                            ],
                        }
                    )
                )
                continue
            if index:
                print()
            print(
                table(
                    paths,
                    skips_left=pool,
                    final_stage=args.final_stage,
                    unsettled=args.unsettled,
                )
            )
    return 0


if __name__ == "__main__":  # pragma: no cover - a script
    raise SystemExit(main())
