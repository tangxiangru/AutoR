"""The eight stages as a directed graph the run navigates, instead of a list it walks.

Real research is not a pipeline. Analysis finds that the experiment answered a
different question than the one that was asked; writing finds that a claim has no
result behind it; a result nobody expected is worth more than the one that was
planned. Every one of those is a *backward* move, and a linear stage list has no
way to express one. AutoR's loop could only refine the current stage or abort, so
the system's response to "Stage 06 shows the design was wrong" was to write up the
wrong design more carefully.

This module makes the topology explicit. Nodes are stages; edges are the moves
that are allowed between them; after each approved stage the run chooses an edge.
The default topology is exactly the old sequence — 01→02→…→08, one edge out of
each node — so a run that does not ask for anything else behaves as it always did.
The linear pipeline is not replaced, it is one path through the graph.

**Why the agent does not simply decide.**

An agent choosing its own next step chooses the short path to the deliverable.
The terminal node is where the reward is, and every autonomous research system
that has been evaluated drifts toward writing up early. So the choice here is a
two-part thing, and the parts are not both the agent's:

1. AutoR computes which moves are *admissible*, by evaluating each edge's guard
   against artifacts on disk. An edge into ``07_writing`` requires a frozen
   preregistration and a verdict on every hypothesis. The agent cannot route
   around a gate, because a gated edge is not on the menu.
2. The agent chooses among the admissible moves and says why. Its reason is
   recorded next to the measurement that made the move admissible.

The backward edges are the reason the graph exists, so they are cheap to take and
expensive to take *twice for the same reason*: a node carries a visit budget, and
:func:`admissible_moves` withdraws a revisit whose justification has not changed
since the last time it was taken. A loop that keeps returning to Stage 05 with the
same complaint is not iterating, it is stuck, and the difference is measurable.

The path is recorded in ``evolution/stage_graph.json`` — every visit, the move out
of it, whether the agent's choice matched what AutoR would have picked, and the
rubric total at the time. :mod:`src.archive` reads those across runs to learn
which edges actually pay, which is what lets the topology improve rather than just
exist.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .utils import (
    FIGURE_SUFFIXES,
    MACHINE_DATA_SUFFIXES,
    RESULT_SUFFIXES,
    RunPaths,
    StageSpec,
    STAGES,
    _count_files_with_suffixes,
    read_text,
    write_text,
)


#: Terminal target. Not a stage — a node the run can move to and stop.
FINISH = "finish"

#: How many stage executions a graph run may make before it is stopped, regardless
#: of visit budgets. A cap on the whole walk, not on any node: three stages each
#: revisited twice is a productive run, and the same total spent bouncing between
#: two nodes is not, but only the global number bounds the cost of either.
DEFAULT_MAX_STEPS = 20

#: Times a single stage may be entered. Two revisits of Stage 05 is a run that
#: took its own analysis seriously; a fourth is a loop.
DEFAULT_MAX_VISITS = 3


# ----------------------------------------------------------------------------
# Guards
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class GuardResult:
    ok: bool
    #: Why the edge is or is not available, in the words the router will show the
    #: agent. A guard that fails without saying what would satisfy it turns a
    #: routing decision into a guess.
    reason: str


GuardFn = Callable[[RunPaths, "GraphState"], GuardResult]


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _guard_always(paths: RunPaths, state: "GraphState") -> GuardResult:
    return GuardResult(True, "no precondition")


def _guard_design_artifacts(paths: RunPaths, state: "GraphState") -> GuardResult:
    count = _count_files_with_suffixes(paths.data_dir, MACHINE_DATA_SUFFIXES)
    protocol = _load_json(paths.experimental_protocol)
    has_protocol = isinstance(protocol, dict) and bool(protocol.get("baselines"))
    if count and has_protocol:
        return GuardResult(True, f"{count} machine-readable design artifact(s) and a declared protocol")
    missing = []
    if not count:
        missing.append("machine-readable artifacts under workspace/data")
    if not has_protocol:
        missing.append("workspace/notes/experimental_protocol.json declaring the baselines")
    return GuardResult(False, "the study design has produced no " + " and no ".join(missing))


def _guard_runnable_code(paths: RunPaths, state: "GraphState") -> GuardResult:
    count = _count_files_with_suffixes(
        paths.code_dir, {".py", ".sh", ".r", ".jl", ".ipynb", ".cpp", ".rs", ".go"}
    )
    if count:
        return GuardResult(True, f"{count} executable file(s) under workspace/code")
    return GuardResult(False, "there is nothing to run: workspace/code holds no executable file")


def _guard_results_exist(paths: RunPaths, state: "GraphState") -> GuardResult:
    """Results on disk, and the manifest that indexes them.

    ``result_artifacts`` is the key :mod:`src.experiment_manifest` actually writes.
    An earlier version of this guard looked for ``experiments``, which nothing in
    AutoR has ever produced — so the guard could not be satisfied by any run, and
    the forward move out of Stage 05 was permanently closed. A precondition no real
    run can meet is not a strict gate, it is a broken one.
    """
    count = _count_files_with_suffixes(paths.results_dir, RESULT_SUFFIXES)
    manifest = _load_json(paths.experiment_manifest)
    indexed = manifest.get("result_artifacts") if isinstance(manifest, dict) else None
    if count and indexed:
        return GuardResult(
            True, f"{count} result artifact(s), {len(indexed)} indexed in the experiment manifest"
        )
    if not count:
        return GuardResult(
            False, "no experiment has produced a machine-readable result under workspace/results"
        )
    return GuardResult(
        False,
        "results exist but experiment_manifest.json indexes none of them, so nothing "
        "downstream can tell which experiment produced what",
    )


def _guard_validity_chain(paths: RunPaths, state: "GraphState") -> GuardResult:
    """The one gate a self-routing agent must not be able to talk its way past.

    Writing before the hypotheses are adjudicated is how a manuscript ends up
    claiming a result the run never established. The check is over artifacts, not
    over the agent's assessment of its own readiness.
    """
    prereg = _load_json(paths.preregistration)
    hypotheses = prereg.get("hypotheses") if isinstance(prereg, dict) else None
    if not hypotheses:
        return GuardResult(False, "the hypotheses were never frozen; there is nothing to write up against")

    expected = {
        str(item.get("id") or "").strip()
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("type") or "") == "empirical"
    }
    outcomes = _load_json(paths.hypothesis_outcomes)
    recorded = {
        str(item.get("id") or "").strip()
        for item in (outcomes.get("outcomes", []) if isinstance(outcomes, dict) else [])
        if isinstance(item, dict) and str(item.get("verdict") or "").strip()
    }
    unadjudicated = sorted(expected - recorded)
    if unadjudicated:
        return GuardResult(
            False,
            "these preregistered hypotheses have no verdict yet: " + ", ".join(unadjudicated),
        )
    figures = _count_files_with_suffixes(paths.figures_dir, FIGURE_SUFFIXES)
    if not figures:
        return GuardResult(False, "the analysis produced no figure under workspace/figures")
    return GuardResult(True, f"every hypothesis is adjudicated and {figures} figure(s) exist")


def _guard_report_exists(paths: RunPaths, state: "GraphState") -> GuardResult:
    if paths.report_file.exists() or _count_files_with_suffixes(paths.writing_dir, {".tex", ".md"}):
        return GuardResult(True, "a written deliverable exists")
    return GuardResult(False, "no report or manuscript source has been written")


def _guard_round_abandoned(paths: RunPaths, state: "GraphState") -> GuardResult:
    """Open only when the closed round concluded the question cannot be answered.

    :mod:`src.research_rounds` lets a round end in ``abandon`` — the resources
    available cannot settle the question — and until this edge existed the decision
    had nowhere to go. `resume_stage_slug_for("abandon")` returns None, so the walk
    advanced to Stage 07, `validate_round_decision` refused it there, and the stage
    burned its whole retry budget. Measured on a scripted run: **10 operator calls
    at Stage 07**, all discarded, and the run recorded as `cancelled` —
    indistinguishable from a crash. The most scientifically honest outcome a run can
    reach was its most expensive and its worst-labelled.
    """
    from .research_rounds import latest_round

    # Scoped to *this visit*, not to the run.
    #
    # `research_rounds.json` is run-global and nothing invalidates it — a rollback
    # does not touch it, and `_skip_stage` never closes a round at all. Read
    # globally, an abandonment recorded once would govern every later arrival at
    # Stage 06 forever: an operator who disagreed, rolled back to Stage 03 and
    # re-ran into a Stage 06 that exhausted its retries would find the walk
    # terminating on a decision that visit never made — and, because a live
    # conditional terminal preempts every other move, with no way for the agent to
    # go anywhere else either.
    #
    # Every other guard here reads stage artifacts, which a rollback invalidates.
    # This one reads a ledger, so the scoping has to be explicit: the closing round
    # is stamped on the `Visit`, and the guard asks whether *this* traversal closed
    # a round that concluded abandon.
    visit = state.path[-1] if state.path else None
    closed = visit.closed_round if visit is not None else 0
    if not closed:
        return GuardResult(False, "this visit closed no research round")

    final = latest_round(paths)
    if final is not None and final.number == closed and final.decision == "abandon":
        return GuardResult(
            True,
            f"round {final.number} concluded the question cannot be answered: {final.rationale}",
        )
    return GuardResult(False, f"round {closed} did not conclude `abandon`")


def _guard_has_hypotheses(paths: RunPaths, state: "GraphState") -> GuardResult:
    manifest = _load_json(paths.hypothesis_manifest)
    if isinstance(manifest, dict) and manifest.get("empirical_hypotheses"):
        return GuardResult(True, "typed hypotheses are on record")
    return GuardResult(False, "no empirical hypothesis has been stated yet")


GUARDS: dict[str, GuardFn] = {
    "always": _guard_always,
    "design_artifacts": _guard_design_artifacts,
    "runnable_code": _guard_runnable_code,
    "results_exist": _guard_results_exist,
    "validity_chain": _guard_validity_chain,
    "report_exists": _guard_report_exists,
    "has_hypotheses": _guard_has_hypotheses,
    "round_abandoned": _guard_round_abandoned,
}


# ----------------------------------------------------------------------------
# Edges
# ----------------------------------------------------------------------------


#: ``advance`` moves forward, ``revisit`` goes back to redo work in the light of
#: something later, ``finish`` ends the run. The kind is not decoration: a revisit
#: is budgeted and justified differently from an advance, and the archive learns
#: their payoffs separately — so an edge declared with a kind nothing handles is
#: refused at construction rather than silently treated as an advance.
EDGE_KINDS = ("advance", "revisit", "finish")


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str
    #: Shown to the router. Says what condition in the *research* makes this the
    #: right move — not what the target stage does, which the agent already knows.
    rationale: str
    guard: str = "always"
    #: Deterministic tie-break, low first. Also the fallback order when routing is
    #: off or the agent's choice is refused, which is why the advance edge out of
    #: every node is priority 0: the fallback through the graph is the old pipeline.
    priority: int = 0

    def __post_init__(self) -> None:
        if self.kind not in EDGE_KINDS:
            raise ValueError(
                f"Edge {self.source}->{self.target} has kind {self.kind!r}; "
                f"expected one of {', '.join(EDGE_KINDS)}."
            )
        if self.guard not in GUARDS:
            raise ValueError(
                f"Edge {self.source}->{self.target} names guard {self.guard!r}, which is not "
                f"registered. A guard that does not resolve would silently pass."
            )

    def guard_fn(self) -> GuardFn:
        return GUARDS[self.guard]


#: Preconditions on the forward moves. They apply in the adaptive topology, where
#: the run is choosing between edges and a guard is what stops it choosing the one
#: that skips the work. They deliberately do **not** apply to the linear topology:
#: there is one edge out of each node there, so a guard could only ever halt the
#: run, and the condition it would halt on is already a stage validation error with
#: a better message. Two gates over one condition is one gate too many, and the one
#: that fires second is the one nobody maintains.
_ADVANCE_GUARDS = {
    "03_study_design": "has_hypotheses",
    "04_implementation": "design_artifacts",
    "05_experimentation": "runnable_code",
    "06_analysis": "results_exist",
    "07_writing": "validity_chain",
    "08_dissemination": "report_exists",
}


#: Per-target overrides for the forward priority. Empty, and it should stay that
#: way unless something can be shown to depend on it: a live conditional terminal
#: preempts every other move at its node, so priority never decides between a
#: terminal and an advance, and every node has exactly one advance. An entry here
#: that changes no behaviour is a constant a reader will assume is load-bearing.
_ADVANCE_PRIORITIES: dict[str, int] = {}

#: Terminals other than "the run produced what it set out to produce". Carried by
#: both topologies: refusing to write up an abandoned round is a correctness
#: property, not a routing preference, and `--stage-graph linear` asks for a strict
#: sequence of *stages*, not for the run to keep going after it has said it cannot.
TERMINAL_EDGES: tuple["Edge", ...] = ()  # populated below, after Edge is defined


def _advance_edges(*, guarded: bool) -> list[Edge]:
    edges: list[Edge] = []
    guards = _ADVANCE_GUARDS if guarded else {}
    for index, stage in enumerate(STAGES):
        target = STAGES[index + 1].slug if index + 1 < len(STAGES) else FINISH
        edges.append(
            Edge(
                source=stage.slug,
                target=target,
                kind="advance" if target != FINISH else "finish",
                rationale=(
                    "This stage is complete and the next one is the natural continuation."
                    if target != FINISH
                    else "The run has produced everything it set out to produce."
                ),
                guard=guards.get(target, "always"),
                priority=_ADVANCE_PRIORITIES.get(target, 0),
            )
        )
    return edges


TERMINAL_EDGES = (
    Edge(
        "06_analysis", FINISH, "finish",
        "The round concluded that the question cannot be answered with the resources "
        "available. Recording that and stopping is the result; writing up a manuscript "
        "for a question the run just said it could not settle is not.",
        guard="round_abandoned", priority=0,
    ),
)


#: The moves a linear list cannot express. Each one exists because a specific
#: discovery at the source stage invalidates work at the target — which is the
#: normal way research goes, not an error path.
REVISIT_EDGES: tuple[Edge, ...] = (
    Edge(
        "04_implementation", "03_study_design", "revisit",
        "Building it showed the design is not executable as specified — the metric cannot be "
        "computed, the dataset does not contain what the plan assumed, or the budget is off by "
        "an order of magnitude.",
        guard="always", priority=2,
    ),
    Edge(
        "05_experimentation", "04_implementation", "revisit",
        "The experiment could not run, or ran and produced something the implementation is "
        "clearly responsible for.",
        guard="always", priority=2,
    ),
    Edge(
        "05_experimentation", "03_study_design", "revisit",
        "Running it showed the comparison does not answer the question — the baseline is not "
        "competent, or the measurement cannot distinguish the hypotheses.",
        guard="always", priority=3,
    ),
    Edge(
        "06_analysis", "05_experimentation", "revisit",
        "The results are real but insufficient to decide a hypothesis: too few repeats, a "
        "missing ablation, a condition that was never run.",
        guard="runnable_code", priority=1,
    ),
    Edge(
        "06_analysis", "03_study_design", "revisit",
        "The analysis exposed a design flaw the results cannot repair — a confound, a leak, or "
        "a comparison that was never fair.",
        guard="always", priority=3,
    ),
    Edge(
        "06_analysis", "02_hypothesis_generation", "revisit",
        "The evidence refutes the hypotheses and points somewhere specific. Recording the "
        "refutation and stating the new hypothesis is a result; quietly rewriting the old one "
        "is not, and the amendment is logged either way.",
        guard="always", priority=4,
    ),
    Edge(
        "07_writing", "06_analysis", "revisit",
        "Writing it up showed a claim has no analysis behind it, or a figure does not show what "
        "the text says it shows.",
        guard="results_exist", priority=1,
    ),
    Edge(
        "07_writing", "05_experimentation", "revisit",
        "Writing it up showed the paper needs a result that was never produced.",
        guard="runnable_code", priority=3,
    ),
    Edge(
        "07_writing", "01_literature_survey", "revisit",
        "The finding turns out to relate to work the survey missed, and the contribution cannot "
        "be stated honestly without it.",
        guard="always", priority=4,
    ),
    Edge(
        "08_dissemination", "07_writing", "revisit",
        "Packaging it showed the deliverable is not what a reader would need.",
        guard="always", priority=2,
    ),
)


# ----------------------------------------------------------------------------
# State
# ----------------------------------------------------------------------------


@dataclass
class Visit:
    stage: str
    entered_at: str
    #: The targets that were live at the moment of choosing, and why the others
    #: were not.
    #:
    #: Recorded because it is the difference between "this edge was taken" and
    #: "this edge was offered and taken". Without it the archive's control arm pools
    #: four unrelated states — the guard was shut, `--final-stage` pruned the edge,
    #: the visit budget was spent, or the run was on a topology where the edge does
    #: not exist — and calls all of them "did not take it". The guards read the same
    #: disk predicates the rubric scores, so that pooling makes the guard a selection
    #: mechanism on the outcome, which is the textbook way to measure a difference
    #: that is not there.
    #:
    #: It costs nothing: `StageRouter.choose` computes both lists and discards them.
    #: And it cannot be recovered afterwards — re-evaluating a guard needs the
    #: workspace as it was at that moment, which the next stage has already changed.
    offered: tuple[str, ...] = ()
    blocked: dict[str, str] = field(default_factory=dict)
    #: True when the move did not go through the router at all: a `/back`, a rollback
    #: after retry exhaustion, or a research-round decision. These had no choice set,
    #: and an estimator that counted them as decisions where nothing else was on
    #: offer would be reading an operator's intervention as evidence about an edge.
    bypassed: bool = False
    #: The research round this visit closed, if it closed one. Zero otherwise.
    #: What makes the abandonment guard a statement about this traversal rather than
    #: about the run's whole history.
    closed_round: int = 0
    #: Filled in when the run leaves. An unfinished visit is the record of where a
    #: run was interrupted, which is what a resume needs.
    left_at: str = ""
    chose: str = ""
    kind: str = ""
    reason: str = ""
    #: What AutoR would have chosen with no agent involved. Kept beside the actual
    #: choice so a disagreement is visible: the archive learns from the cases where
    #: the router departed from the pipeline and it paid off, and from where it did
    #: not, and neither is recoverable if only the taken edge is stored.
    default_choice: str = ""
    agent_directed: bool = False
    score_total: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "entered_at": self.entered_at,
            "left_at": self.left_at,
            "chose": self.chose,
            "kind": self.kind,
            "reason": self.reason,
            "default_choice": self.default_choice,
            "agent_directed": self.agent_directed,
            "score_total": self.score_total,
            "offered": list(self.offered),
            "blocked": dict(self.blocked),
            "bypassed": self.bypassed,
            "closed_round": self.closed_round,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Visit":
        total = payload.get("score_total")
        return cls(
            stage=str(payload.get("stage") or ""),
            entered_at=str(payload.get("entered_at") or ""),
            left_at=str(payload.get("left_at") or ""),
            chose=str(payload.get("chose") or ""),
            kind=str(payload.get("kind") or ""),
            reason=str(payload.get("reason") or ""),
            default_choice=str(payload.get("default_choice") or ""),
            agent_directed=bool(payload.get("agent_directed")),
            score_total=float(total) if isinstance(total, (int, float)) else None,
            # Absent means empty, so a stage_graph.json written before these fields
            # existed still loads — as a visit with no recorded choice set, which is
            # exactly what it is and what every estimator should exclude.
            offered=tuple(str(item) for item in payload.get("offered", []) if str(item)),
            blocked={
                str(k): str(v) for k, v in (payload.get("blocked") or {}).items() if str(k)
            },
            bypassed=bool(payload.get("bypassed")),
            closed_round=int(payload.get("closed_round") or 0),
        )


@dataclass
class GraphState:
    path: list[Visit] = field(default_factory=list)
    max_steps: int = DEFAULT_MAX_STEPS
    max_visits: int = DEFAULT_MAX_VISITS
    #: Set when the walk stopped for a reason other than reaching ``finish``.
    halted_because: str = ""
    #: Which kind of stop it was, from :data:`BLOCK_KINDS`, or ``"none"`` when the
    #: node simply had no edge.
    #:
    #: The reason alone was not enough, and being a string nobody could branch on is
    #: why it went unread: `--final-stage` stopping a run is the caller getting what
    #: they asked for, and a step budget stopping one is a run that did not finish.
    #: Both wrote a sentence into ``halted_because`` and both came out of
    #: ``_complete_run`` as "All stages approved."
    halted_kind: str = ""

    @property
    def steps(self) -> int:
        return len(self.path)

    def visits(self, slug: str) -> int:
        return sum(1 for visit in self.path if visit.stage == slug)

    def revisit_reasons(self, slug: str) -> list[str]:
        """Why the run entered ``slug`` before, normalised for comparison."""
        return [
            " ".join(visit.reason.lower().split())
            for visit in self.path
            if visit.chose == slug and visit.reason
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": [visit.to_dict() for visit in self.path],
            "max_steps": self.max_steps,
            "max_visits": self.max_visits,
            "halted_because": self.halted_because,
            "halted_kind": self.halted_kind,
            "route": " -> ".join(visit.stage for visit in self.path),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GraphState":
        return cls(
            path=[Visit.from_dict(item) for item in payload.get("path", []) if isinstance(item, Mapping)],
            max_steps=int(payload.get("max_steps") or DEFAULT_MAX_STEPS),
            max_visits=int(payload.get("max_visits") or DEFAULT_MAX_VISITS),
            halted_because=str(payload.get("halted_because") or ""),
            halted_kind=str(payload.get("halted_kind") or ""),
        )


def state_file(paths: RunPaths) -> Path:
    return paths.evolution_dir / "stage_graph.json"


def load_graph_state(paths: RunPaths, *, max_steps: int | None = None, max_visits: int | None = None) -> GraphState:
    payload = _load_json(state_file(paths))
    state = GraphState.from_dict(payload) if isinstance(payload, Mapping) else GraphState()
    if max_steps is not None:
        state.max_steps = max_steps
    if max_visits is not None:
        state.max_visits = max_visits
    return state


def save_graph_state(paths: RunPaths, state: GraphState) -> None:
    write_text(state_file(paths), json.dumps(state.to_dict(), indent=2, ensure_ascii=False))


# ----------------------------------------------------------------------------
# The graph
# ----------------------------------------------------------------------------


#: Why a move is unavailable. The distinction decides whether the walk may fall
#: through it: a guard is a statement about the *research* and can be overridden as
#: a last resort, while a budget is a statement about the *run* and cannot.
#: ``concluded`` is neither — the run has already decided to stop, and the move is
#: not unavailable so much as moot. ``pruned`` is the caller's own ``--final-stage``:
#: not a fact about the research at all, and the one kind that means the walk is
#: finished rather than stuck.
BLOCK_KINDS = ("guard", "visits", "steps", "concluded", "pruned")


@dataclass(frozen=True)
class Move:
    """An edge the run is allowed to take right now, and why."""

    edge: Edge
    guard: GuardResult
    #: Set when the edge exists but may not be taken. The edge is still shown to
    #: the router with this attached: an agent that can see *why* Stage 07 is
    #: closed will route to what opens it, whereas an agent shown a shorter menu
    #: will pick the wrong item off it and never know what it missed.
    blocked_because: str = ""
    blocked_kind: str = ""
    #: Taken because nothing else was available, with its guard still failing.
    last_resort: bool = False

    @property
    def admissible(self) -> bool:
        return not self.blocked_because

    @property
    def target(self) -> str:
        return self.edge.target


class StageGraph:
    """Nodes, edges, and the rule for which edges are live given what is on disk."""

    def __init__(self, edges: Sequence[Edge], *, name: str = "linear") -> None:
        self.name = name
        self.edges = tuple(edges)
        self._by_source: dict[str, list[Edge]] = {}
        for edge in self.edges:
            self._by_source.setdefault(edge.source, []).append(edge)
        for group in self._by_source.values():
            group.sort(key=lambda item: (item.priority, item.target))

    # -- construction --------------------------------------------------------

    @classmethod
    def linear(cls) -> "StageGraph":
        """The topology AutoR has always had: one edge out of each stage.

        Kept as a real graph rather than a special case, so the default run and the
        adaptive run go through the same engine. A bug in the walk shows up in both,
        which is the only way the default path stays trustworthy once it stops being
        the only path.
        """
        return cls([*_advance_edges(guarded=False), *TERMINAL_EDGES], name="linear")

    @classmethod
    def adaptive(cls) -> "StageGraph":
        """The advance edges plus every backward move that has a research meaning."""
        return cls([*_advance_edges(guarded=True), *TERMINAL_EDGES, *REVISIT_EDGES], name="adaptive")

    @classmethod
    def named(cls, name: str) -> "StageGraph":
        if name == "adaptive":
            return cls.adaptive()
        if name == "linear":
            return cls.linear()
        raise ValueError(f"Unknown stage graph topology: {name!r}. Expected 'linear' or 'adaptive'.")

    # -- navigation ----------------------------------------------------------

    def out_edges(self, slug: str) -> list[Edge]:
        return list(self._by_source.get(slug, []))

    def moves(self, paths: RunPaths, slug: str, state: GraphState, *, final_stage: StageSpec | None = None) -> list[Move]:
        """Every edge out of ``slug``, each labelled admissible or blocked.

        Blocked edges are returned rather than filtered out. The router needs them:
        the useful thing to tell an agent is not "you may go to 06" but "07 is
        closed because H2 has no verdict", which is a reason to go to 06.
        """
        results: list[Move] = []
        for edge in self.out_edges(slug):
            # `--final-stage` used to drop the edge from the list entirely. That made
            # the node look like one with no forward move at all, and `default_move`
            # fell through to the backward edges — so on the adaptive topology, which
            # is the default, `--final-stage 07` sent the run back to Stage 06 and
            # kept going until a budget stopped it. Measured at every final stage:
            # 05 -> 04, 06 -> 05, 07 -> 06, all revisits. Recorded as a block instead,
            # the node still has its forward move and the walk can see that the
            # reason it cannot be taken is the caller's, not the research's.
            if final_stage is not None and edge.target != FINISH:
                target_stage = stage_for_slug(edge.target)
                if target_stage is not None and target_stage.number > final_stage.number:
                    results.append(
                        Move(
                            edge,
                            GuardResult(True, "not evaluated"),
                            f"`{edge.target}` is past the requested final stage "
                            f"`{final_stage.slug}`",
                            "pruned",
                        )
                    )
                    continue

            guard = edge.guard_fn()(paths, state)
            blocked, kind = "", ""
            if not guard.ok:
                blocked, kind = guard.reason, "guard"
            elif edge.target != FINISH and state.visits(edge.target) >= state.max_visits:
                blocked, kind = (
                    f"{edge.target} has already been entered {state.visits(edge.target)} times, "
                    f"which is the per-stage limit",
                    "visits",
                )
            elif state.steps >= state.max_steps:
                blocked, kind = (
                    f"the run has taken {state.steps} steps, which is the limit for this graph",
                    "steps",
                )
            results.append(Move(edge, guard, blocked, kind))

        return _preempted_by_a_conclusion(results)

    def admissible_moves(self, paths: RunPaths, slug: str, state: GraphState, **kwargs: Any) -> list[Move]:
        return [move for move in self.moves(paths, slug, state, **kwargs) if move.admissible]

    def default_move(self, paths: RunPaths, slug: str, state: GraphState, **kwargs: Any) -> Move | None:
        """What AutoR takes when nothing chooses: the lowest-priority live edge.

        **The default is always the forward edge.** Not merely the lowest-priority
        live one: a backward move is only ever correct as a deliberate choice with a
        reason attached, and the router refuses an unreasoned one for exactly that
        reason. A default that could silently reverse the run would be able to do
        what no explicit decision is allowed to do.

        **When nothing is live, the forward edge is taken anyway.** A guard is a
        routing preference, not a correctness gate — the correctness gate is the
        stage's own validation, which is unchanged and still refuses a Stage 07
        that writes up unadjudicated hypotheses. Treating a failed guard as an
        absolute barrier would mean a run that genuinely cannot satisfy it bounces
        between backward edges until its visit budget runs out and then halts with
        nothing, where the linear pipeline would have produced a deliverable and
        failed the stage gate honestly. Halting is not the safer outcome; it is the
        same refusal with the evidence thrown away.

        A budget block is different and is never overridden: a guard says something
        about the research, a budget says something about the run, and the run
        stopping is exactly what a budget is for.
        """
        moves = self.moves(paths, slug, state, **kwargs)
        by_rank = lambda move: (move.edge.priority, move.edge.target)  # noqa: E731
        forward = [move for move in moves if move.edge.kind in {"advance", "finish"}]

        live_forward = [move for move in forward if move.admissible]
        if live_forward:
            return min(live_forward, key=by_rank)

        # A budget said stop, or the caller did. Unlike a guard, neither is a
        # statement about the research, and there is nothing to route around.
        if any(move.blocked_kind in {"steps", "visits", "pruned"} for move in forward):
            return None

        # Forward is shut by a guard, and the default does **not** go back.
        #
        # It is tempting: the backward edges exist for exactly this, and the guard
        # message reads like a reason. It is wrong, and observably so. Stage 04's
        # forward guard fails when `workspace/code` holds nothing executable; the
        # only backward edge out of 04 goes to 03, and study design is not the stage
        # that writes code. The default would send the run somewhere that cannot fix
        # the thing that blocked it, attach the guard's message as though it were a
        # justification, and do it again next time round.
        #
        # Which backward edge addresses a given block is a judgement about the
        # research, not a computation over the graph. That is the agent's call, and
        # the whole arrangement here is that AutoR decides what is *possible* and the
        # agent decides what is *sensible*. So the default advances with the
        # precondition unmet and lets the stage's own validation — unchanged, and
        # still refusing a Stage 07 that writes up unadjudicated hypotheses — be the
        # correctness gate it always was. A guard is a routing preference; the gate
        # is the gate.
        # Only an `advance` may be taken as a last resort. A `finish` edge is a
        # *conclusion* — "the run produced what it set out to produce", or "the
        # question cannot be answered" — and a conclusion reached because nothing
        # else was available is not one the run is entitled to. Without this, a node
        # whose every forward move is shut could fall through to the abandonment
        # terminal and record that the run had decided to give up, which it had not.
        fallback = [move for move in forward if move.edge.kind == "advance"]
        if fallback:
            return replace(min(fallback, key=by_rank), last_resort=True)

        # No forward edge is declared here at all. Only reachable on a hand-built
        # topology; the shipped ones give every node one.
        live = [move for move in moves if move.admissible]
        return min(live, key=by_rank) if live else None

    def repeats_a_previous_reason(self, state: GraphState, target: str, reason: str) -> bool:
        """Whether this exact justification has already sent the run to ``target``.

        A revisit is worth taking when something has been learned. Returning to
        Stage 05 for the third time because "more repeats are needed" is the same
        move, and the graph is not going to reach a different place by making it
        again.
        """
        normalized = " ".join(reason.lower().split())
        if not normalized:
            return False
        return normalized in state.revisit_reasons(target)

    def describe_for_prompt(self, moves: Sequence[Move]) -> str:
        lines = ["| Move | Target | Kind | Available | Why this move exists |", "| --- | --- | --- | --- | --- |"]
        for index, move in enumerate(moves, start=1):
            availability = "yes" if move.admissible else f"**no** — {move.blocked_because}"
            lines.append(
                f"| {index} | `{move.edge.target}` | {move.edge.kind} | {availability} | "
                f"{move.edge.rationale} |"
            )
        return "\n".join(lines)


def _preempted_by_a_conclusion(moves: list[Move]) -> list[Move]:
    """A live conditional terminal is the only move at its node.

    A terminal whose guard is not ``always`` is not an exit that happens to be
    available — it is a conclusion the run reached and recorded, and a conclusion is
    not one option among several. Without this the abandonment terminal is merely
    the *default*, and the default is only what happens when nobody is asked.
    Measured on the shipped defaults (`adaptive` + `routing auto`): a run whose
    round concluded the question cannot be answered still offers five live moves at
    Stage 06, so the backend is consulted, and a backend answering
    ``{"target": "07_writing", "reason": "the refutation is the contribution"}``
    gets it — `agent_directed=True`, no refusal. The run talks itself out of its own
    finding.

    A person may still overrule it. `/back` and `--rollback-stage` do not go through
    the router at all, which is the right place for "the operator disagrees with the
    run's own conclusion" to live.
    """
    conclusion = next(
        (
            move
            for move in moves
            if move.edge.kind == "finish" and move.edge.guard != "always" and move.admissible
        ),
        None,
    )
    if conclusion is None:
        return moves
    return [
        move
        if move is conclusion
        else replace(
            move,
            blocked_because=(
                f"the run has concluded: {conclusion.guard.reason}. Recording that and stopping "
                "is the result; continuing would contradict the run's own record."
            ),
            blocked_kind="concluded",
        )
        for move in moves
    ]


def stage_for_slug(slug: str) -> StageSpec | None:
    return next((stage for stage in STAGES if stage.slug == slug), None)


def enter(paths: RunPaths, state: GraphState, stage: StageSpec) -> Visit:
    visit = Visit(stage=stage.slug, entered_at=_now())
    state.path.append(visit)
    save_graph_state(paths, state)
    return visit


def leave(
    paths: RunPaths,
    state: GraphState,
    *,
    chose: str,
    kind: str,
    reason: str,
    default_choice: str,
    agent_directed: bool,
    score_total: float | None,
    offered: "Sequence[str]" = (),
    blocked: Mapping[str, str] | None = None,
    bypassed: bool = False,
) -> None:
    if not state.path:
        return
    visit = state.path[-1]
    visit.left_at = _now()
    visit.chose = chose
    visit.kind = kind
    visit.reason = reason
    visit.default_choice = default_choice
    visit.agent_directed = agent_directed
    visit.score_total = score_total
    visit.offered = tuple(offered)
    visit.blocked = dict(blocked or {})
    visit.bypassed = bypassed
    save_graph_state(paths, state)


def format_route(state: GraphState) -> str:
    """The path as a human reads it, with the backward moves marked."""
    if not state.path:
        return "(no stages run)"
    parts: list[str] = []
    for visit in state.path:
        marker = " ↩" if visit.kind == "revisit" else ""
        parts.append(f"{visit.stage}{marker}")
    tail = " → finish" if state.path[-1].chose == FINISH else ""
    return " → ".join(parts) + tail


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
