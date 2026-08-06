"""The stage topology, and the moves it refuses.

The default graph has to behave exactly like the list it replaced — that is the
first test here and the reason the linear topology is a real graph rather than a
branch around one. The rest are about the adaptive topology, where the run picks
its own route and the interesting question is not which moves it can make but
which it cannot.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.stage_graph import (
    DEFAULT_MAX_VISITS,
    FINISH,
    GUARDS,
    Edge,
    GraphState,
    StageGraph,
    Visit,
    enter,
    format_route,
    leave,
    load_graph_state,
    save_graph_state,
    stage_for_slug,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text
from tests import prereg_support


class LinearTopologyTests(unittest.TestCase):
    """The default must be the old pipeline, edge for edge."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)

    def test_the_default_graph_walks_01_through_08_and_finishes(self) -> None:
        graph = StageGraph.linear()
        state = GraphState()
        route = []
        current = STAGES[0].slug
        while current != FINISH:
            route.append(current)
            move = graph.default_move(self.paths, current, state)
            self.assertIsNotNone(move, msg=f"no move out of {current} on the default graph")
            current = move.target
        self.assertEqual(route, [stage.slug for stage in STAGES])

    def test_no_forward_move_on_the_linear_graph_is_guarded(self) -> None:
        """A guard on the only edge out of a node could only ever halt the run, and
        the condition it would halt on is already a stage validation error with a
        better message. Two gates over one condition is one too many."""
        for edge in StageGraph.linear().edges:
            self.assertEqual(edge.guard, "always", msg=f"{edge.source}->{edge.target} is guarded")

    def test_every_registered_guard_is_wired_to_an_edge(self) -> None:
        """A guard nobody wired is a check nobody runs.

        It reads as protection in a review and enforces nothing, and the adaptive
        topology is the only place guards apply — so an orphan is invisible until
        someone assumes the condition is being checked.
        """
        wired = {edge.guard for edge in StageGraph.adaptive().edges}
        self.assertEqual(set(GUARDS) - wired, set())

    def test_an_edge_with_an_unknown_guard_is_refused_at_construction(self) -> None:
        """A guard name that does not resolve would silently pass."""
        with self.assertRaises(ValueError):
            Edge("06_analysis", "07_writing", "advance", "why", guard="looks_fine")

    def test_an_edge_with_an_unhandled_kind_is_refused_at_construction(self) -> None:
        """A revisit is budgeted and justified differently from an advance, and the
        archive learns their payoffs separately. An unknown kind would be treated
        as neither."""
        with self.assertRaises(ValueError):
            Edge("06_analysis", "07_writing", "sideways", "why")

    def test_an_empty_run_offers_every_linear_move(self) -> None:
        state = GraphState()
        for stage in STAGES:
            self.assertTrue(
                StageGraph.linear().admissible_moves(self.paths, stage.slug, state),
                msg=f"{stage.slug} has no live move on an empty run",
            )


class AdaptiveTopologyTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        self.graph = StageGraph.adaptive()

    def targets(self, slug: str, state: GraphState | None = None) -> set[str]:
        return {
            move.target
            for move in self.graph.admissible_moves(self.paths, slug, state or GraphState())
        }

    # -- what the graph refuses ---------------------------------------------

    def test_writing_is_closed_until_every_hypothesis_has_a_verdict(self) -> None:
        """The gate a self-routing agent must not be able to talk past.

        Writing up before adjudication is how a manuscript claims a result the run
        never established, and an agent asked where to go next will reach for the
        deliverable.
        """
        self.assertNotIn("07_writing", self.targets("06_analysis"))

        self.build_adjudicated_run()
        self.assertIn("07_writing", self.targets("06_analysis"))

    def test_a_blocked_move_says_which_hypothesis_is_missing_a_verdict(self) -> None:
        """A guard that fails without saying what would satisfy it turns the
        routing decision into a guess, and the agent into a random walker."""
        self.build_adjudicated_run(adjudicate=False)
        blocked = next(
            move
            for move in self.graph.moves(self.paths, "06_analysis", GraphState())
            if move.target == "07_writing"
        )
        self.assertFalse(blocked.admissible)
        self.assertIn(prereg_support.HYPOTHESIS_ID, blocked.blocked_because)

    def test_a_blocked_move_is_still_shown_to_the_router(self) -> None:
        """Hiding it would be the obvious design and it is the wrong one: an agent
        that can see why writing is closed routes to what opens it."""
        moves = self.graph.moves(self.paths, "06_analysis", GraphState())
        self.assertIn("07_writing", {move.target for move in moves})
        rendered = self.graph.describe_for_prompt(moves)
        self.assertIn("07_writing", rendered)
        self.assertIn("**no**", rendered)

    def test_a_stage_cannot_be_entered_past_its_visit_budget(self) -> None:
        state = GraphState()
        for _ in range(DEFAULT_MAX_VISITS):
            state.path.append(Visit(stage="05_experimentation", entered_at="t"))
        self.assertNotIn("05_experimentation", self.targets("06_analysis", state))

    def test_the_step_limit_stops_the_walk_wherever_it_is(self) -> None:
        state = GraphState(max_steps=2)
        state.path.extend(
            [Visit(stage="01_literature_survey", entered_at="t"), Visit(stage="02_hypothesis_generation", entered_at="t")]
        )
        self.assertEqual(self.targets("02_hypothesis_generation", state), set())

    def test_a_revisit_repeating_its_own_reason_is_recognised(self) -> None:
        """Going back to Stage 05 a third time because 'more repeats are needed' is
        not iteration. The check is on the reason, so a *different* reason is never
        penalised for the earlier trip."""
        state = GraphState()
        state.path.append(
            Visit(
                stage="06_analysis",
                entered_at="t",
                chose="05_experimentation",
                kind="revisit",
                reason="Only one seed was run, so H1 cannot be decided.",
            )
        )
        self.assertTrue(
            self.graph.repeats_a_previous_reason(
                state, "05_experimentation", "only one seed was run, so h1 cannot be decided."
            )
        )
        self.assertFalse(
            self.graph.repeats_a_previous_reason(
                state, "05_experimentation", "The ablation condition was never run at all."
            )
        )

    def test_final_stage_prunes_moves_past_it(self) -> None:
        """`--final-stage 07` means the run does not owe a dissemination package, so
        the edge into one must not be on the menu."""
        stage_07 = stage_for_slug("07_writing")
        targets = {
            move.target
            for move in self.graph.moves(
                self.paths, "07_writing", GraphState(), final_stage=stage_07
            )
        }
        self.assertNotIn("08_dissemination", targets)

    # -- what the graph allows ----------------------------------------------

    def test_analysis_can_send_the_run_back_to_the_experiment(self) -> None:
        """The move a linear list cannot express, and the reason the graph exists."""
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        self.assertIn("05_experimentation", self.targets("06_analysis"))

    def test_the_default_move_out_of_every_adaptive_node_is_the_forward_one(self) -> None:
        """A refusal or a routing failure degrades to the old pipeline, not a stall."""
        self.build_adjudicated_run()
        for index, stage in enumerate(STAGES):
            expected = STAGES[index + 1].slug if index + 1 < len(STAGES) else FINISH
            move = self.graph.default_move(self.paths, stage.slug, GraphState())
            self.assertIsNotNone(move, msg=f"no default move out of {stage.slug}")
            self.assertEqual(move.target, expected, msg=f"default out of {stage.slug}")

    # -- state ---------------------------------------------------------------

    def test_the_path_survives_a_reload(self) -> None:
        state = load_graph_state(self.paths)
        enter(self.paths, state, STAGES[0])
        leave(
            self.paths,
            state,
            chose="02_hypothesis_generation",
            kind="advance",
            reason="The survey named the gap.",
            default_choice="02_hypothesis_generation",
            agent_directed=True,
            score_total=0.71,
        )
        reloaded = load_graph_state(self.paths)
        self.assertEqual(len(reloaded.path), 1)
        self.assertEqual(reloaded.path[0].chose, "02_hypothesis_generation")
        self.assertTrue(reloaded.path[0].agent_directed)
        self.assertAlmostEqual(reloaded.path[0].score_total or 0.0, 0.71)

    def test_the_route_marks_backward_moves(self) -> None:
        state = GraphState(
            path=[
                Visit(stage="06_analysis", entered_at="t", chose="05_experimentation", kind="revisit"),
                Visit(stage="05_experimentation", entered_at="t", chose=FINISH, kind="finish"),
            ]
        )
        rendered = format_route(state)
        self.assertIn("↩", rendered)
        self.assertIn("finish", rendered)

    def test_explicit_limits_override_what_was_stored(self) -> None:
        save_graph_state(self.paths, GraphState(max_steps=4, max_visits=1))
        state = load_graph_state(self.paths, max_steps=11, max_visits=2)
        self.assertEqual((state.max_steps, state.max_visits), (11, 2))

    def test_an_unknown_topology_is_refused_rather_than_defaulted(self) -> None:
        with self.assertRaises(ValueError):
            StageGraph.named("whatever-sounds-good")

    # -- helpers -------------------------------------------------------------

    def build_adjudicated_run(self, *, adjudicate: bool = True) -> None:
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.write_experimental_protocol(self.paths)
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        write_text(self.paths.data_dir / "splits.json", json.dumps({"test": [1, 2]}))
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"acc": 0.7}))
        write_text(self.paths.figures_dir / "fig.png", "x" * 64)
        write_text(self.paths.report_file, "# Report\n\nBody.\n")
        write_text(
            self.paths.experiment_manifest,
            json.dumps({"experiments": [{"id": "e1", "command": "python run.py"}]}),
        )
        prereg_support.freeze_preregistration(self.paths)
        if adjudicate:
            prereg = json.loads(self.paths.preregistration.read_text(encoding="utf-8"))
            write_text(
                self.paths.hypothesis_outcomes,
                json.dumps(
                    {
                        "preregistration_digest": prereg["digest"],
                        "outcomes": [
                            {
                                "id": prereg_support.HYPOTHESIS_ID,
                                "verdict": "refuted",
                                "rationale": "The gap did not clear the decision rule.",
                                "evidence": ["results/metrics.json"],
                            }
                        ],
                    }
                ),
            )


if __name__ == "__main__":
    unittest.main()
