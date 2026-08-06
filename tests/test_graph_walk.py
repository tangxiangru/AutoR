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
from src.router import RoutingDecision
from src.stage_graph import FINISH, StageGraph, load_graph_state
from src.utils import STAGES, build_run_paths, load_run_config, read_text
from tests.test_manager_smoke import REPO_ROOT, ScriptedSmokeOperator


STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")
STAGE_06 = next(stage for stage in STAGES if stage.slug == "06_analysis")
STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")


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

    def drive(self, manager: ResearchManager, goal: str = "Walk the stage graph.") -> bool:
        stack = ExitStack()
        stack.enter_context(patch.object(manager.ui, "choose_intake_clarification_answer", return_value=None))
        stack.enter_context(patch.object(manager.ui, "read_optional_multiline_feedback", return_value=None))
        stack.enter_context(patch.object(manager.ui, "choose_intake_final_action", return_value="5"))
        stack.enter_context(patch.object(manager, "_ask_choice", return_value="5"))
        with stack:
            return manager.run(goal, venue="neurips_2025")

    def only_run(self):
        roots = sorted(path for path in self.runs_dir.iterdir() if path.is_dir())
        self.assertEqual(len(roots), 1)
        return build_run_paths(roots[0])

    # -- the default has to be what it always was ----------------------------

    def test_a_default_run_still_walks_01_through_08(self) -> None:
        """The regression that would matter most. A run that asked for nothing new
        must produce the same route it always did, through the new engine."""
        _operator, manager = self.build()
        self.assertTrue(self.drive(manager))

        paths = self.only_run()
        state = load_graph_state(paths)
        self.assertEqual([visit.stage for visit in state.path], [stage.slug for stage in STAGES])
        self.assertEqual(state.path[-1].chose, FINISH)
        self.assertFalse(any(visit.agent_directed for visit in state.path))
        self.assertEqual(load_run_config(paths)["stage_graph"], "linear")

    def test_a_default_run_never_calls_the_router(self) -> None:
        """`routing off` is the default, and a default that quietly spent a backend
        call per stage boundary would be a cost nobody asked for."""
        _operator, manager = self.build()
        with patch.object(manager.router, "_ask", side_effect=AssertionError("router was asked")):
            self.assertTrue(self.drive(manager))

    # -- the walk follows the router -----------------------------------------

    def test_a_backward_decision_sends_the_run_back(self) -> None:
        """The move a linear list cannot express, taken through the real loop."""
        _operator, manager = self.build(stage_graph=StageGraph.adaptive(), routing_mode="agent")
        sent_back = {"done": False}

        def choose(*, paths, stage, graph, state, score=None, final_stage=None):
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

        def choose(*, paths, stage, graph, state, score=None, final_stage=None):
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

        def choose(*, paths, stage, graph, state, score=None, final_stage=None):
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

    # -- settings survive a resume -------------------------------------------

    def test_the_walk_settings_are_preserved_on_resume(self) -> None:
        """Resuming an adaptive run without repeating the flag must not silently
        revert it to the linear default."""
        _operator, manager = self.build(
            stage_graph=StageGraph.adaptive(),
            routing_mode="auto",
            evolution=EvolutionConfig(enabled=True, rounds=2),
        )
        self.drive(manager)
        paths = self.only_run()
        config = load_run_config(paths)
        self.assertEqual(config["stage_graph"], "adaptive")
        self.assertEqual(config["routing_mode"], "auto")
        self.assertEqual(config["evolve_rounds"], 2)

    # -- evolution through the real loop -------------------------------------

    def test_evolution_promotes_the_champion_and_writes_a_ledger(self) -> None:
        _operator, manager = self.build(evolution=EvolutionConfig(enabled=True, rounds=2))
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
            evolution=EvolutionConfig(enabled=True, rounds=3), max_stage_attempts=2
        )
        self.assertTrue(self.drive(manager))
        paths = self.only_run()
        manifest = load_run_manifest(paths.run_manifest)
        self.assertTrue(all(entry.settled for entry in manifest.stages))


if __name__ == "__main__":
    unittest.main()
