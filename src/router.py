"""Ask the agent which stage comes next, and hold it to the moves that are open.

The graph in :mod:`src.stage_graph` says which moves exist and which are live.
This module is where one gets chosen. The division matters more than it looks:

* **AutoR decides what is possible.** Guards are evaluated against artifacts on
  disk. An edge whose guard fails is not selectable, no matter how the agent
  argues for it.
* **The agent decides what is sensible.** Among the live moves it picks one and
  says why, having just done the work and being the only party that knows whether
  the results actually decided anything.
* **AutoR decides what happens when those disagree.** A choice outside the menu is
  refused, recorded with the reason it was refused, and replaced by the default
  edge — which at every node is the forward one, so a refusal degrades to the old
  linear pipeline rather than to a stall.

Blocked moves are shown to the agent along with why they are blocked. Hiding them
would be the more obvious design and it is the wrong one: an agent that can see
"`07_writing` is closed because H2 has no verdict" routes to the analysis stage
that would fix it, while an agent shown only the open moves picks the best of them
without ever learning what it was missing.

**The refusal that carries the weight.** A revisit whose justification repeats one
already on the path is refused. Returning to Stage 05 a third time because "more
repeats are needed" is not iteration; the run has been there twice with that exact
reason and did not resolve it. The check is on the recorded reason rather than on
a count, so a run that goes back for a *different* reason is never penalised for
the earlier trip.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .approval_agent import extract_json_payload
from .rubric import StageScore, format_score_for_prompt
from .stage_graph import FINISH, GraphState, Move, StageGraph
from .utils import (
    RunPaths,
    StageSpec,
    append_jsonl,
    append_log_entry,
    read_text,
    truncate_text,
    write_text,
)


#: ``off`` keeps the deterministic default edge — the historical behaviour, and what
#: a linear graph collapses to anyway. ``agent`` asks the backend at every node.
#: ``auto`` asks only where the answer can differ, which is any node with more than
#: one live move; on a linear graph that is never, so ``auto`` costs nothing there.
ROUTING_MODES = ("off", "auto", "agent")


@dataclass(frozen=True)
class RoutingDecision:
    target: str
    kind: str
    reason: str
    #: What the graph would have taken with nobody asked. Recorded even when it
    #: equals ``target``: an agreement is evidence about the topology too, and the
    #: archive cannot tell "the agent confirmed the default" from "the agent was
    #: never consulted" unless both are on the record.
    default_target: str
    agent_directed: bool
    #: Why the agent's choice was not used, when it was not. Empty otherwise.
    refusal: str = ""
    #: The targets that were live when this decision was made, and why the rest were
    #: not. Carried through every return site so a refusal, a halt and an agreement
    #: all record the same thing: what was actually on offer.
    offered: tuple[str, ...] = ()
    blocked: dict[str, str] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.target == FINISH


class StageRouter:
    """Chooses the edge out of a completed stage."""

    def __init__(
        self,
        operator: Any | None = None,
        *,
        mode: str = "auto",
        fake_mode: bool = False,
    ) -> None:
        if mode not in ROUTING_MODES:
            raise ValueError(f"Unknown routing mode: {mode!r}. Expected one of {', '.join(ROUTING_MODES)}.")
        self.mode = mode
        self.operator = operator
        self.fake_mode = fake_mode

    def choose(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        graph: StageGraph,
        state: GraphState,
        score: StageScore | None = None,
        final_stage: StageSpec | None = None,
    ) -> RoutingDecision:
        moves = graph.moves(paths, stage.slug, state, final_stage=final_stage)
        live = [move for move in moves if move.admissible]
        default = graph.default_move(paths, stage.slug, state, final_stage=final_stage)
        default_target = default.target if default is not None else FINISH
        # Computed here anyway; recorded rather than dropped. See `Visit.offered`.
        offered = tuple(sorted(move.target for move in live))
        blocked = {
            move.target: move.blocked_kind for move in moves if move.blocked_kind
        }

        if default is None:
            # Nothing is open. That is a real answer at Stage 08 and a halt anywhere
            # else; either way the walk stops, and the state records which it was —
            # and *which kind* it was, because the caller's own `--final-stage` and a
            # spent step budget are not the same event and only one of them means the
            # run finished.
            # Read off the *advance* edge, not every forward one. A conditional
            # terminal is shut on every run that did not meet its condition — the
            # abandonment edge is `guard`-blocked on essentially all of them — so
            # including terminals made "guard" the answer at Stage 06 always, and
            # `--final-stage 06` came out as a halt when it is the caller getting
            # exactly what they asked for.
            #
            # A merely guard-blocked advance cannot reach here anyway:
            # `default_move` takes it as a last resort rather than returning None.
            advances = [move for move in moves if move.edge.kind == "advance"]
            kinds = {move.blocked_kind for move in advances if move.blocked_kind}
            if stage.slug == "08_dissemination":
                state.halted_because, state.halted_kind = "", ""
            else:
                state.halted_because = (
                    f"no move out of {stage.slug} is available: "
                    + "; ".join(move.blocked_because for move in moves)
                ) or "the graph has no edge here"
                state.halted_kind = next(
                    (kind for kind in ("steps", "visits", "pruned", "guard") if kind in kinds),
                    "none",
                )
            return RoutingDecision(
                FINISH, "finish", "No further move is available.", FINISH, False,
                offered=offered, blocked=blocked,
            )

        should_ask = self.mode == "agent" or (self.mode == "auto" and len(live) > 1)
        if not should_ask or self.operator is None or self.fake_mode:
            return RoutingDecision(
                default.target,
                default.edge.kind,
                _default_reason(default, moves),
                default_target,
                agent_directed=False,
                offered=offered,
                blocked=blocked,
            )

        proposal = self._ask(paths=paths, stage=stage, moves=moves, state=state, score=score)
        if proposal is None:
            return self._refuse(
                paths, stage, default, default_target,
                "the router produced no readable decision",
                offered=offered, blocked=blocked,
            )

        target = str(proposal.get("target") or "").strip()
        reason = str(proposal.get("reason") or "").strip()

        chosen = next((move for move in live if move.edge.target == target), None)
        if chosen is None:
            unavailable = next((move for move in moves if move.edge.target == target), None)
            detail = (
                f"`{target}` is not available: {unavailable.blocked_because}"
                if unavailable is not None
                else f"`{target}` is not a move out of {stage.slug}"
            )
            return self._refuse(
                paths, stage, default, default_target, detail, offered=offered, blocked=blocked
            )

        if not reason:
            return self._refuse(
                paths, stage, default, default_target,
                f"`{target}` was chosen with no stated reason",
                offered=offered, blocked=blocked,
            )

        if chosen.edge.kind == "revisit" and graph.repeats_a_previous_reason(state, target, reason):
            return self._refuse(
                paths, stage, default, default_target,
                f"the run has already gone back to `{target}` for this same reason and it was not "
                "resolved; going again on the same grounds is a loop, not an iteration",
                offered=offered, blocked=blocked,
            )

        append_log_entry(
            paths.logs,
            f"{stage.slug} route_chosen",
            f"target: {target}\nkind: {chosen.edge.kind}\ndefault: {default_target}\nreason: {reason}",
        )
        return RoutingDecision(
            target, chosen.edge.kind, reason, default_target, agent_directed=True,
            offered=offered, blocked=blocked,
        )

    # -- refusal -------------------------------------------------------------

    def _refuse(
        self,
        paths: RunPaths,
        stage: StageSpec,
        default: Move,
        default_target: str,
        detail: str,
        *,
        offered: tuple[str, ...] = (),
        blocked: dict[str, str] | None = None,
    ) -> RoutingDecision:
        append_log_entry(
            paths.logs,
            f"{stage.slug} route_refused",
            f"{detail}\nFalling back to the graph's default move: {default.target}",
        )
        append_jsonl(
            paths.evolution_dir / "routing_refusals.jsonl",
            {"stage": stage.slug, "detail": detail, "fell_back_to": default.target},
        )
        return RoutingDecision(
            default.target,
            default.edge.kind,
            f"Router fell back to the default move: {detail}.",
            default_target,
            agent_directed=False,
            refusal=detail,
            offered=offered,
            blocked=dict(blocked or {}),
        )


    # -- the ask -------------------------------------------------------------

    def _ask(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        moves: list[Move],
        state: GraphState,
        score: StageScore | None,
    ) -> dict[str, Any] | None:
        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_route.prompt.md"
        write_text(prompt_path, self.build_prompt(paths=paths, stage=stage, moves=moves, state=state, score=score))

        session_id = str(uuid.uuid4())
        try:
            command, cwd, stdin_text = self.operator._prepare_invocation(  # noqa: SLF001
                prompt_path, session_id, paths=paths, resume=False
            )
            exit_code, stdout_text, _stderr, _observed, _meta = self.operator._run_streaming_command(  # noqa: SLF001
                command=command,
                cwd=cwd,
                stage=stage,
                attempt_no=0,
                paths=paths,
                mode="route",
                stdin_text=stdin_text,
            )
        except Exception as exc:  # noqa: BLE001 - a routing failure must not end the run
            append_log_entry(paths.logs, f"{stage.slug} route_error", str(exc))
            return None

        if exit_code != 0:
            append_log_entry(
                paths.logs,
                f"{stage.slug} route_error",
                f"Routing backend exited {exit_code}.",
            )
            return None
        return extract_json_payload(stdout_text)

    def build_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        moves: list[Move],
        state: GraphState,
        score: StageScore | None,
    ) -> str:
        graph = StageGraph(tuple(move.edge for move in moves))
        route = " → ".join(f"{visit.stage}" for visit in state.path) or "(this is the first stage)"
        revisits = [
            f"- went back to `{visit.chose}` after `{visit.stage}`: {visit.reason}"
            for visit in state.path
            if visit.kind == "revisit" and visit.reason
        ]

        sections = [
            "# AutoR Routing Decision",
            "",
            f"You have just completed **{stage.stage_title}** and it has been approved. "
            "AutoR's stages are a directed graph, not a fixed sequence. Choose the move out of "
            "this node.",
            "",
            "You are choosing where the *research* should go, not where the workflow usually "
            "goes. Going backwards is a first-class move and is often the right one: an analysis "
            "that exposes a design flaw is a finding, and writing up around it is not.",
            "",
            "## Moves out of this node",
            "",
            graph.describe_for_prompt(moves),
            "",
            "A move marked unavailable cannot be chosen. The reason it is unavailable is usually "
            "actionable — if the writing stage is closed because a hypothesis has no verdict, the "
            "move that opens it is the one to take.",
            "",
            "**Discards** is how many stages the move throws away and the run has to redo. It is "
            "there so the choice is informed, not so you make the cheap one: a correct expensive "
            "correction beats a wrong cheap one every time, and a run that shops on price writes "
            "up around the flaw it should have gone back for. Use it only to break a tie between "
            "two moves that would fix the same thing.",
            "",
            "## Route so far",
            "",
            route,
        ]
        if revisits:
            sections += ["", "Backward moves already taken:", *revisits, "",
                         "Do not go back to the same stage for the same reason twice. If the "
                         "reason is genuinely unchanged, the earlier trip did not work and "
                         "repeating it will not either."]
        if score is not None:
            sections += ["", "## Measured standing of the stage you just finished", "",
                         format_score_for_prompt(score)]

        sections += [
            "",
            "## Original goal",
            "",
            truncate_text(_read(paths.user_input), max_chars=2500),
            "",
            "## Stage summary you just produced",
            "",
            truncate_text(_read(paths.stage_file(stage)) or _read(paths.stage_tmp_file(stage)), max_chars=12000),
            "",
            "## Answer",
            "",
            "Return JSON only, with no prose outside the object:",
            "",
            '{"target":"<stage slug or finish>","reason":"<one or two sentences>"}',
            "",
            "- `target` must be one of the available moves above, spelled exactly as shown.",
            "- `reason` must say what in *this stage's results* makes that the right move. "
            "\"Continue the workflow\" is not a reason; \"H2 is inconclusive because only one "
            "seed was run\" is.",
            "- Choose `finish` only if the run has produced what it set out to produce.",
        ]
        return "\n".join(sections)


def _default_reason(default: Move, moves: list[Move]) -> str:
    """Why the graph took this edge with nobody asked.

    The default is always a forward move, so there are two cases: it was open, or it
    was taken with its precondition unmet because nothing else could be. The second
    has to say so on the route — the archive later learns from these, and a step
    recorded as an ordinary advance when the guard was failing is a mislabelled
    observation.
    """
    if default.last_resort:
        return (
            f"No move out of this stage is open and there is nowhere left to go back to, so the "
            f"run advances with the precondition unmet: {default.guard.reason}"
        )
    return default.edge.rationale


def _read(path: Path) -> str:
    try:
        return read_text(path)
    except OSError:
        return ""


def format_decision(decision: RoutingDecision) -> str:
    """One line for the terminal."""
    if decision.refusal:
        return f"→ {decision.target} (default; agent choice refused: {decision.refusal})"
    who = "agent" if decision.agent_directed else "default"
    marker = " ↩" if decision.kind == "revisit" else ""
    return f"→ {decision.target}{marker} ({who}): {decision.reason}"


def routing_summary(paths: RunPaths) -> dict[str, Any]:
    """Aggregate this run's routing for the archive.

    Reported per edge rather than per stage because the thing worth learning across
    runs is whether *a move* pays, and the same target reached from two different
    sources is two different decisions.

    **A bypassed move is not an edge observation.** `/back`, a rollback after retry
    exhaustion and a research round's own jump all reach the walk with the move
    already made: no guard was evaluated, no alternative was on offer, and nothing
    chose between anything. Counted here, an operator's intervention would enter
    `RunRecord.edges` indistinguishable from a routed traversal — and, worse, would
    enter it *without a choice set*, which is the precise observation
    :attr:`src.stage_graph.Visit.offered` was added to keep out of the estimator.
    The round decisions are the largest source of these, so the edges the archive
    most wants to learn about were the ones it was being lied to about.

    They are counted, not silently dropped. A summary that quietly discards moves
    reports a route shorter than the one the run walked.
    """
    payload = _load_json(paths.evolution_dir / "stage_graph.json")
    if not isinstance(payload, dict):
        return {}
    edges: dict[str, int] = {}
    agent_directed = 0
    revisits = 0
    bypassed = 0
    for visit in payload.get("path", []):
        if not isinstance(visit, dict):
            continue
        source, target = str(visit.get("stage") or ""), str(visit.get("chose") or "")
        if not source or not target:
            continue
        if visit.get("kind") == "revisit":
            revisits += 1
        if visit.get("bypassed"):
            bypassed += 1
            continue
        edges[f"{source}->{target}"] = edges.get(f"{source}->{target}", 0) + 1
        if visit.get("agent_directed"):
            agent_directed += 1
    return {
        "edges": edges,
        "steps": len(payload.get("path", [])),
        "agent_directed": agent_directed,
        "revisits": revisits,
        "bypassed": bypassed,
        "route": payload.get("route", ""),
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
