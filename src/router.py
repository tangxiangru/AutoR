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

**And what the run has left to spend.** The same argument reaches one step further
than it used to. The prompt showed every move and what each one discards, and then
told the agent in as many words not to weigh the cost — right in the abstract, and
wrong under a budget the agent could not see. Measured on every finished run of the
first live paired trial — the population and the figures are pinned in the module
docstring of ``tests/test_router_budget.py`` — the step budget never bound and the
auto-skip allowance did. On `Astronomy_000_20260814_175426` three skips went, the
next exhaustion landed at the stage that writes the deliverable, and the run ended
`cancelled`: its manifest has `07_writing` as `failed`, its `stages/` holds a
`07_writing.tmp.md` and no `07_writing.md`, and one stage of the eight is `approved`.
A backward move re-runs stages and a re-run stage can exhaust its attempts like any
other, so revisiting and reaching the deliverable were drawing on one allowance while
the routing prompt named neither. :class:`src.stage_graph.WalkBudget` now puts all
three pools next to the menu — the graph's own two off
:class:`~src.stage_graph.GraphState`, and the
auto-skip pool from ``skip_budget``, the counters the manager enforces it with — so
"an expensive correction is worth it" has a denominator. It is still not a price
list: what changed is that "cost is not the criterion" is now said to an agent that
can tell whether it can afford to finish.

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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .approval_agent import extract_json_payload
from .obligations import load_ledger
from .preregistration import load_hypothesis_outcomes
from .rubric import StageScore, format_score_for_prompt
from .stage_graph import (
    FINISH,
    GraphState,
    Move,
    StageGraph,
    WalkBudget,
    block_census,
    describe_budget_for_prompt,
)
from .utils import (
    RunPaths,
    StageSpec,
    append_jsonl,
    append_log_entry,
    goal_excerpt,
    read_text,
    truncate_text,
    write_text,
)


#: ``off`` keeps the deterministic default edge — the historical behaviour, and what
#: a linear graph collapses to anyway. ``agent`` asks the backend at every node.
#: ``auto`` asks only where the answer can differ, which is any node with more than
#: one live move; on a linear graph that is never, so ``auto`` costs nothing there.
ROUTING_MODES = ("off", "auto", "agent")


#: Auto-skips spent and allowed, supplied by whoever enforces them. ``None`` for the
#: allowance means "nobody declared one", which the prompt says in those words rather
#: than filling in a default — see :func:`src.stage_graph.describe_budget_for_prompt`.
SkipBudget = Callable[[], tuple[int, int | None]]


#: The run supervisor required this move, so no ask happened at this node.
SUPERVISOR_PREEMPTION = "supervisor"

