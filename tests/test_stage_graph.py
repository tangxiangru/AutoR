"""The stage topology, and the moves it refuses.

The default graph has to behave exactly like the list it replaced — that is the
first test here and the reason the linear topology is a real graph rather than a
branch around one. The rest are about the adaptive topology, where the run picks
its own route and the interesting question is not which moves it can make but
which it cannot.
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

from src.stage_graph import (
    BLOCK_KINDS,
    DEFAULT_MAX_VISITS,
    FINISH,
    GUARDS,
    Edge,
    GraphState,
    GuardResult,
    Move,
    StageGraph,
    Visit,
    block_census,
    enter,
    format_block_census,
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

    def test_no_advance_on_the_linear_graph_is_guarded(self) -> None:
        """A guard on the only way *onward* from a node could only ever halt the run,
        and the condition it would halt on is already a stage validation error with a
        better message. Two gates over one condition is one too many.

        The abandonment terminal is exempt and has to be: it is not the way onward,
        it is a second exit whose guard is the entire point of it. A shut guard there
        removes the edge rather than halting anything — which is the case on every
        run that did not abandon, i.e. almost all of them.
        """
        for edge in StageGraph.linear().edges:
            if edge.kind == "finish" and edge.guard != "always":
                continue
            self.assertEqual(
                edge.guard, "always", msg=f"{edge.source}->{edge.target} is guarded"
            )

    def test_the_linear_graph_still_has_exactly_one_way_onward_from_each_node(self) -> None:
        """The exemption above is only safe if it is narrow. `linear` may gain
        terminals; it may not gain a choice of direction."""
        graph = StageGraph.linear()
        for stage in STAGES:
            onward = [e for e in graph.out_edges(stage.slug) if e.kind == "advance"]
            self.assertLessEqual(len(onward), 1, msg=f"{stage.slug} has {len(onward)} advances")
            self.assertEqual(
                [e for e in graph.out_edges(stage.slug) if e.kind == "revisit"],
                [],
                msg=f"{stage.slug} has a backward edge on the linear topology",
            )

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


class WhatEdgePriorityActuallyReachesTests(unittest.TestCase):
    """What the archive's only learnable value can and cannot change.

    `Variant.edge_priority` is the whole output of the cross-run learner, and the
    honest statement of its reach is narrow: it orders the move table the agent is
    shown, and that is currently all of it. `default_move` filters to forward edges
    before ranking, and at most one is ever live at a node: seven of the eight have a
    single forward edge, and 06_analysis's second — the abandonment terminal — is shut
    unless a round concluded `abandon` and preempts everything else when it is open. So
    no assignment of priorities changes what a run does when nobody is steering.

    Both halves are asserted on purpose. A test that only pinned "no difference"
    would stay green if someone deleted `default_move` entirely; pinning that the
    menu order *does* move is what makes this a measurement of a live channel rather
    than a tautology about a dead one.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)

    def _sweep(self, graph: StageGraph):
        from src.archive import Variant

        rng = random.Random(20260806)
        keys = [f"{e.source}->{e.target}" for e in graph.edges]
        default_changes = order_changes = comparisons = 0
        for _ in range(50):
            priorities = {key: rng.randint(0, 6) for key in keys}
            mutated = Variant("sweep", graph.name, edge_priority=priorities).apply_to(graph)
            for stage in STAGES:
                comparisons += 1
                before = graph.default_move(self.paths, stage.slug, GraphState())
                after = mutated.default_move(self.paths, stage.slug, GraphState())
                if (before is None) != (after is None) or (
                    before is not None and after is not None and before.target != after.target
                ):
                    default_changes += 1
                if [e.target for e in graph.out_edges(stage.slug)] != [
                    e.target for e in mutated.out_edges(stage.slug)
                ]:
                    order_changes += 1
        return default_changes, order_changes, comparisons

    def test_priority_never_changes_what_the_run_does_by_default(self) -> None:
        changed, _order, comparisons = self._sweep(StageGraph.adaptive())
        self.assertEqual(
            changed,
            0,
            msg=f"{changed}/{comparisons} default moves moved; the docs say priority orders the "
            "menu, not the walk",
        )

    def test_priority_does_change_the_menu_the_agent_is_shown(self) -> None:
        _changed, order, comparisons = self._sweep(StageGraph.adaptive())
        self.assertGreater(
            order,
            0,
            msg=f"0/{comparisons} menu orderings moved: edge priority now reaches nothing at all, "
            "and the archive is learning a value with no consumer",
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

    def test_final_stage_takes_the_move_past_it_off_the_menu(self) -> None:
        """`--final-stage 07` means the run does not owe a dissemination package."""
        stage_07 = stage_for_slug("07_writing")
        moves = self.graph.moves(
            self.paths, "07_writing", GraphState(), final_stage=stage_07
        )
        self.assertNotIn("08_dissemination", [move.target for move in moves])
        # Reaching the stage the caller asked for is a completion, so the advance past
        # it is rendered as the finish edge it amounts to rather than as a dead one.
        # Recorded as a pruned advance the node had no live forward move at all,
        # `default_move` returned None, and `StageRouter.choose` halted without asking
        # — discarding the live backward edges at 07, which is the node where "is any
        # written claim unsupported by the analysis?" gets decided.
        finish = next(move for move in moves if move.target == FINISH)
        self.assertTrue(finish.admissible)
        self.assertEqual(finish.edge.kind, "finish")

    def test_final_stage_ends_the_walk_instead_of_sending_it_backwards(self) -> None:
        """The bug that dropping the edge caused, at every final stage.

        `moves()` used to omit a pruned edge entirely, so the node looked like one
        with no forward move at all and `default_move` fell through to the backward
        edges. On the adaptive topology — the default — `--final-stage 07` therefore
        sent the run back to Stage 06 and kept going until a budget stopped it.
        Measured before the fix: final-stage 05 went to 04, 06 went to 05, 07 went to
        06, all revisits, on the graph a default run walks.

        A pruned edge is the caller's own instruction. It is not a fact about the
        research, and unlike a guard there is nothing to route around.
        """
        for number in (5, 6, 7):
            final = next(stage for stage in STAGES if stage.number == number)
            with self.subTest(final_stage=final.slug):
                default = self.graph.default_move(
                    self.paths, final.slug, GraphState(), final_stage=final
                )
                self.assertIsNotNone(default, msg=f"--final-stage {final.slug} halted")
                self.assertEqual(
                    default.target,
                    FINISH,
                    msg=f"--final-stage {final.slug} did not end the walk",
                )

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

    def test_a_visit_written_before_the_choice_set_existed_still_loads(self) -> None:
        """Absent means empty, not assumed. A `stage_graph.json` from before these
        fields is a visit with no recorded choice set, which is exactly what it is
        and what every estimator should exclude."""
        legacy = {
            "stage": "06_analysis",
            "entered_at": "t",
            "chose": "07_writing",
            "kind": "advance",
        }
        visit = Visit.from_dict(legacy)
        self.assertEqual(visit.offered, ())
        self.assertEqual(visit.blocked, {})
        self.assertFalse(visit.bypassed)

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


class BlockCensusTests(unittest.TestCase):
    """What the walk was offered, and what shut the rest.

    The route says where the run went. Every visit also records the menu it chose
    from and why each closed edge was closed; `routing_summary` published the menu
    under `decisions` and never the closures, and nothing totalled either per edge
    over the whole walk. These tests are about the two ways that record can be
    misread: pooling an edge that was never offered with one that was refused, and
    pooling an operator's intervention with either.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    @staticmethod
    def visit(stage: str, *, offered=(), blocked=None, bypassed: bool = False, chose: str = "") -> Visit:
        return Visit(
            stage=stage,
            entered_at="t",
            chose=chose,
            offered=tuple(offered),
            blocked=dict(blocked or {}),
            bypassed=bypassed,
        )

    def test_a_block_is_counted_per_edge_and_per_kind(self) -> None:
        """The unit is the edge, not the target: the same target reached from two
        nodes is two different moves, and pooling them makes a guard that shuts one
        of them look twice as strict as it is."""
        census = block_census(
            [
                self.visit("06_analysis", offered=("05_experimentation",), blocked={"07_writing": "guard"}),
                self.visit("06_analysis", offered=("05_experimentation",), blocked={"07_writing": "guard"}),
                self.visit("08_dissemination", blocked={"07_writing": "visits"}),
            ]
        )
        self.assertEqual(
            census.blocked,
            {
                "06_analysis->07_writing": {"guard": 2},
                "08_dissemination->07_writing": {"visits": 1},
            },
        )
        self.assertEqual(census.offered, {"06_analysis->05_experimentation": 2})
        self.assertEqual(census.visits, 3)

    def test_the_kind_tally_is_the_sum_of_the_per_edge_columns(self) -> None:
        """Derived, so the two numbers cannot drift. A separate tally kept beside the
        per-edge one is a second encoding of one fact, and the one nobody updates is
        the one that gets quoted."""
        census = block_census(
            [
                self.visit("06_analysis", blocked={"07_writing": "guard"}),
                self.visit("06_analysis", blocked={"07_writing": "guard"}),
                self.visit("07_writing", blocked={"08_dissemination": "steps"}),
            ]
        )
        # Three blocks on two edges: the tally counts blocks, not edges.
        self.assertEqual(census.kinds, {"guard": 2, "steps": 1})
        self.assertEqual(census.blocks, 3)
        self.assertEqual(len(census.blocked), 2)
        self.assertEqual(
            census.blocks,
            sum(count for per_kind in census.blocked.values() for count in per_kind.values()),
        )

    def test_a_visit_with_no_choice_set_is_unobserved_rather_than_unblocked(self) -> None:
        """The distinction the whole census rests on.

        A bypass — `/back`, a rollback, a research round's own jump — arrives with
        the move already made: no guard was evaluated and nothing was on offer.
        Counted as a visit at which nothing was blocked, an operator's intervention
        would enter the census as evidence that the graph was wide open there.
        """
        census = block_census(
            [
                self.visit("06_analysis", chose="05_experimentation", bypassed=True),
                self.visit("05_experimentation", offered=("06_analysis",), blocked={"04_implementation": "visits"}),
            ]
        )
        self.assertEqual(census.unobserved, 1)
        self.assertEqual(census.bypassed, 1)
        self.assertEqual(census.offered, {"05_experimentation->06_analysis": 1})
        self.assertEqual(census.blocked, {"05_experimentation->04_implementation": {"visits": 1}})
        self.assertNotIn("06_analysis->05_experimentation", census.offered)

    def test_a_bypass_that_did_record_a_choice_set_is_counted_on_both_axes(self) -> None:
        """Not every bypass is choice-set-less, and the two counters say so.

        A resume that starts somewhere other than where the last visit was heading
        flags a visit the router had already closed with a full menu. Its guards
        were evaluated, so its offers and blocks are real observations about the
        graph; the move out of it was still the operator's. One counter would have
        to throw away one of those two facts.
        """
        census = block_census(
            [
                self.visit(
                    "06_analysis",
                    chose=FINISH,
                    offered=("05_experimentation",),
                    blocked={"07_writing": "guard"},
                    bypassed=True,
                )
            ]
        )
        self.assertEqual(census.bypassed, 1)
        self.assertEqual(census.unobserved, 0)
        self.assertEqual(census.offered, {"06_analysis->05_experimentation": 1})
        self.assertEqual(census.blocked, {"06_analysis->07_writing": {"guard": 1}})

    def test_a_visit_from_before_the_choice_set_existed_is_not_read_as_an_open_node(self) -> None:
        """A `stage_graph.json` written before `offered` and `blocked` existed loads
        as a visit with neither. It is no observation at all, and the denominator has
        to say so rather than let an old record read as a run nothing ever blocked."""
        census = block_census([Visit.from_dict({"stage": "06_analysis", "chose": "07_writing"})])
        self.assertEqual((census.visits, census.unobserved), (1, 1))
        self.assertEqual(census.offered, {})
        self.assertEqual(census.blocked, {})

    def test_a_visit_with_no_stage_has_no_edge_to_attribute_anything_to(self) -> None:
        """`GraphState.from_dict` takes any mapping, and an entry with no stage would
        otherwise be counted under the edge key `->07_writing`."""
        census = block_census([Visit.from_dict({"blocked": {"07_writing": "guard"}})])
        self.assertEqual(census.blocked, {})
        self.assertEqual(census.unobserved, 1)

    def test_the_census_of_a_real_walk_names_the_edges_the_graph_offered(self) -> None:
        """Against the shipped adaptive topology rather than a hand-built path, so
        the keys are edges that exist."""
        graph = StageGraph.adaptive()
        state = GraphState()
        moves = graph.moves(self.paths, "06_analysis", state)
        state.path.append(
            Visit(
                stage="06_analysis",
                entered_at="t",
                offered=tuple(sorted(move.target for move in moves if move.admissible)),
                blocked={move.target: move.blocked_kind for move in moves if move.blocked_kind},
            )
        )
        census = block_census(state.path)
        declared = {f"{edge.source}->{edge.target}" for edge in graph.edges}
        self.assertTrue(set(census.offered) | set(census.blocked))
        self.assertEqual((set(census.offered) | set(census.blocked)) - declared, set())
        # Nothing is adjudicated on an empty run, so writing is shut and the reason
        # is a guard rather than a budget.
        self.assertEqual(census.blocked.get("06_analysis->07_writing"), {"guard": 1})

    def test_the_rendering_says_what_was_offered_and_what_shut_the_rest(self) -> None:
        rendered = format_block_census(
            block_census(
                [self.visit("06_analysis", offered=("05_experimentation",), blocked={"07_writing": "guard"})]
            )
        )
        self.assertIn("06_analysis->05_experimentation", rendered)
        self.assertIn("06_analysis->07_writing", rendered)
        self.assertIn("guard 1", rendered)

    def test_an_empty_walk_says_so_rather_than_rendering_an_empty_census(self) -> None:
        self.assertIn("No choice set", format_block_census(block_census([])))

    # -- the refusal that keeps the census's arithmetic true -----------------

    def test_a_move_blocked_with_no_kind_is_refused_at_construction(self) -> None:
        """It would be inadmissible and counted under no heading: the route would
        show an edge the run could not take and the census would show nothing
        shutting it."""
        edge = StageGraph.adaptive().out_edges("06_analysis")[0]
        with self.assertRaises(ValueError):
            Move(edge, GuardResult(False, "shut"), "shut", "")

    def test_a_move_given_a_kind_but_no_reason_is_refused_at_construction(self) -> None:
        """The other direction, and the worse one: `admissible` reads the sentence,
        so the move would be offered to the agent *and* counted as blocked."""
        edge = StageGraph.adaptive().out_edges("06_analysis")[0]
        with self.assertRaises(ValueError):
            Move(edge, GuardResult(True, "fine"), "", "guard")

    def test_a_move_blocked_by_an_undeclared_kind_is_refused_at_construction(self) -> None:
        """The same refusal `Edge` makes about its kind. A kind outside
        `BLOCK_KINDS` would be tallied under a heading no reader can interpret, and
        `default_move` branches on exactly these names.

        The example used to be `"budget"`, which then became a kind and turned this
        into a test of nothing that failed loudly rather than quietly. The
        `assertNotIn` is so the next one says which half moved.
        """
        undeclared = "affordable"
        self.assertNotIn(undeclared, BLOCK_KINDS)
        edge = StageGraph.adaptive().out_edges("06_analysis")[0]
        with self.assertRaises(ValueError):
            Move(edge, GuardResult(False, "shut"), "shut", undeclared)

    def test_every_declared_kind_is_accepted(self) -> None:
        """The control. A refusal that rejects the vocabulary it is guarding would
        pass all three tests above and break every walk."""
        edge = StageGraph.adaptive().out_edges("06_analysis")[0]
        for kind in BLOCK_KINDS:
            self.assertFalse(Move(edge, GuardResult(False, "shut"), "shut", kind).admissible)
        self.assertTrue(Move(edge, GuardResult(True, "fine"), "", "").admissible)


if __name__ == "__main__":
    unittest.main()
