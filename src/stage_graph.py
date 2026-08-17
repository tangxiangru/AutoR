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

They are cheap, not free, and :class:`WalkBudget` is what says so before the wall
rather than at it. A block is what a budget looks like once it has already bitten;
:func:`describe_budget_for_prompt` and :func:`worst_case` are the same arithmetic
addressed to the party about to spend — how much of the walk is left, how much of
this node is left, how much of the unattended auto-skip allowance is left, and how
much of each the move under consideration can take. Neither refuses anything: the
refusals are :meth:`StageGraph.moves`'s and stay there.

The path is recorded in ``evolution/stage_graph.json`` — every visit, the move out
of it, whether the agent's choice matched what AutoR would have picked, and the
rubric total at the time. :mod:`src.archive` reads those across runs to learn
which edges actually pay, which is what lets the topology improve rather than just
exist. :func:`block_census` sums the same record the other way, per edge rather
than per visit, so a finished run can say which moves it was ever offered and what
shut the rest — the walk, and not only the path through it.
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


def _load_json_if_live(paths: RunPaths, path: Path) -> Any:
    """``_load_json``, except a file a rollback withdrew reads as absent.

    For the gates that read one named document rather than counting a directory. The
    ``preregistration`` is deliberately not read through this: it has its own
    invalidation path in :mod:`src.preregistration`, stamped outside the workspace, and
    two mechanisms deciding whether one frozen document counts is how they drift apart.
    """

    from .provenance import path_is_live

    if not path_is_live(paths, path):
        return None
    return _load_json(path)


def _guard_always(paths: RunPaths, state: "GraphState") -> GuardResult:
    return GuardResult(True, "no precondition")


def _count_live(paths: RunPaths, directory: Path, suffixes: set[str]) -> int:
    """Count the files in ``directory`` that a rollback has not withdrawn.

    Every counting guard below reads this rather than ``_count_files_with_suffixes``,
    and the difference is the one that decided runs. A rollback used to be a manifest
    edit: ``workspace/`` was untouched, so the files the abandoned future had written
    stayed on disk and stayed countable. A run that reached Stage 06, found the design
    wrong and went back to Stage 03 met an already-open forward edge — opened by the
    data files Stage 04 and Stage 05 had written under the design being abandoned. The
    gate that exists to prove *this* visit did the work was answering for the visit the
    run had just repudiated.

    :func:`src.provenance.count_live_files` subtracts what
    :func:`src.provenance.invalidate_from` withdrew, and counts anything unattributed,
    so a run with no ledger behaves exactly as it did before.
    """

    from .provenance import count_live_files

    return count_live_files(paths, directory, suffixes)


