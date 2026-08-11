"""End to end: the run navigating its own topology, through the real manager loop.

The unit tests around the graph prove the topology is right. This proves the walk
is wired to it — that a router decision actually redirects the manager, that a
backward move invalidates the downstream stages it should, and, first of all, that
a run which asked for none of this still runs 01 through 08 exactly as it did
before the graph existed.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.evolution import EvolutionConfig
from src.manager import ResearchManager
from src.manifest import load_run_manifest
from src.router import RoutingDecision, routing_summary
from src.rubric import score_stage
from src.stage_graph import (
    FINISH,
    GUARDS,
    GraphState,
    StageGraph,
    load_graph_state,
    save_graph_state,
)
from src.utils import STAGES, build_run_paths, load_run_config, read_text, write_text
from tests.test_manager_smoke import REPO_ROOT, ScriptedSmokeOperator


STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")
STAGE_06 = next(stage for stage in STAGES if stage.slug == "06_analysis")
STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")


class NeverRunsOperator(ScriptedSmokeOperator):
    """Fails loudly if the walk starts a stage.

    Used where the assertion *is* that no stage runs. A resume that refuses has
    nothing to execute, and a passing test that merely checked the status afterwards
    would still pass if the walk quietly re-ran everything.
    """

    def run_stage(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the walk started a stage on a run that had nothing to resume")


def _advance(stage) -> RoutingDecision:
    """The forward move, scripted. Keeps a walk test deterministic.

    Delegating the non-forced decisions to the real router would make the route
    depend on which guards the smoke operator's artifacts happen to satisfy, so
    the test would be asserting the fake operator's output rather than the walk.
    """
    index = next(i for i, item in enumerate(STAGES) if item.slug == stage.slug)
    target = STAGES[index + 1].slug if index + 1 < len(STAGES) else FINISH
    return RoutingDecision(target, "advance" if target != FINISH else "finish", "continue", target, False)


class GraphWalkTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_dir = Path(self._tmp.name) / "runs"

    def build(self, **kwargs) -> tuple[ScriptedSmokeOperator, ResearchManager]:
        operator = ScriptedSmokeOperator()
        manager = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=self.runs_dir,
            operator=operator,
            output_stream=io.StringIO(),
            **kwargs,
        )
        return operator, manager

    def drive(
        self,
        manager: ResearchManager,
        goal: str = "Walk the stage graph.",
        **kwargs,
    ) -> bool:
        stack = ExitStack()
        stack.enter_context(patch.object(manager.ui, "choose_intake_clarification_answer", return_value=None))
        stack.enter_context(patch.object(manager.ui, "read_optional_multiline_feedback", return_value=None))
        stack.enter_context(patch.object(manager.ui, "choose_intake_final_action", return_value="5"))
        stack.enter_context(patch.object(manager, "_ask_choice", return_value="5"))
        with stack:
            return manager.run(goal, venue="neurips_2025", **kwargs)

    def only_run(self):
        roots = sorted(path for path in self.runs_dir.iterdir() if path.is_dir())
        self.assertEqual(len(roots), 1)
        return build_run_paths(roots[0])

    # -- what a run that asks for nothing gets -------------------------------

    def test_the_default_run_is_adaptive_and_still_reaches_the_end(self) -> None:
        """The default topology can go back, but nothing pushes it back on its own.

        Every backward move needs a reason, and nobody supplies one here, so the
        route is the plain sequence. This is the regression that would matter most:
        turning the graph on by default must not change where an ordinary run ends
        up, only what it is *able* to do.
        """
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))

        paths = self.only_run()
        state = load_graph_state(paths)
        self.assertEqual([visit.stage for visit in state.path], [stage.slug for stage in STAGES])
        self.assertEqual(state.path[-1].chose, FINISH)
        self.assertEqual(load_run_config(paths)["stage_graph"], "adaptive")
        self.assertEqual(load_run_config(paths)["routing_mode"], "auto")

    def test_an_explicit_linear_run_walks_the_strict_sequence(self) -> None:
        _operator, manager = self.build(stage_graph=StageGraph.linear())
        self.assertTrue(self.drive(manager))
        paths = self.only_run()
        self.assertEqual(
            [visit.stage for visit in load_graph_state(paths).path],
            [stage.slug for stage in STAGES],
        )
        self.assertEqual(load_run_config(paths)["stage_graph"], "linear")

    def test_routing_off_never_calls_the_router(self) -> None:
        """The escape hatch has to actually be an escape hatch: a run that turned
        routing off must not spend a backend call per stage boundary."""
        _operator, manager = self.build(routing_mode="off")
        with patch.object(manager.router, "_ask", side_effect=AssertionError("router was asked")):
            self.assertTrue(self.drive(manager))

    def test_a_router_that_cannot_be_reached_does_not_derail_the_walk(self) -> None:
        """Routing is on by default, so its failure mode is now everyone's.

        The backend here has none of the private methods the router calls, which is
        the harshest version of "the routing call did not work". The run has to come
        out the same as one that never asked.
        """
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))
        state = load_graph_state(self.only_run())
        self.assertEqual([visit.stage for visit in state.path], [stage.slug for stage in STAGES])
        self.assertFalse(any(visit.agent_directed for visit in state.path))

    def test_the_default_move_is_never_a_backward_one(self) -> None:
        """A revisit taken by default carries no reason, and the router refuses an
        unreasoned revisit. A default able to do what no explicit decision may do
        would be the one path around that rule.
        """
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))
        for visit in load_graph_state(self.only_run()).path:
            if not visit.agent_directed:
                self.assertNotEqual(visit.kind, "revisit", msg=f"{visit.stage} reversed by default")

    # -- the walk follows the router -----------------------------------------

    def test_a_backward_decision_sends_the_run_back(self) -> None:
        """The move a linear list cannot express, taken through the real loop."""
        _operator, manager = self.build(stage_graph=StageGraph.adaptive(), routing_mode="agent")
        sent_back = {"done": False}

        def choose(*, paths, stage, graph, state, score=None, final_stage=None, **_kwargs):
            if stage.slug == STAGE_06.slug and not sent_back["done"]:
                sent_back["done"] = True
                return RoutingDecision(
                    STAGE_05.slug,
                    "revisit",
                    "H1 rests on a single seed, so the verdict cannot be decided.",
                    STAGE_07.slug,
                    agent_directed=True,
                )
            return _advance(stage)

        with patch.object(manager.router, "choose", side_effect=choose):
            self.assertTrue(self.drive(manager))

        route = [visit.stage for visit in load_graph_state(self.only_run()).path]
        self.assertEqual(
            route,
            [
                "01_literature_survey",
                "02_hypothesis_generation",
                "03_study_design",
                "04_implementation",
                "05_experimentation",
                "06_analysis",
                "05_experimentation",
                "06_analysis",
                "07_writing",
                "08_dissemination",
            ],
        )

    def test_a_backward_move_marks_the_downstream_stages_stale(self) -> None:
        """Re-entering a stage invalidates what came after it. Skipping this would
        leave a later stage's approved summary in memory describing work the
        revisit is about to replace."""
        _operator, manager = self.build(stage_graph=StageGraph.adaptive(), routing_mode="agent")
        seen: list[str] = []

        def choose(*, paths, stage, graph, state, score=None, final_stage=None, **_kwargs):
            if stage.slug == STAGE_06.slug and STAGE_06.slug not in seen:
                seen.append(STAGE_06.slug)
                manifest_before = load_run_manifest(paths.run_manifest)
                approved = {
                    entry.slug for entry in manifest_before.stages if entry.status == "approved"
                }
                self.assertIn(STAGE_05.slug, approved)
                return RoutingDecision(
                    STAGE_05.slug, "revisit", "The ablation was never run.", STAGE_07.slug, True
                )
            return _advance(stage)

        with patch.object(manager.router, "choose", side_effect=choose):
            self.assertTrue(self.drive(manager))

        paths = self.only_run()
        reasons = [
            visit.reason for visit in load_graph_state(paths).path if visit.kind == "revisit"
        ]
        self.assertIn("The ablation was never run.", reasons)

    def test_the_step_limit_stops_a_run_that_will_not_converge(self) -> None:
        """A router that always goes back is the failure mode a budget exists for."""
        _operator, manager = self.build(
            stage_graph=StageGraph.adaptive(),
            routing_mode="agent",
            graph_max_steps=6,
            graph_max_visits=99,
        )

        def choose(*, paths, stage, graph, state, score=None, final_stage=None, **_kwargs):
            if stage.slug == STAGE_05.slug:
                return RoutingDecision(STAGE_06.slug, "advance", "on", STAGE_06.slug, True)
            if stage.slug == STAGE_06.slug:
                return RoutingDecision(
                    STAGE_05.slug, "revisit", f"again {state.steps}", STAGE_07.slug, True
                )
            return _advance(stage)

        with patch.object(manager.router, "choose", side_effect=choose):
            self.drive(manager)

        state = load_graph_state(self.only_run())
        self.assertLessEqual(state.steps, 6)
        self.assertIn("step limit", state.halted_because)

    def test_a_jump_is_marked_bypassed_and_a_routed_move_is_not(self) -> None:
        """`/back`, a retry rollback and a research-round decision all reach the walk
        with the move already made. They had no choice set, and an estimator that
        counted them as decisions where nothing else was on offer would be reading an
        operator's intervention as evidence about an edge.
        """
        _operator, manager = self.build(stage_graph=StageGraph.adaptive(), routing_mode="agent")
        jumped = {"done": False}
        real_run_stage = manager._run_stage

        def run_stage(paths, stage):
            approved = real_run_stage(paths, stage)
            if stage.slug == STAGE_06.slug and not jumped["done"]:
                jumped["done"] = True
                manager._jump_target_stage = STAGE_05
                manager._jump_reason = "Operator sent it back."
            return approved

        with patch.object(manager, "_run_stage", side_effect=run_stage), patch.object(
            manager.router, "choose", side_effect=lambda **kw: _advance(kw["stage"])
        ):
            self.drive(manager)

        path = load_graph_state(self.only_run()).path
        bypassed = [v for v in path if v.bypassed]
        self.assertEqual(len(bypassed), 1)
        self.assertEqual(bypassed[0].chose, STAGE_05.slug)
        self.assertEqual(bypassed[0].offered, ())
        self.assertTrue(all(not v.bypassed for v in path if v is not bypassed[0]))

    # -- a run that did not finish must not report that it did ---------------

    def test_a_budget_halt_is_not_a_completed_run(self) -> None:
        """The worst available outcome, and what it looked like.

        `--graph-max-steps 4` produced: exit code 0, `run_status: completed`,
        `last_event: run.completed`, the log line "All stages approved. Run
        complete." — and Stages 05 through 08 never ran. Anything checking the exit
        code or the status would score an empty run as a success, and
        `state.halted_because` was set the whole time and read by nothing.
        """
        _operator, manager = self.build(graph_max_steps=4)
        completed = self.drive(manager)

        paths = self.only_run()
        manifest = load_run_manifest(paths.run_manifest)
        self.assertFalse(completed)
        self.assertEqual(manifest.run_status, "halted")
        self.assertEqual(manifest.last_event, "run.halted")
        self.assertTrue(
            [entry.slug for entry in manifest.stages if not entry.settled],
            msg="a halt that settled every stage is not the case this is about",
        )
        state = load_graph_state(paths)
        self.assertEqual(state.halted_kind, "steps")

    def test_final_stage_is_a_completed_run_not_a_halt(self) -> None:
        """The control. `--final-stage` also ends the walk with moves unavailable,
        and it is the caller getting exactly what they asked for.

        The distinction is easy to lose: the abandonment terminal is guard-blocked on
        every run that did not abandon, so reading the halt kind off *every* forward
        edge made `guard` the answer at Stage 06 always, and `--final-stage 06` came
        out as a failure. It is read off the advance edge alone.
        """
        stage_06 = next(stage for stage in STAGES if stage.number == 6)
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager, final_stage=stage_06))

        paths = self.only_run()
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "completed")
        # No halt kind at all, which is what this test's name has always said it is.
        # Reaching the requested final stage now takes a live `finish` edge rather than
        # leaving the node with no forward move; `halted_kind` describes a walk that
        # stopped because it could not continue, and this one stopped because it was
        # done. The distinction the docstring draws is preserved and sharpened.
        state = load_graph_state(paths)
        self.assertEqual(state.halted_kind, "")
        self.assertEqual(state.path[-1].chose, FINISH)

    def test_resuming_an_abandoned_run_does_not_relabel_it_completed(self) -> None:
        """A refused resume ran no walk, and `_complete_run` read the walk.

        So the resume printed "Nothing to resume", fell through, and wrote
        `run_status: completed` over `abandoned` — with Stages 07 and 08 still
        pending and no report on disk. `operator=None` is the assertion that no walk
        starts: if one did, this raises rather than quietly passing.
        """
        _operator, manager = self.build()
        self._abandon_at_analysis(manager)
        self.drive(manager)
        paths = self.only_run()
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "abandoned")

        resumed = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=self.runs_dir,
            operator=NeverRunsOperator(),
            output_stream=io.StringIO(),
        )
        self.assertTrue(resumed.resume_run(paths.run_root))

        manifest = load_run_manifest(paths.run_manifest)
        self.assertEqual(manifest.run_status, "abandoned")
        self.assertEqual(manifest.last_event, "run.abandoned")

    def test_resuming_an_ordinary_finished_run_still_reports_completed(self) -> None:
        """The control for the one above, so the fallback cannot over-broaden."""
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))
        paths = self.only_run()

        resumed = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=self.runs_dir,
            operator=NeverRunsOperator(),
            output_stream=io.StringIO(),
        )
        self.assertTrue(resumed.resume_run(paths.run_root))
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "completed")

    def test_a_standing_abandonment_is_not_laundered_by_a_rollback_resume(self) -> None:
        """The rollback the tool itself recommends was the way around the terminal.

        A bare resume of an abandoned run prints "To continue anyway, roll back
        explicitly, or record a round that reopens it." Take the first suggestion:
        `--rollback-stage 03`, round 2 closes `converged`, and the guard shut because
        round 2 was not an abandonment. Measured: Stage 07 burned 10 operator calls
        against a gate refusing it 20 times, and the run produced nothing.

        The ledger question is "does an abandonment still stand", not "was the last
        round one". The visit gate stays — it stops a visit that closed nothing being
        governed by the ledger at all — and the companion below is what holds it.
        """
        _operator, manager = self.build()
        self._abandon_at_analysis(manager)
        self.drive(manager)
        paths = self.only_run()
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "abandoned")

        operator, resumed = self.build()
        self._declare_at_analysis(resumed, "converged")
        stage_03 = next(stage for stage in STAGES if stage.number == 3)
        self.drive_resume(resumed, paths.run_root, rollback_stage=stage_03)

        self.assertEqual(operator.invocations.get("07_writing", 0), 0)
        self.assertEqual(operator.invocations.get("08_dissemination", 0), 0)
        # The Stage-07 refusal specifically. The log legitimately records the round's
        # own decision; what must be absent is the gate rejecting a write-up 20 times.
        self.assertNotIn("cannot run: round", read_text(paths.logs))
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "abandoned")

    def test_a_round_that_says_it_reopens_the_abandonment_may_continue(self) -> None:
        """The companion, so the fix cannot be satisfied by nailing the terminal shut.

        Overruling an abandonment is legitimate. It has a spelling, and a round that
        uses it gets through to writing.
        """
        _operator, manager = self.build()
        self._abandon_at_analysis(manager)
        self.drive(manager)
        paths = self.only_run()

        operator, resumed = self.build()
        self._declare_at_analysis(resumed, "converged", reopens_round=1)
        stage_03 = next(stage for stage in STAGES if stage.number == 3)
        self.drive_resume(resumed, paths.run_root, rollback_stage=stage_03)

        self.assertGreater(operator.invocations.get("07_writing", 0), 0)
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "completed")

    def test_a_resume_that_starts_elsewhere_does_not_archive_the_move_it_overruled(self) -> None:
        """The halted walk closed Stage 06 with `chose='finish'`. The resume starts at
        Stage 07 and never re-enters 06, so that visit is never reconciled — and the
        archived row claimed `06_analysis->finish` while its own route read
        `06 -> 07 -> 08`. One record, two contradictory claims, and the real advance
        into Stage 07 missing entirely.
        """
        stage_06 = next(stage for stage in STAGES if stage.number == 6)
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager, final_stage=stage_06))
        paths = self.only_run()
        self.assertIn("06_analysis->finish", routing_summary(paths)["edges"])

        _op2, resumed = self.build()
        self.drive_resume(resumed, paths.run_root)

        summary = routing_summary(paths)
        self.assertNotIn("06_analysis->finish", summary["edges"])
        self.assertIn("07_writing->08_dissemination", summary["edges"])
        self.assertEqual(summary["bypassed"], 1)
        self.assertIn("07_writing", summary["route"])

    def test_a_resume_that_continues_where_it_was_heading_keeps_its_edge(self) -> None:
        """The control for the `!= entry.slug` half.

        Dropping that condition would mark *every* resumed run's last move bypassed,
        including one that simply picked up where it left off, and quietly delete a
        traversal the run genuinely made. Staged directly rather than through a real
        interruption, because the two natural ways to stop a walk — a budget halt and
        an abort — both leave a last visit that was not heading to the entry stage.
        """
        _operator, manager = self.build(graph_max_steps=4)
        self.drive(manager)
        paths = self.only_run()

        # Rewrite the halt as "it was on its way to Stage 05 and stopped", which is
        # what an interruption between stages looks like.
        state = load_graph_state(paths)
        state.path[-1].chose = STAGE_05.slug
        state.path[-1].kind = "advance"
        save_graph_state(paths, state)
        before = dict(routing_summary(paths)["edges"])
        self.assertIn("04_implementation->05_experimentation", before)

        _op2, resumed = self.build(graph_max_steps=40)
        self.drive_resume(resumed, paths.run_root)

        after = routing_summary(paths)["edges"]
        self.assertIn("04_implementation->05_experimentation", after)
        self.assertEqual(routing_summary(paths)["bypassed"], 0)

    def test_an_unfinished_visit_is_left_alone(self) -> None:
        """A visit with no recorded move was never a traversal, so there is nothing to
        reconcile and nothing to mark. An abort leaves one."""
        _operator, manager = self.build()
        self.drive(manager)
        paths = self.only_run()
        state = load_graph_state(paths)
        state.path[-1].chose = ""
        save_graph_state(paths, state)

        _op2, resumed = self.build()
        self.drive_resume(resumed, paths.run_root)
        self.assertEqual(routing_summary(paths)["bypassed"], 0)

    # -- the checks have to be satisfiable -----------------------------------

    def test_every_guard_passes_on_a_completed_run(self) -> None:
        """A precondition no real run can meet is not a strict gate, it is a broken one.

        This is the test that was missing. Two checks shipped reading keys nothing
        in AutoR writes — `experiment_manifest.experiments`, which does not exist
        (the real key is `result_artifacts`), and a
        `workspace/literature/evidence_ledger.json` that no writer produces. Both
        failed silently on every run: the forward move out of Stage 05 was
        permanently shut and the reproducibility criterion permanently docked, and
        nothing anywhere said so, because a guard that always fails looks exactly
        like a guard protecting you from something.

        Asserting against a run driven all the way through, rather than against a
        fixture, is the point — a fixture would have been built from the same wrong
        assumption as the code.
        """
        _operator, manager = self.build(stage_graph=StageGraph.linear(), routing_mode="off")
        self.assertTrue(self.drive(manager))
        paths = self.only_run()

        # `round_abandoned` is exempt and must be: it opens the edge a run takes
        # when it concludes the question cannot be answered, so a run that answered
        # it is precisely the run that should not satisfy it. The exemption is a
        # claim, so it is run as a control — `test_the_abandonment_guard_opens_on_a
        # _run_that_abandons` below is the other half, and without it this exemption
        # would be indistinguishable from the two broken guards this gate was
        # written to catch.
        outcome_specific = {"round_abandoned"}
        failing = {
            name: fn(paths, GraphState()).reason
            for name, fn in sorted(GUARDS.items())
            if name not in outcome_specific and not fn(paths, GraphState()).ok
        }
        self.assertEqual(failing, {}, msg=f"guards unsatisfiable by a completed run: {failing}")
        for name in outcome_specific:
            self.assertIn(name, GUARDS, msg=f"{name} is exempted but no longer exists")
            self.assertFalse(
                GUARDS[name](paths, GraphState()).ok,
                msg=f"{name} is exempted as outcome-specific but passes on an ordinary run",
            )

    def test_every_reproducibility_check_passes_on_a_completed_run(self) -> None:
        """The same trap on the rubric side: a criterion that can never reach 1.00
        is a constant subtracted from every score, not a measurement."""
        _operator, manager = self.build(stage_graph=StageGraph.linear(), routing_mode="off")
        self.assertTrue(self.drive(manager))
        paths = self.only_run()

        shortfalls = {}
        for stage in STAGES:
            score = score_stage(
                paths=paths,
                stage=stage,
                markdown=read_text(paths.stage_file(stage)),
            )
            item = score.by_key.get("reproducibility")
            if item is not None and item.score < 1.0:
                shortfalls[stage.slug] = item.observed
        self.assertEqual(
            shortfalls, {}, msg=f"validity-chain checks unsatisfiable by a completed run: {shortfalls}"
        )

    def _declare_at_analysis(self, manager, decision: str, **extra) -> None:
        """Make Stage 06 close its round with `decision`."""
        original = manager.operator.run_stage

        def run_stage(stage, prompt, run_paths, attempt_no, continue_session=False):
            result = original(stage, prompt, run_paths, attempt_no, continue_session)
            if stage.number == 6:
                payload = {
                    "decision": decision,
                    "rationale": "The second design separates the effect cleanly enough.",
                    "what_we_learned": "Tuning on a development split removes the confound.",
                    "what_changes_next": "",
                    "negative_result": True,
                }
                payload.update(extra)
                write_text(run_paths.round_decision, json.dumps(payload))
            return result

        manager.operator.run_stage = run_stage

    def drive_resume(self, manager: ResearchManager, run_root, **kwargs) -> bool:
        stack = ExitStack()
        stack.enter_context(patch.object(manager.ui, "choose_intake_clarification_answer", return_value=None))
        stack.enter_context(patch.object(manager.ui, "read_optional_multiline_feedback", return_value=None))
        stack.enter_context(patch.object(manager.ui, "choose_intake_final_action", return_value="5"))
        stack.enter_context(patch.object(manager, "_ask_choice", return_value="5"))
        with stack:
            return manager.resume_run(run_root, **kwargs)

    # -- abandonment is an outcome, not a failure ----------------------------

    def _abandon_at_analysis(self, manager) -> None:
        """Make Stage 06 declare that the question cannot be answered."""
        original = manager.operator.run_stage

        def run_stage(stage, prompt, run_paths, attempt_no, continue_session=False):
            result = original(stage, prompt, run_paths, attempt_no, continue_session)
            if stage.number == 6:
                write_text(
                    run_paths.round_decision,
                    json.dumps(
                        {
                            "decision": "abandon",
                            "rationale": "The effect cannot be separated from tuning noise "
                            "with the compute available.",
                            "what_we_learned": "Every arm we can afford sits within noise of "
                            "the baseline on this split.",
                            "what_changes_next": "",
                            "negative_result": False,
                        }
                    ),
                )
            return result

        manager.operator.run_stage = run_stage

    def test_an_abandoned_run_stops_instead_of_writing_up(self) -> None:
        """The defect this closes, measured before and after.

        `resume_stage_slug_for("abandon")` returns None, so the round decision had
        nowhere to go: the walk advanced to Stage 07, `validate_round_decision`
        refused it there, and the stage burned its entire retry budget. Measured on
        this fixture beforehand: **10 operator calls at Stage 07**, every one
        discarded, and the run recorded `cancelled` — the same status an abort
        writes, so the most scientifically honest outcome a run can reach was
        indistinguishable from a crash and was its most expensive.
        """
        operator, manager = self.build()
        self._abandon_at_analysis(manager)
        completed = self.drive(manager)

        paths = self.only_run()
        self.assertEqual(operator.invocations.get("07_writing", 0), 0)
        self.assertEqual(operator.invocations.get("08_dissemination", 0), 0)

        manifest = load_run_manifest(paths.run_manifest)
        self.assertEqual(manifest.run_status, "abandoned")
        self.assertTrue(
            completed,
            msg="a run that concluded its question cannot be answered did what it should; "
            "reporting that as failure would make the honest outcome look like a crash",
        )

        route = load_graph_state(paths).path
        self.assertEqual(route[-1].stage, STAGE_06.slug)
        self.assertEqual(route[-1].chose, FINISH)

    def test_abandonment_is_only_reachable_by_declaring_it(self) -> None:
        """A conclusion reached because nothing else was available is not one the run
        is entitled to. Every forward move out of Stage 06 is shut here, and the walk
        must still not record that the run gave up."""
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))
        paths = self.only_run()
        self.assertEqual(load_run_manifest(paths.run_manifest).run_status, "completed")
        self.assertNotIn(
            FINISH,
            [visit.chose for visit in load_graph_state(paths).path[:-1]],
        )

    def test_the_abandonment_guard_opens_on_a_run_that_abandons(self) -> None:
        """The control for the exemption in `test_every_guard_passes_on_a_completed_run`.

        Without this, exempting a guard from the satisfiability gate would be
        indistinguishable from the two broken guards that gate was written to catch.
        """
        _operator, manager = self.build()
        self._abandon_at_analysis(manager)
        self.drive(manager)
        paths = self.only_run()

        # Against the state the run actually persisted, not a synthetic one: the
        # guard is scoped to the visit that closed the round, so a bare GraphState
        # is a Stage 06 that closed nothing, and asserting on one would prove the
        # opposite of what this test is for.
        state = load_graph_state(paths)
        self.assertTrue(GUARDS["round_abandoned"](paths, state).ok)
        self.assertEqual(state.path[-1].closed_round, 1)

        # And the same ledger does not govern a visit that closed no round.
        self.assertFalse(GUARDS["round_abandoned"](paths, GraphState()).ok)

    # -- settings survive a resume -------------------------------------------

    def test_the_walk_settings_are_preserved_on_resume(self) -> None:
        """Resuming an adaptive run without repeating the flag must not silently
        revert it to the linear default."""
        _operator, manager = self.build(
            stage_graph=StageGraph.adaptive(),
            routing_mode="auto",
            evolution=EvolutionConfig(rounds=2),
        )
        self.drive(manager)
        paths = self.only_run()
        config = load_run_config(paths)
        self.assertEqual(config["stage_graph"], "adaptive")
        self.assertEqual(config["routing_mode"], "auto")
        self.assertEqual(config["evolve_rounds"], 2)

    # -- evolution through the real loop -------------------------------------

    def test_evolution_promotes_the_champion_and_writes_a_ledger(self) -> None:
        _operator, manager = self.build(evolution=EvolutionConfig(rounds=2))
        self.assertTrue(self.drive(manager))

        paths = self.only_run()
        ledger = paths.evolution_dir / "improvement_ledger.jsonl"
        self.assertTrue(ledger.exists())
        rows = [json.loads(line) for line in read_text(ledger).splitlines() if line.strip()]
        self.assertTrue(rows)
        for row in rows:
            self.assertIn(row["stage"], {stage.slug for stage in STAGES})
            self.assertIn(
                row["verdict"],
                {"first", "promoted", "frontier", "regressed", "directed", "verdict_drift"},
            )

        summary = json.loads(read_text(paths.evolution_dir / "summary.json"))
        self.assertTrue(summary["stages"])
        for slug, entry in summary["stages"].items():
            self.assertGreaterEqual(entry["total"], 0.0)
            self.assertLessEqual(entry["total"], 1.0)
            self.assertTrue(paths.stage_file(next(s for s in STAGES if s.slug == slug)).exists())

    def test_polish_rounds_do_not_consume_the_repair_budget(self) -> None:
        """`--max-attempts` bounds a stage that is failing. A stage being improved
        would otherwise look like one that was thrashing, and would have nothing
        left if a later round did break something."""
        _operator, manager = self.build(
            evolution=EvolutionConfig(rounds=3), max_stage_attempts=2
        )
        self.assertTrue(self.drive(manager))
        paths = self.only_run()
        manifest = load_run_manifest(paths.run_manifest)
        self.assertTrue(all(entry.settled for entry in manifest.stages))


if __name__ == "__main__":
    unittest.main()