#: Parties other than the agent that can end a routing decision before the agent is
#: asked. Declared as a closed vocabulary in the shape ``BLOCK_KINDS`` and
#: ``INTERVENTIONS`` already have, and refused at construction, because the reason to
#: count pre-emptions at all is that a new one must not be able to arrive unnamed.
#:
#: One entry, and the one that is *not* here is deliberate. A closed research round also
#: returns a decision ahead of the ask — the ``declared`` branch below — and it is not a
#: pre-emption: the party that reasoned about the results is the same party the ask would
#: have gone to, which is why that branch records ``agent_directed=True``. Counting it
#: here would put the run's own reasoning into a counter built to notice the run's
#: reasoning being displaced. The supervisor is a different party with a different claim:
#: it has reasoned about the *spend*.
PREEMPTIONS: tuple[str, ...] = (SUPERVISOR_PREEMPTION,)


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
    #: Which party ended this decision before the agent was asked, from
    #: :data:`PREEMPTIONS`. Empty when the agent was asked, when it was asked and refused,
    #: and when nothing was on offer to ask about.
    #:
    #: A field rather than something inferred, because nothing already on the record can
    #: tell the cases apart: ``agent_directed=False`` covers a supervisor redirect, a
    #: refused answer, a linear node and ``--routing-mode off`` alike. The count exists so
    #: that loosening :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT` moves a
    #: number rather than quietly draining the capability the graph is for.
    preempted_by: str = ""

    def __post_init__(self) -> None:
        """A pre-emption outside the declared vocabulary is refused at construction.

        The shape ``Move.__post_init__`` uses for ``BLOCK_KINDS`` and
        ``Intervention.__post_init__`` for ``INTERVENTIONS``, for the same reason: a
        vocabulary enforced only by every call site spelling the constant right is not a
        vocabulary, and this one is counted rather than merely displayed.
        """
        if self.preempted_by and self.preempted_by not in PREEMPTIONS:
            raise ValueError(
                f"{self.preempted_by!r} is not a routing pre-emption; the vocabulary is "
                f"{', '.join(PREEMPTIONS)}."
            )

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
        archive: Any | None = None,
        skip_budget: SkipBudget | None = None,
    ) -> None:
        if mode not in ROUTING_MODES:
            raise ValueError(f"Unknown routing mode: {mode!r}. Expected one of {', '.join(ROUTING_MODES)}.")
        self.mode = mode
        self.operator = operator
        self.fake_mode = fake_mode
        # What the cross-run archive has learned, if the caller is willing to let it
        # be *seen*. It reaches the agent as numbers in the prompt and nothing else:
        # not `default_move`, not a guard, not a recommendation. The archive knows
        # about other research questions; the agent can see this one.
        self.archive = archive
        # The auto-skip pool, from the party that spends it. The router cannot compute
        # it: the allowance is a `ResearchManager` setting that reaches no file and no
        # `RunPaths` field, and the tally lives in memory beside it.
        #
        # Reading it back out of `logs.txt` was the other candidate and is wrong twice
        # over. `logs.txt` sits at the run root and the operator runs at `cwd=run_root`
        # with `bypassPermissions`, so it is a file the displayed party can write; and
        # it is incomplete — `_route_to_deliverable` extends the tally the budget test
        # reads without writing an `auto_skip_used:` line, so a run routed off the
        # approval gate reports every stage from the aborting one up to the deliverable
        # as consumed in memory — four when it aborts at Stage 03, six at Stage 01 —
        # and none of them on the record.
        # A provider asks the enforcer, which cannot disagree with itself.
        #
        # Optional because the router runs without a manager in tests and in
        # `tools/`; absent, the prompt says the pool was never declared.
        self.skip_budget = skip_budget

    def choose(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        graph: StageGraph,
        state: GraphState,
        score: StageScore | None = None,
        final_stage: StageSpec | None = None,
        declared: tuple[str, str] | None = None,
        skips_left: int | None = None,
        required: tuple[str, str] | None = None,
    ) -> RoutingDecision:
        # `skips_left` reaches the graph and stops there. It is deliberately not shown
        # to the agent here and not weighed by anything in this module: the decision
        # this file makes is "which of the open moves", and whether a backward edge is
        # open at all under a nearly-spent recovery budget is a refusal in code, made
        # in `StageGraph.moves`. What the agent sees of it is what it sees of every
        # other block — the edge on the menu, marked unavailable, with the reason.
        moves = graph.moves(paths, stage.slug, state, final_stage=final_stage, skips_left=skips_left)
        live = [move for move in moves if move.admissible]
        default = graph.default_move(
            paths, stage.slug, state, final_stage=final_stage, skips_left=skips_left
        )
        default_target = default.target if default is not None else FINISH
        # Computed here anyway; recorded rather than dropped. See `Visit.offered`.
        offered = tuple(sorted(move.target for move in live))
        blocked_kinds = {
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
                offered=offered, blocked=blocked_kinds,
            )

        # A closed research round's decision is a proposal like any other, and it
        # outranks the backend: the round has already reasoned about the results and
        # written its conclusion to disk, so asking a second time would be paying for
        # an opinion on a settled question. What it does not outrank is the guards —
        # `_rollback_and_jump` jumped regardless of them, and this does not.
        if declared is not None:
            target, reason = declared
            chosen = next((move for move in live if move.edge.target == target), None)
            if chosen is None:
                unavailable = next((move for move in moves if move.edge.target == target), None)
                detail = (
                    f"the round asked for `{target}`: {unavailable.blocked_because}"
                    if unavailable is not None
                    else f"the round asked for `{target}`, which is not a move out of {stage.slug}"
                )
                return self._refuse(
                    paths, stage, default, default_target, detail,
                    offered=offered, blocked=blocked_kinds,
                )
            append_log_entry(
                paths.logs,
                f"{stage.slug} route_from_round",
                f"target: {target}\nreason: {reason}",
            )
            return RoutingDecision(
                target, chosen.edge.kind, reason, default_target, agent_directed=True,
                offered=offered, blocked=blocked_kinds,
            )

        # The run supervisor's redirect: a target it requires, with the reason it gave.
        #
        # Ranked below a closed round's decision and above the backend. A round has
        # reasoned about the *results* and written its conclusion to disk; the supervisor
        # has reasoned about the *spend*, which is the weaker claim about where the run
        # should go next, so a round that has spoken is not overruled by it.
        #
        # Checked against `live` exactly as `declared` is, and refused the same way. That
        # is the whole of "only an edge the guards already leave open": there is no branch
        # here that consults a blocked move, so a redirect cannot open one.
        #
        # `agent_directed=False`, deliberately. The archive learns which moves the *agent*
        # chose pay off, and recording a move the agent did not make as one it did is the
        # one thing the offered/blocked bookkeeping exists to keep out.
        if required is not None and declared is None:
            target, reason = required
            chosen = next((move for move in live if move.edge.target == target), None)
            if chosen is None:
                unavailable = next((move for move in moves if move.edge.target == target), None)
                detail = (
                    f"the supervisor required `{target}`: {unavailable.blocked_because}"
                    if unavailable is not None
                    else f"the supervisor required `{target}`, which is not a move out of {stage.slug}"
                )
                return self._refuse(
                    paths, stage, default, default_target, detail,
                    offered=offered, blocked=blocked_kinds,
                )
            append_log_entry(
                paths.logs,
                f"{stage.slug} route_required_by_supervisor",
                f"target: {target}\nreason: {reason}",
            )
            return RoutingDecision(
                target, chosen.edge.kind, reason, default_target, agent_directed=False,
                offered=offered, blocked=blocked_kinds,
                # The ask did not happen at this node, and the record says so as a number
                # rather than as an absence. `_refuse` above deliberately does not set it:
                # a redirect the guards shut is a refusal the supervisor did not get, and
                # counting it would credit the mechanism with a choice it never took.
                preempted_by=SUPERVISOR_PREEMPTION,
            )

        # `auto` means "ask where the answer can differ". `len(live) > 1` was the wrong
        # way to say that, and it skipped the one decision this graph exists to put to
        # an agent.
        #
        # A blocked edge is not in `live`. So at a node whose forward guard is unmet and
        # whose backward edge is open — Stage 02, 03 and 04 on any run that has not yet
        # produced design artifacts, runnable code or results — `live` holds exactly the
        # repair move, `len(live) == 1`, and the router is skipped. `default_move` then
        # advances forward anyway as a `last_resort`, with the precondition still unmet,
        # and the agent is never told that the edge which would satisfy it was open.
        #
        # Measured over the 50 archived ResearchClawBench routes: 133 visits, one
        # revisit, and 41 of 50 runs halting at or before Stage 03 — the stages where
        # this is the shape of every node.
        #
        # "Push on with the precondition unmet, or go back and satisfy it" is a research
        # judgement, it is the reason the thirteen backward edges exist, and it is
        # exactly what the module docstring promises an agent gets shown. Ask for it.
        a_repair_is_open = default.last_resort and bool(live)
        should_ask = self.mode == "agent" or (
            self.mode == "auto" and (len(live) > 1 or a_repair_is_open)
        )
        if not should_ask or self.operator is None or self.fake_mode:
            return RoutingDecision(
                default.target,
                default.edge.kind,
                _default_reason(default, moves),
                default_target,
                agent_directed=False,
                offered=offered,
                blocked=blocked_kinds,
            )

        proposal = self._ask(paths=paths, stage=stage, moves=moves, state=state, score=score)
        if proposal is None:
            return self._refuse(
                paths, stage, default, default_target,
                "the router produced no readable decision",
                offered=offered, blocked=blocked_kinds,
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
                paths, stage, default, default_target, detail, offered=offered,
                blocked=blocked_kinds,
            )

        if not reason:
            return self._refuse(
                paths, stage, default, default_target,
                f"`{target}` was chosen with no stated reason",
                offered=offered, blocked=blocked_kinds,
            )

        if chosen.edge.kind == "revisit" and graph.repeats_a_previous_reason(state, target, reason):
            return self._refuse(
                paths, stage, default, default_target,
                f"the run has already gone back to `{target}` for this same reason and it was not "
                "resolved; going again on the same grounds is a loop, not an iteration",
                offered=offered, blocked=blocked_kinds,
            )

        append_log_entry(
            paths.logs,
            f"{stage.slug} route_chosen",
            f"target: {target}\nkind: {chosen.edge.kind}\ndefault: {default_target}\nreason: {reason}",
        )
        return RoutingDecision(
            target, chosen.edge.kind, reason, default_target, agent_directed=True,
            offered=offered, blocked=blocked_kinds,
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
        # `target` is what identifies a routing move, the way `decision` identifies a review
        # verdict: the backend is an agent whose stdout is a transcript, and the object it
        # merely quoted from a file must not outrank the one it chose.
        payload = extract_json_payload(stdout_text, verdict_key="target")
        if payload is not None:
            return payload

        # Every failure of the ask degrades *forward*: `choose` falls through to
        # `_refuse`, which takes the default, and the default is a forward move by
        # construction. So a dropped brace is scored as "advance" — a routing decision
        # lost to formatting, indistinguishable in the archive from one the agent made.
        # The reviewer gate has re-asked for years; this had one attempt.
        append_log_entry(
            paths.logs,
            f"{stage.slug} route_unparsed",
            "No object carrying `target` in the routing response; re-asking once.\n"
            f"tail: {stdout_text[-2000:]}",
        )
        return self._reask(paths=paths, stage=stage, previous=stdout_text)

    def _reask(self, *, paths: RunPaths, stage: StageSpec, previous: str) -> dict[str, Any] | None:
        """One more attempt, asking only for the object."""
        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_route.retry.prompt.md"
        write_text(
            prompt_path,
            "# Routing answer, second attempt\n\n"
            "Your previous answer could not be parsed. Return the routing object and "
            "nothing else — no explanation, no code fence, no text after it.\n\n"
            '{"target":"<stage slug>","reason":"<one or two sentences>"}\n\n'
            "## What you replied\n\n"
            f"{previous[-4000:]}\n",
        )
        try:
            command, cwd, stdin_text = self.operator._prepare_invocation(  # noqa: SLF001
                prompt_path, str(uuid.uuid4()), paths=paths, resume=False
            )
            exit_code, stdout_text, _stderr, _observed, _meta = self.operator._run_streaming_command(  # noqa: SLF001
                command=command,
                cwd=cwd,
                stage=stage,
                attempt_no=0,
                paths=paths,
                mode="route_retry",
                stdin_text=stdin_text,
            )
        except Exception as exc:  # noqa: BLE001 - a routing failure must not end the run
            append_log_entry(paths.logs, f"{stage.slug} route_error", str(exc))
            return None
        if exit_code != 0:
            return None
        return extract_json_payload(stdout_text, verdict_key="target")

    def _archive_evidence(self, source: str, targets: list[str]) -> str:
        """What the archive can show about the moves on this menu, or nothing.

        Best-effort. A archive that cannot be read is a research aid that is
        unavailable, not a reason to fail a routing decision.
        """
        if self.archive is None or not targets:
            return ""
        try:
            from .decisions import (
                believable_evidence,
                decisions_from,
                format_evidence_for_prompt,
                offered_payoffs,
            )

            payoffs = offered_payoffs(decisions_from(self.archive.runs()))
            live = believable_evidence(payoffs, targets, source)
            return format_evidence_for_prompt(live, max(len(payoffs), 1))
        except Exception:  # noqa: BLE001 - never fail a route over a report
            return ""


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
        skips_spent, max_skips = self.skip_budget() if self.skip_budget else (0, None)
        budget = WalkBudget.of(
            state, stage.slug, skips_spent=skips_spent, max_skips=max_skips
        )
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
            graph.describe_for_prompt(moves, budget),
            "",
            "A move marked unavailable cannot be chosen. The reason it is unavailable is usually "
            "actionable — if the writing stage is closed because a hypothesis has no verdict, the "
            "move that opens it is the one to take.",
            "",
            "**Discards** is how many stages the move throws away and the run has to redo. "
            "**Worst case** is what that comes to against what is left: one stage execution per "
            "discarded stage, and — because a re-run stage can exhaust its attempts like any "
            "other — up to one auto-skip each. Both are ceilings; a re-run stage that passes "
            "first time costs a step and no skip.",
            "",
            "## What this run has left",
            "",
            describe_budget_for_prompt(budget),
            "",
            "Cost is not the criterion. A correct expensive correction beats a wrong cheap one, "
            "and a run that shops on price writes up around the flaw it should have gone back "
            "for. But a correction the run cannot afford to finish is not a correction: if the "
            "worst case of the move you want does not fit in the numbers above, the run does not "
            "come back from it — it stops part-way and writes up from wherever it stopped, which "
            "is the outcome going back was supposed to prevent. So spend on the move that fixes "
            "the research, and where two moves would fix the same thing, break a tie with the "
            "one the run can finish.",
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
            if score.total >= 1.0 - 1e-9:
                # A ceiling is not a verdict on the research. The ratchet stops at 1.000
                # and most stages reach it, so a router told only the total is told the
                # same thing at almost every node -- see `unfinished_business`.
                sections += [
                    "",
                    "This is the rubric's ceiling, and the ratchet polishes every stage "
                    "towards it, so most stages arrive here reporting 1.000. It means the "
                    "mechanical checks pass — references resolve, numbers trace to files, "
                    "the contract is met. It does not mean the research question was "
                    "answered, and it is not evidence for advancing.",
                ]

        unsettled = unfinished_business(paths, stage)
        if unsettled:
            sections += ["", unsettled]

        evidence = self._archive_evidence(stage.slug, [move.target for move in moves if move.admissible])
        if evidence:
            sections += ["", evidence]

        # Only offer `finish` where a finish edge exists. Inviting it everywhere cost a
        # real decision: at Stage 07 the agent answered `finish`, 07 has no finish edge,
        # the router refused an off-menu target and fell through to the default — which
        # at 07 happens to be backward. That fallback is the single `revisit` recorded in
        # the whole 133-visit archive, and it was not a routing decision at all.
        can_finish = any(move.edge.kind == "finish" for move in moves)
        sections += [
            "",
            "## Original goal",
            "",
            goal_excerpt(_read(paths.user_input), max_chars=2500),
            "",
            "## Stage summary you just produced",
            "",
            truncate_text(_read(paths.stage_file(stage)) or _read(paths.stage_tmp_file(stage)), max_chars=12000),
            "",
            "## Answer",
            "",
            "Return JSON only, with no prose outside the object. Emit it as your final "
            "message and emit nothing after it.",
            "",
            f'{{"target":"{"<stage slug or finish>" if can_finish else "<stage slug>"}",'
            '"reason":"<one or two sentences>"}',
            "",
            "- `target` must be one of the available moves above, spelled exactly as shown.",
            "- `reason` must say what in *this stage's results* makes that the right move. "
            "\"Continue the workflow\" is not a reason; \"H2 is inconclusive because only one "
            "seed was run\" is.",
        ]
        if can_finish:
            sections.append(
                "- Choose `finish` only if the run has produced what it set out to produce."
            )
        return "\n".join(sections)


#: Verdicts that mean the hypothesis was settled. Everything else -- ``inconclusive``,
#: ``not_tested``, a blank, a verdict the schema does not know -- is a question the run
#: asked and did not answer, which is the strongest reason there is to go back.
_SETTLED_VERDICTS = frozenset({"supported", "refuted"})


def unfinished_business(paths: RunPaths, stage: StageSpec) -> str:
    """What is still owed, rendered for the routing prompt. Empty when nothing is.

    The router used to be handed the stage's rubric total and nothing else, and the
    ratchet grinds that total to 1.000 before the router ever sees it -- measured over
    41 ResearchClawBench runs, 71% of routing decisions were made against a stage
    reporting a perfect score with every criterion at 1.00 and the "where the points
    are" list empty. The prompt asks for a `reason` grounded in "what in *this stage's
    results* makes that the right move" and then shows results with nothing wrong in
    them, so the only defensible answer is the forward one. The router departed at 16 of
    252 decision points (6.3%) and 31 of 41 runs walked a straight line.

    It was not being blocked. Guards refused 48 moves across those runs and 46 of them
    were `finish`, which is the terminal edge being closed rather than a departure being
    denied. The router had the moves; it had no grounds.

    These are the grounds, and they were on disk the whole time. 30% of hypotheses came
    back `inconclusive` or `not_tested` and 84% of runs held at least one -- the prompt's
    own worked example of a good reason is "H2 is inconclusive because only one seed was
    run", and the run knew which hypotheses those were and never said. Obligations are
    the same shape from the reviewer's side: a debt it recorded, still open, and a stage
    it named to pay it.

    Facts, not advice. Nothing here tells the router to go back -- it lists what is
    unsettled and lets the move follow, because an instruction to depart more often is a
    thumb on the scale and would be obeyed on the runs that had nothing to go back for.
    """
    lines: list[str] = []

    unsettled = [
        outcome
        for outcome in load_hypothesis_outcomes(paths)
        if outcome.verdict not in _SETTLED_VERDICTS
    ]
    if unsettled:
        lines += [
            f"**{len(unsettled)} hypothesis verdict(s) are not settled.** A hypothesis the "
            "run could not decide is a question it asked and did not answer. Writing up "
            "around one is the failure this graph exists to avoid; going back to the stage "
            "that could settle it is a first-class move.",
            "",
        ]
        for outcome in unsettled:
            verdict = outcome.verdict or "(no verdict recorded)"
            rationale = truncate_text(outcome.rationale, max_chars=400)
            lines.append(f"- `{outcome.identifier or '(unnamed)'}` — **{verdict}**: {rationale}")
        lines.append("")

    ledger = load_ledger(paths)
    # The reviewer's own record of what it let through on the promise that a later stage
    # would settle it. `open_for` asks the ledger which of those this stage is on the hook
    # for, which is the same question the routing decision is about to answer.
    owed = ledger.open_for(stage)
    if owed:
        lines += [
            f"**{len(owed)} obligation(s) the reviewer recorded are still open against "
            "this stage.**",
            "",
        ]
        for obligation in owed:
            lines.append(
                f"- `{obligation.obligation_id}` (raised at {obligation.origin_stage}, "
                f"deferred {obligation.deferrals}x): {truncate_text(obligation.text, max_chars=400)}"
            )
        lines.append("")

    if not lines:
        return ""
    return "\n".join(["## What is still unsettled", "", *lines]).rstrip()


def _default_reason(default: Move, moves: list[Move]) -> str:
    """Why the graph took this edge with nobody asked.

    The default is always a forward move, so there are two cases: it was open, or it
    was taken with its precondition unmet because nothing else could be. The second
    has to say so on the route — the archive later learns from these, and a step
    recorded as an ordinary advance when the guard was failing is a mislabelled
    observation.
    """
    if default.last_resort:
        # Two different events, and recording them as one put a false claim on the
        # route. `default_move` never goes backward by design, so it last-resorts
        # forward whether or not a backward edge was open — and at Stages 02-04 one
        # usually is. The archive learns from these reasons; "nowhere left to go back
        # to" written over a live repair edge is a mislabelled observation about the
        # topology, in the direction that makes the topology look inert.
        open_moves = [move.target for move in moves if move.admissible]
        if open_moves:
            return (
                "No forward move is open, so the run advances with the precondition unmet: "
                f"{default.guard.reason}. It was not sent back to "
                f"{', '.join(f'`{target}`' for target in open_moves)}, which "
                f"{'was' if len(open_moves) == 1 else 'were'} open — the default never goes "
                "backward, and nothing chose one."
            )
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

    **`census` is the other half of the walk.** `edges` and `decisions` are about
    moves the run *made*. `decisions` already carried each visit's `offered` set,
    and `offered_payoffs` consumes it — so what was missing was narrower than "the
    exploration left no record": :attr:`src.stage_graph.Visit.blocked` was read by
    nothing, and there was no per-edge total over the whole walk.
    :func:`src.stage_graph.block_census` supplies both.

    A visit with no recorded choice set contributes neither an offer nor a block,
    because nothing was evaluated — an operator's `/back`, a rollback, a round's own
    jump. A bypass that *did* record a choice set contributes both, because those
    guard evaluations happened even though the move out was the operator's, and
    :attr:`BlockCensus.bypassed` counts it separately so neither reading is forced.

    **`preempted` is the count beside `agent_directed`.** The supervisor's `redirect`
    returns a routing decision before the agent is asked, which may well be right and
    has to be countable: every other mechanism that constrains a run is separately
    gated, and the capability they can jointly remove — the run choosing its own next
    move, backward included — was gated by nobody. One number, on a record that
    already exists, so that loosening
    :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT` shows up as a figure
    moving rather than as a capability draining away. It is not a view: nothing here
    renders it for a person, and it goes where the other run-level routing figures go
    — :attr:`src.archive.RunRecord.preempted`, beside `agent_directed` and `bypassed`,
    which is what makes it comparable across runs rather than a fact about one.
    """
    payload = _load_json(paths.evolution_dir / "stage_graph.json")
    if not isinstance(payload, dict):
        return {}
    census = block_census(GraphState.from_dict(payload).path)
    edges: dict[str, int] = {}
    # The same walk, kept per decision rather than summed per edge. `edges` cannot
    # distinguish "declined" from "never offered", and those are different
    # observations — see :mod:`src.decisions`.
    decisions: list[dict[str, object]] = []
    agent_directed = 0
    revisits = 0
    bypassed = 0
    refused = 0
    preempted = 0
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
        # A refused route is a real traversal and not a real decision, and the two
        # halves go to different places.
        #
        # The edge *was* taken, with its guards evaluated and the graph's own default
        # chosen, so it stays in `edges` — unlike a bypass, where no guard was
        # evaluated at all. What did not happen is a choice: the router was asked, an
        # answer came back, and it was lost as unreadable or off-menu. Recorded in
        # `decisions`, that reads to `src.decisions` as "an alternative was offered and
        # declined", which is the one thing it was built to keep out. In the archived
        # corpus 23 of the 27 visits where anything was on offer were refusals, so the
        # estimator's picture of every forward edge was built almost entirely out of
        # answers nobody read.
        was_refused = bool(visit.get("refusal"))
        if was_refused:
            refused += 1
        if not was_refused:
            decisions.append(
                {
                    "source": source,
                    "chose": target,
                    "offered": [str(item) for item in visit.get("offered", []) if str(item)],
                    "agent_directed": bool(visit.get("agent_directed")),
                }
            )
        edges[f"{source}->{target}"] = edges.get(f"{source}->{target}", 0) + 1
        if visit.get("agent_directed"):
            agent_directed += 1
        # The count that says how often the graph's choice was taken away, beside the
        # count that says how often it was made. Read off the field rather than derived:
        # every derivation available here pools a pre-emption with a linear node, a
        # refused answer and `--routing-mode off`.
        if visit.get("preempted_by"):
            preempted += 1
    return {
        "edges": edges,
        "decisions": decisions,
        "census": census.to_dict(),
        "steps": len(payload.get("path", [])),
        "agent_directed": agent_directed,
        "preempted": preempted,
        "revisits": revisits,
        "bypassed": bypassed,
        "refused": refused,
        "route": payload.get("route", ""),
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