def _guard_design_artifacts(paths: RunPaths, state: "GraphState") -> GuardResult:
    count = _count_live(paths, paths.data_dir, MACHINE_DATA_SUFFIXES)
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
    count = _count_live(
        paths, paths.code_dir, {".py", ".sh", ".r", ".jl", ".ipynb", ".cpp", ".rs", ".go"}
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
    count = _count_live(paths, paths.results_dir, RESULT_SUFFIXES)
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

    # The population this guard checks adjudication against is read out of a
    # file the stage under test writes. Dropping a hypothesis from it shrinks
    # `expected` and opens the edge, so the edge is closed while the frozen set
    # disagrees with AutoR's own copy of it, before the ids are counted at all.
    from .preregistration import preregistration_tamper_findings

    tampered = preregistration_tamper_findings(paths)
    if tampered:
        return GuardResult(
            False,
            "the frozen preregistration no longer matches the record AutoR stamped outside "
            "the workspace: " + " ".join(tampered),
        )

    expected = {
        str(item.get("id") or "").strip()
        for item in hypotheses
        if isinstance(item, dict) and str(item.get("type") or "") == "empirical"
    }
    outcomes = _load_json_if_live(paths, paths.hypothesis_outcomes)
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
    figures = _count_live(paths, paths.figures_dir, FIGURE_SUFFIXES)
    if not figures:
        return GuardResult(False, "the analysis produced no figure under workspace/figures")
    return GuardResult(True, f"every hypothesis is adjudicated and {figures} figure(s) exist")


def _guard_report_exists(paths: RunPaths, state: "GraphState") -> GuardResult:
    from .provenance import path_is_live

    if path_is_live(paths, paths.report_file) or _count_live(
        paths, paths.writing_dir, {".tex", ".md"}
    ):
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
    from .research_rounds import unreopened_abandonment

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
    #
    # That first sentence was the reason given for scoping this guard and leaving the
    # others global, and until `src.provenance` existed it was false: a rollback edited
    # manifest rows and left `workspace/` alone, so every artifact the other guards
    # counted survived the rollback that was supposed to invalidate it. The distinction
    # this comment draws — artifacts a rollback withdraws, ledgers it does not — is now
    # the distinction the code makes, via `_count_live` and `_load_json_if_live`.
    visit = state.path[-1] if state.path else None
    closed = visit.closed_round if visit is not None else 0
    if not closed:
        return GuardResult(False, "this visit closed no research round")

    # The *ledger* question is "does an abandonment still stand", not "was the last
    # round an abandonment". Asking the narrower one let the rollback the tool itself
    # recommends launder it: abandon at round 1, `--resume-run --rollback-stage 03`,
    # round 2 closes `converged`, and the terminal shuts because round 2 is not an
    # abandonment. Measured: Stage 07 then burned 10 operator calls against a gate
    # refusing it 20 times, and the run produced nothing.
    #
    # The *visit* gate stays. It exists so a visit that closed no round cannot be
    # governed by the ledger at all; it was never meant to let a closing visit
    # overrule a standing abandonment silently. Overruling one is legitimate and has
    # its own spelling — `reopens_round` — which this reader honours.
    standing = unreopened_abandonment(paths)
    if standing is not None:
        return GuardResult(
            True,
            f"round {standing.number} concluded the question cannot be answered: "
            f"{standing.rationale}",
        )
    return GuardResult(False, "no abandonment stands")


def _guard_has_hypotheses(paths: RunPaths, state: "GraphState") -> GuardResult:
    manifest = _load_json_if_live(paths, paths.hypothesis_manifest)
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
        "02_hypothesis_generation", "01_literature_survey", "revisit",
        "Stating the hypotheses showed the gap they rest on is not a gap — the work exists and "
        "the survey did not find it, or the literature that would settle the question was never "
        "searched. A hypothesis whose novelty claim is an unsearched query is not worth designing "
        "a study around.",
        guard="always", priority=2,
    ),
    Edge(
        "03_study_design", "02_hypothesis_generation", "revisit",
        "Designing the study showed a hypothesis cannot be brought to a decision — no measurement "
        "available here separates it from its alternative, or two of them collapse into the same "
        "comparison. Weakening the hypothesis until the design can test it is how a run ends up "
        "testing something nobody asked.",
        guard="always", priority=2,
    ),
    Edge(
        "06_analysis", "04_implementation", "revisit",
        "The analysis showed the numbers are wrong rather than disappointing — the metric is "
        "computed on the wrong axis, the split leaks, or the aggregation averages over the wrong "
        "grouping. Re-running the same code produces the same defect with more seeds behind it.",
        guard="runnable_code", priority=3,
    ),
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
    #: Why the router's answer was not used, when it was not. A refused route is not a
    #: routing observation: the run took the default because the answer was lost or
    #: off-menu, not because anything preferred it. Recorded rather than inferred,
    #: because `agent_directed=False` alone cannot tell "nobody was asked" from
    #: "somebody answered and it did not survive" — and in the archived corpus 23 of
    #: the 27 visits where anything was on offer were the second kind.
    refusal: str = ""
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
            "refusal": self.refusal,
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
            refusal=str(payload.get("refusal") or ""),
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
        """Why the run went *back* to ``slug`` before, normalised for comparison.

        Backward moves only. The pool exists so `repeats_a_previous_reason` can refuse
        a revisit that has already been tried, and an *advance* into a stage is not a
        previous attempt at that repair — it is the run arriving there in the first
        place. Pooling both put the machine-written forward rationales, which are
        identical every run, in the way of a first backward move to the same node.
        """
        return [
            " ".join(visit.reason.lower().split())
            for visit in self.path
            if visit.chose == slug and visit.reason and visit.kind == "revisit"
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
    record_graph_effect(paths, state)


GRAPH_EFFECT_FILENAME = "graph_effect.json"


def effect_file(paths: RunPaths) -> Path:
    return paths.evolution_dir / GRAPH_EFFECT_FILENAME


def graph_effect(state: GraphState) -> dict[str, Any]:
    """What the topology bought over the linear pipeline it contains.

    The adaptive graph is one of this project's two central claims, and until now no run
    could say whether it had done anything. ``stage_graph.json`` records every visit, but
    reading a departure rate out of it correctly is easy to get wrong in three ways, and
    :class:`Visit` carries a field against each:

    * ``bypassed`` -- a ``/back``, a rollback after retry exhaustion or a round decision had
      no choice set. Counting those as decisions reads an operator's intervention as
      evidence about an edge.
    * ``offered`` -- a node with one live move is not a decision. Pooling it with the rest
      makes the denominator the pipeline's length rather than the number of choices, and
      every graph then looks equally unused.
    * ``refusal`` -- the agent answered and the answer was not used, because it was lost or
      off-menu. That is not the agent agreeing with the default, and the difference is the
      difference between "the graph is not wanted" and "the graph is not reaching anyone".

    The measured answer on twelve benchmark runs, with the fix that made verdicts readable
    already in: 81 decision points, 74 agreements, 6 departures, 1 refusal. So the freedom
    is real, it reaches the router, and the router declines it 91% of the time. That is the
    least flattering reading available and it is the one the evidence supports, which is
    why this file writes it rather than leaving the claim unmeasured.
    """
    decision_points = departed = refused = agreed = bypassed = 0
    single_move = 0
    blocked_by: dict[str, int] = {}

    for visit in state.path:
        for kind in visit.blocked.values():
            blocked_by[kind] = blocked_by.get(kind, 0) + 1
        if visit.bypassed:
            bypassed += 1
            continue
        if len(visit.offered) <= 1:
            single_move += 1
            continue
        decision_points += 1
        if visit.refusal:
            refused += 1
        elif visit.chose and visit.chose != visit.default_choice:
            departed += 1
        else:
            agreed += 1

    return {
        "steps": len(state.path),
        "nodes_with_one_live_move": single_move,
        "nodes_bypassing_the_router": bypassed,
        "decision_points": decision_points,
        "departed_from_the_default": departed,
        "agreed_with_the_default": agreed,
        "answers_refused_or_lost": refused,
        "departure_rate": round(departed / decision_points, 3) if decision_points else None,
        "moves_blocked_by": blocked_by,
        "verdict": _graph_effect_sentence(decision_points, departed, refused),
    }


def _graph_effect_sentence(decision_points: int, departed: int, refused: int) -> str:
    """One line a human can act on, written to be unflattering when that is the truth."""
    if decision_points == 0:
        return (
            "No node on this run offered more than one live move, so the graph could not "
            "have differed from a linear pipeline and nothing here is evidence about it."
        )
    if departed == 0 and refused == 0:
        return (
            f"{decision_points} node(s) offered a real choice and the router took the "
            "default at every one: on this run the graph was a linear pipeline."
        )
    if departed == 0:
        return (
            f"{decision_points} node(s) offered a real choice and the router departed at "
            f"none of them, but {refused} answer(s) were refused or lost -- so this run is "
            "evidence about the routing channel, not about the topology."
        )
    return (
        f"The router departed from the default at {departed} of {decision_points} node(s) "
        f"that offered a real choice ({100 * departed / decision_points:.0f}%)"
        + (f", with {refused} answer(s) refused or lost." if refused else ".")
    )


def record_graph_effect(paths: RunPaths, state: GraphState) -> dict[str, Any]:
    """Write :func:`graph_effect` beside the state it is derived from.

    Derived rather than accumulated: unlike the review panel's, every input is already in
    ``stage_graph.json``, so recomputing from the current state is always right and a
    resumed or rolled-back run cannot leave a stale tally behind.
    """
    effect = graph_effect(state)
    write_text(effect_file(paths), json.dumps(effect, indent=2, ensure_ascii=False))
    return effect


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


def replay_cost(source: str, target: str) -> int:
    """Stages this move discards, derived from the ordering — never written down.

    A backward move throws away the work between target and source and has to
    redo it: ``07_writing -> 01_literature_survey`` costs seven stages,
    ``07_writing -> 06_analysis`` costs two. Presenting those as equally
    available is how a run spends most of its step budget on a move a cheaper
    one would have settled.

    Derived rather than tabulated on purpose. A per-edge cost constant sitting
    beside a derivable one is where drift starts, and inserting a stage would
    silently falsify every entry in such a table.
    """
    order = [item.slug for item in STAGES]
    if target == FINISH:
        return 0
    try:
        source_index, target_index = order.index(source), order.index(target)
    except ValueError:
        return 0
    if target_index >= source_index:
        return 0
    return source_index - target_index + 1


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

    def __post_init__(self) -> None:
        # The same refusal `Edge` makes about its kind, for the same reason. The two
        # fields are one fact written twice — `admissible` reads the sentence,
        # `block_census` reads the kind — and a `Move` carrying one without the other
        # makes them disagree: a move with a kind and no sentence is *admissible* and
        # counted as blocked, a move with a sentence and no kind is refused and
        # counted nowhere. Refused at construction, so the census's arithmetic is a
        # property of the type rather than of how carefully each call site was
        # written.
        if bool(self.blocked_because) != bool(self.blocked_kind):
            raise ValueError(
                f"Move {self.edge.source}->{self.edge.target} was given "
                f"blocked_because={self.blocked_because!r} and "
                f"blocked_kind={self.blocked_kind!r}; a block needs both or neither."
            )
        if self.blocked_kind and self.blocked_kind not in BLOCK_KINDS:
            raise ValueError(
                f"Move {self.edge.source}->{self.edge.target} is blocked as "
                f"{self.blocked_kind!r}, which is not one of {', '.join(BLOCK_KINDS)}. "
                "A kind nothing declares would be counted under a heading no reader "
                "can interpret."
            )

    @property
    def replay_cost(self) -> int:
        """Stages this move discards and has to redo. 0 for a forward move."""
        return replay_cost(self.edge.source, self.edge.target)

    @property
    def stage_runs(self) -> int:
        """Stage executions the move commits to before the run is back here.

        The same quantity as :attr:`replay_cost` for a backward move — the stages
        it throws away are exactly the stages it has to run again — but not the
        same *statement*, and the difference is what a budget reads. An advance
        discards nothing and still runs a stage; a finish discards nothing and
        runs none. Presenting all three as ``0`` is how a menu can show cost and
        still say nothing about what the run is about to spend.
        """
        if self.edge.kind == "finish":
            return 0
        return self.replay_cost or 1

    @property
    def admissible(self) -> bool:
        return not self.blocked_because

    @property
    def target(self) -> str:
        return self.edge.target


# ----------------------------------------------------------------------------
# What the walk has left
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkBudget:
    """What the run has already spent, against what it was given.

    Three pools, and they are not one pool. :data:`DEFAULT_MAX_STEPS` bounds the
    whole walk, :data:`DEFAULT_MAX_VISITS` bounds one node, and the unattended
    auto-skip allowance bounds how many stages may exhaust their attempts before
    the run is sent to write up whatever it holds. Only the first two are the
    graph's own; the third is the manager's, and it arrives from the caller rather
    than as a constant repeated here — a second copy of a budget is a second
    answer to "how much is left".

    The auto-skip pool is the one that matters to a routing decision and the one
    the router could not see. A backward move re-runs stages, a re-run stage can
    exhaust its attempts like any other, and an exhausted stage spends a skip. So
    a revisit and reaching the deliverable draw on the same allowance, and an
    agent shown only the moves is choosing without the denominator.

    Nothing here refuses anything. :meth:`StageGraph.moves` already blocks a move
    the step and visit budgets have closed, with its own reason and its own block
    kind; this is the same arithmetic said *before* the wall rather than at it.
    ``max_skips`` is deliberately optional for the same reason: a display may say
    "nobody declared one" and be honest, where a gate that fell back to a guess
    would be refusing on a number nobody wrote.
    """

    #: Stage executions already made, including the one being routed out of, and
    #: the cap on the whole walk.
    steps_taken: int
    max_steps: int
    #: The node being routed out of, how many times the run has entered it, and
    #: the per-stage cap.
    node: str
    node_visits: int
    max_visits: int
    #: Stages the harness auto-skipped after they exhausted their attempts.
    skips_spent: int = 0
    #: The cap on those. ``None`` when no allowance was declared: an attended run
    #: has none in play, because a person chooses what happens when a stage
    #: exhausts its attempts, and a caller with no manager behind it has nothing
    #: to declare.
    max_skips: int | None = None

    @classmethod
    def of(
        cls,
        state: GraphState,
        node: str,
        *,
        skips_spent: int = 0,
        max_skips: int | None = None,
    ) -> "WalkBudget":
        """Read the graph's own two pools off ``state``; take the third from the caller."""
        return cls(
            steps_taken=state.steps,
            max_steps=state.max_steps,
            node=node,
            node_visits=state.visits(node),
            max_visits=state.max_visits,
            skips_spent=skips_spent,
            max_skips=max_skips,
        )

    @property
    def steps_left(self) -> int:
        return max(self.max_steps - self.steps_taken, 0)

    @property
    def skips_left(self) -> int | None:
        if self.max_skips is None:
            return None
        return max(self.max_skips - self.skips_spent, 0)


def worst_case(move: Move, budget: WalkBudget) -> str:
    """What taking ``move`` can cost, in one cell, against what is left.

    Worst case rather than expected: the number that decides whether a correction
    is affordable is the one where every stage it re-runs goes badly, because that
    is the run that does not come back. Each re-run stage is a step, and each can
    exhaust its attempts and spend an auto-skip, so the ceiling on both is the
    same :attr:`Move.stage_runs`.

    It is a ceiling and it says so. A re-run stage that passes first time spends a
    step and no skip, which is the ordinary case and the reason this is not
    presented as a price.

    The skip half saturates once the pool is low, and a reader should know that
    before reading the column. ``min(runs, skips_left)`` is ``skips_left`` for every
    move that re-runs at least that many stages, so with one skip left every row of
    the adaptive menu out of `06_analysis` — the advance and every revisit alike —
    reads `up to 1 of the 1 auto-skip left`, and only `finish` differs. That is the
    honest number, because the run really can lose its last skip to any of them; it
    does mean the column tells moves apart through its step term and not its skip
    term. `WorstCaseTest.test_the_skip_ceiling_saturates_once_the_pool_is_low` in
    ``tests/test_router_budget.py`` is where that is pinned rather than asserted here.

    "Does not fit" is said about the step pool and about nothing else, and the
    narrowness is deliberate rather than missed. :attr:`Move.stage_runs` counts what
    the move commits to "before the run is back here", and the run may also fail to
    get back here because this node is at its own visit cap — that wall is the second
    of the three lines :func:`describe_budget_for_prompt` prints, in the section the
    prompt puts under this table, and folding it into a per-row verdict would restate
    one number in as many rows as the menu has. The cap on the *target* is not silent
    either: :meth:`StageGraph.moves` has already marked the move unavailable, with its
    own reason and its own block kind, before the row is rendered. So the omission
    here is one arithmetic the reader has to do across two lines, not a wall nobody
    named.
    """
    runs = move.stage_runs
    if runs == 0:
        return "—"
    steps = f"{runs} step{'s' if runs != 1 else ''} of {budget.steps_left} left"
    if runs > budget.steps_left:
        steps += " — does not fit"
    skips_left = budget.skips_left
    if skips_left is None:
        return f"{steps}; up to {runs} auto-skip{'s' if runs != 1 else ''}"
    at_risk = min(runs, skips_left)
    return (
        f"{steps}; up to {at_risk} of the {skips_left} "
        f"auto-skip{'s' if skips_left != 1 else ''} left"
    )


def describe_budget_for_prompt(budget: WalkBudget) -> str:
    """The three pools, in the words the routing prompt shows them.

    Written as what is *left* rather than as what was configured. "20 steps" is a
    setting; "eleven left" is the thing a decision divides by.
    """
    if budget.max_skips is None:
        skips = (
            f"{budget.skips_spent} spent so far, against no declared allowance — treat this "
            "pool as unknown rather than as empty or as unlimited"
        )
    else:
        skips = f"{budget.skips_spent} of {budget.max_skips} spent, {budget.skips_left} left"
    return "\n".join(
        [
            f"- **Steps**: {budget.steps_taken} of {budget.max_steps} spent, "
            f"{budget.steps_left} left. Every stage execution is one, and a stage this "
            "run has already done counts again when it is re-run.",
            f"- **Visits to `{budget.node}`**: {budget.node_visits} of {budget.max_visits}. "
            "A stage entered that many times is closed to any further move into it.",
            f"- **Auto-skips**: {skips}. A stage that exhausts its attempts spends one and "
            "is promoted as a stub saying its work was not done; when they are gone, the "
            "next exhaustion sends the run straight to the deliverable with whatever it "
            "holds, or ends it if the run is already there.",
        ]
    )


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
                    if edge.kind == "advance":
                        # Reaching the stage the caller asked for is a *completion*, and
                        # the graph already has an edge kind for that. Recorded as a
                        # pruned advance it was neither: with no live forward move
                        # `default_move` returns None, `StageRouter.choose` takes its
                        # "nothing is open" halt, and the live backward edges at that
                        # node are discarded without anyone being asked.
                        #
                        # That is not a corner case. `--final-stage 07_writing` is the
                        # ResearchClawBench default, so every benchmark run ended by
                        # throwing away the one decision worth most at Stage 07 —
                        # whether the write-up contains a claim the analysis does not
                        # support, which is the 07 -> 06 edge.
                        results.append(
                            Move(
                                replace(
                                    edge,
                                    target=FINISH,
                                    kind="finish",
                                    guard="always",
                                    rationale=(
                                        f"`{final_stage.slug}` is the last stage this run was "
                                        "asked for, and it is done."
                                    ),
                                ),
                                GuardResult(True, "the requested final stage is complete"),
                                "",
                                "",
                            )
                        )
                        continue
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

    def describe_for_prompt(self, moves: Sequence[Move], budget: WalkBudget) -> str:
        """The menu, with what each move costs and what the run has to spend.

        Cost is shown because it is real and invisible otherwise: two backward
        moves out of Stage 07 differ by 3.5x in the work they discard, and an
        agent shown only the rationales cannot tell. It is deliberately *not*
        framed as a reason to prefer the cheap move — a correct expensive
        correction beats a wrong cheap one, and a router that shops on price
        writes up around the flaw it should have gone back for.

        ``Discards`` alone was not enough to make that framing honest. A price with
        no balance beside it cannot be weighed at all, so an agent told to ignore
        it was being told the only thing it could do with the column. ``Worst
        case`` is the same number divided by what is left, and ``budget`` is
        required rather than optional because a menu rendered without one is the
        state this method spent its whole life in.
        """
        lines = [
            "| Move | Target | Kind | Discards | Worst case | Available | Why this move exists |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for index, move in enumerate(moves, start=1):
            availability = "yes" if move.admissible else f"**no** — {move.blocked_because}"
            cost = move.replay_cost
            discards = "—" if cost == 0 else f"{cost} stage{'s' if cost != 1 else ''}"
            lines.append(
                f"| {index} | `{move.edge.target}` | {move.edge.kind} | {discards} | "
                f"{worst_case(move, budget)} | {availability} | {move.edge.rationale} |"
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
    refusal: str = "",
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
    visit.refusal = refusal
    save_graph_state(paths, state)


# ----------------------------------------------------------------------------
# What the walk explored
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockCensus:
    """Per edge, what this walk was offered and what shut the rest.

    The route says which edges the run *took*. It cannot say which were on the menu
    and passed over, nor which were unavailable and why — and for a run whose claim
    is that it explored a graph rather than continued a list, those are the two
    halves that make the claim checkable. Each visit records both
    (:attr:`Visit.offered`, :attr:`Visit.blocked`); this is the sum over the walk.

    Counted per edge, ``source->target``, for the same reason the archive counts
    traversals that way: the same target reached from two nodes is two different
    moves. One node can hold two edges to one target — measured with
    ``--final-stage 06``, where the pruned advance out of Stage 06 is replaced by a
    live ``finish`` while the abandonment terminal at the same node stays
    guard-blocked — so an edge key may appear in both :attr:`offered` and
    :attr:`blocked` for a single visit. Recorded as it happened rather than
    reconciled: the node did offer a finish and did have one shut.
    """

    #: Visits the census read. The denominator for everything else here.
    visits: int
    #: ``source->target`` -> visits at which that edge was live.
    offered: dict[str, int]
    #: ``source->target`` -> block kind -> visits at which it was shut for that
    #: reason. The kinds are :data:`BLOCK_KINDS` and nothing else: :class:`Move`
    #: refuses an undeclared one at construction, so this vocabulary is closed
    #: rather than merely intended.
    blocked: dict[str, dict[str, int]]
    #: Visits that recorded no choice set at all — an operator's jump, a visit the
    #: run was interrupted in before it left, or a ``stage_graph.json`` written
    #: before the fields existed. Not a visit at which nothing was blocked: nothing
    #: was *evaluated*. Carried as a number because a census that quietly drops the
    #: visits it could not read describes a graph that offered less than it did.
    unobserved: int
    #: Visits an operator's move carried out of, from :attr:`Visit.bypassed`.
    #: Usually also ``unobserved`` — a jump arrives with the move already made and
    #: no guard evaluated — but not always: a resume starting somewhere other than
    #: where the last visit was heading flags a visit the router had already closed
    #: with a full choice set. Two counters rather than one, so that visit's offers
    #: are not read as an operator's, and the jumps are not read as offers nobody
    #: took.
    bypassed: int

    @property
    def kinds(self) -> dict[str, int]:
        """Blocks per kind over the whole walk.

        Derived from :attr:`blocked` rather than tallied beside it. Two counts of
        one thing drift, and "how often did a budget stop this run" has to be the
        same number as the sum of the budget column under it.
        """
        totals: dict[str, int] = {}
        for per_kind in self.blocked.values():
            for kind, count in per_kind.items():
                totals[kind] = totals.get(kind, 0) + count
        return dict(sorted(totals.items()))

    @property
    def blocks(self) -> int:
        """Every block recorded over the walk."""
        return sum(self.kinds.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "visits": self.visits,
            "offered": dict(self.offered),
            "blocked": {edge: dict(counts) for edge, counts in self.blocked.items()},
            "kinds": self.kinds,
            "unobserved": self.unobserved,
            "bypassed": self.bypassed,
        }


def block_census(visits: Sequence[Visit]) -> BlockCensus:
    """What the graph offered over ``visits``, and what blocked the rest.

    Reads the record the walk wrote; it cannot be recomputed afterwards. A guard
    evaluates the workspace as it was at the moment of choosing, and by the time
    the run is over the stages that followed have changed it — which is why
    :class:`Visit` carries the choice set at all, and why summarising a run without
    it threw away the only copy.

    A visit with no recorded choice set contributes nothing to either mapping. That
    is the distinction an operator's move needs: a bypass had no menu, and reading
    it as a node where every edge was shut would put an intervention into the
    census as evidence about the graph.
    """
    offered: dict[str, int] = {}
    blocked: dict[str, dict[str, int]] = {}
    unobserved = 0
    bypassed = 0
    for visit in visits:
        if visit.bypassed:
            bypassed += 1
        # No node to attribute an offer to, or nothing recorded to attribute.
        if not visit.stage or (not visit.offered and not visit.blocked):
            unobserved += 1
            continue
        for target in visit.offered:
            key = f"{visit.stage}->{target}"
            offered[key] = offered.get(key, 0) + 1
        for target, kind in visit.blocked.items():
            per_kind = blocked.setdefault(f"{visit.stage}->{target}", {})
            per_kind[kind] = per_kind.get(kind, 0) + 1
    return BlockCensus(
        visits=len(visits),
        offered=dict(sorted(offered.items())),
        blocked={key: dict(sorted(counts.items())) for key, counts in sorted(blocked.items())},
        unobserved=unobserved,
        bypassed=bypassed,
    )


def format_block_census(census: BlockCensus) -> str:
    """The census as a human reads it: what was on the menu, and what was shut."""
    if not census.offered and not census.blocked:
        return f"No choice set was recorded over {census.visits} visit(s)."
    kinds = census.kinds
    tally = ", ".join(f"{kind} {count}" for kind, count in kinds.items())
    lines = [
        f"{len(census.offered)} edge(s) offered over {census.visits} visit(s); "
        f"{census.blocks} block(s) on {len(census.blocked)} edge(s)"
        + (f" ({tally})" if tally else "")
        + f"; {census.unobserved} visit(s) with no choice set, {census.bypassed} bypassed."
    ]
    for key in sorted(set(census.offered) | set(census.blocked)):
        detail = [f"offered {census.offered[key]}"] if key in census.offered else []
        detail += [f"{kind} {count}" for kind, count in census.blocked.get(key, {}).items()]
        lines.append(f"  {key:<48} " + ", ".join(detail))
    return "\n".join(lines)


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
