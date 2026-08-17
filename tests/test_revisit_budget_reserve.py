"""The budget a backward edge may not spend, and the two measurements that sized it.

:data:`~src.stage_graph.DELIVERY_RESERVE` is a number, and a number chosen because it
looked reasonable is the defect this repository keeps shipping. It was sized against
two measurements and this file is both of them, plus the invariant that makes the new
block kind safe to add at all.

**The half the corpus could supply** is in ``tools/replay_revisit_reserve.py``, which
replays finished runs against the shipped predicate at every candidate reserve.
:class:`TheReplayInstrumentReadsARun` pins the instrument itself against a synthetic
run, because a table printed by an unchecked reader is not a measurement — the run
corpus lives outside the repository and no test here can reach it, so what the suite
can hold is that the reader turns a known walk and a known log into the known answer.

**The half it could not** is :class:`TheReserveIsTheUnitTheAbortNeeds`. The corpus's
one backward move was taken with the pool untouched, so no reserve of 0, 1 or 2 would
have reached it and the replay cannot separate them. What separates them is a property
of :meth:`~src.manager.ResearchManager._handle_unattended_stage_exhaustion`: driven at
the stage that writes the deliverable, it aborts the run on 0 units left and
auto-skips on 1. One unit is therefore exactly the quantity the observed ending
needed, and the smallest reserve that holds it back.

**The invariant** is :class:`TheRuleOnlyEverRemovesAMove`. A ``budget`` block is the
last clause of an ``elif`` chain, so it can only re-label a move that was admissible.
That is what makes it the same shape as the two rules already in the tree — the
archive may reorder which move is preferred and may never open a guarded edge, the
cross-model reviewer is a veto and never an override — and it is checked here over
every node of the shipped topology rather than argued in a comment.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.manager import ResearchManager
from src.router import StageRouter
from src.stage_graph import (
    BLOCK_KINDS,
    DELIVERY_RESERVE,
    GraphState,
    StageGraph,
    Visit,
    block_census,
    enter,
    revisit_would_strand_delivery,
)
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    WRITING_STAGE,
    build_run_paths,
    ensure_run_layout,
    read_text,
    write_text,
)

REPO = Path(__file__).resolve().parent.parent


def _load_instrument():
    """``tools/`` is not a package, so load the script the way the tree already does.

    Importing it by path rather than by name is how ``tests/test_rcb_trial_driver.py``
    reaches its tool, and it keeps this file independent of where the suite is run
    from — a namespace-package import would work from the repository root and fail
    anywhere else, which is the shape that lets an instrument's test quietly stop
    running.
    """
    path = REPO / "tools" / "replay_revisit_reserve.py"
    spec = importlib.util.spec_from_file_location("replay_revisit_reserve_tool", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    # Registered before it is executed: the module defines dataclasses, and
    # `dataclasses` resolves a field's annotations through `sys.modules[__module__]`.
    # Left out, the class body raises `AttributeError` on `None.__dict__` and the
    # failure names dataclasses rather than this loader.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


REPLAY = _load_instrument()


class AlwaysTTY(io.StringIO):
    """A stream that claims to be a terminal, like the stdin a harness inherits."""

    def isatty(self) -> bool:
        return True


class StubOperator:
    model = "stub-model"
    backend_name = "claude"


class _FakeRoutingOperator:
    """The two private seams `StageRouter` drives a backend through.

    Serving the boundary rather than stubbing `choose` keeps the menu construction
    under test, which is the half the mutation escaped through.
    """

    fake_mode = False

    def __init__(self, response: str) -> None:
        self.response = response

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
        return (["fake-backend"], paths.run_root, None)

    def _run_streaming_command(self, **kwargs):
        return (0, self.response, "", None, {})


def _run_paths(root: Path):
    paths = build_run_paths(root / "runs" / "run_0001")
    ensure_run_layout(paths)
    write_text(paths.user_input, "goal")
    write_text(paths.memory, "# Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")
    return paths


class TheReserveIsTheUnitTheAbortNeeds(unittest.TestCase):
    """What one unit of the pool is worth at the stage that writes the deliverable.

    This is the measurement :data:`~src.stage_graph.DELIVERY_RESERVE` is read off, and
    it is a property of the manager rather than of any corpus: the exhaustion handler
    branches on ``len(auto_skipped_stages) >= max_auto_skips`` and, at the deliverable
    stage, the spent branch has nowhere to route. So the pool being empty *is* the
    abort, and the pool holding one is a skip and a continuation.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _continue_with(self, units_left: int, *, pool: int = 3) -> tuple[bool, str]:
        """Exhaust the writing stage with ``units_left`` of ``pool`` unspent."""
        paths = _run_paths(self.root / f"left{units_left}")
        manager = ResearchManager(
            project_root=REPO,
            runs_dir=self.root / f"left{units_left}" / "runs",
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY(), interactive=False),
            unattended=True,
            max_auto_skips=pool,
        )
        manager.auto_skipped_stages = [stage.slug for stage in STAGES[: pool - units_left]]
        continued = manager._handle_unattended_stage_exhaustion(
            paths=paths, stage=WRITING_STAGE, attempt_no=8, last_validation_errors=[]
        )
        return continued, read_text(paths.logs)

    def test_an_empty_pool_at_the_deliverable_stage_aborts_the_run(self) -> None:
        """The measured ending of both cancelled runs of the first live trial."""
        continued, logs = self._continue_with(0)
        self.assertFalse(continued)
        self.assertIn("unattended_abort", logs)

    def test_one_unit_turns_that_abort_into_a_skip_and_a_continuation(self) -> None:
        """And this is why the reserve is one rather than zero.

        Zero would refuse a backward edge only once the pool is already empty, which
        is after the branch that decides has gone the other way.
        """
        continued, logs = self._continue_with(1)
        self.assertTrue(continued)
        self.assertIn("unattended_auto_skip", logs)
        self.assertNotIn("unattended_abort", logs)

    def test_a_second_unit_buys_nothing_the_first_did_not(self) -> None:
        """Why the reserve is one rather than two.

        Two units and one unit produce the same ending, so the second is held back
        against no measured need — and the replay prices holding it at better than
        twice the withdrawn offers.
        """
        self.assertEqual(self._continue_with(1)[0], self._continue_with(2)[0])

    def test_the_reserve_is_the_unit_the_abort_needs(self) -> None:
        """The three rows above, as the one comparison that sizes the constant.

        The smallest ``units_left`` at which the run survives is the quantity a
        backward edge must not be able to consume, and that is the reserve.
        """
        survives = [left for left in (0, 1, 2, 3) if self._continue_with(left)[0]]
        self.assertEqual(min(survives), DELIVERY_RESERVE)


class ThePredicateIsTheWholeRule(unittest.TestCase):
    def test_a_pool_at_or_below_the_reserve_strands_delivery(self) -> None:
        self.assertTrue(revisit_would_strand_delivery(0))
        self.assertTrue(revisit_would_strand_delivery(DELIVERY_RESERVE))

    def test_a_pool_one_above_the_reserve_does_not(self) -> None:
        """A revisit costs at most one unit before the run is back where it started,
        so a pool holding the reserve *and* that unit is not stranded."""
        self.assertFalse(revisit_would_strand_delivery(DELIVERY_RESERVE + 1))

    def test_the_reserve_is_a_parameter_the_instrument_can_sweep(self) -> None:
        """The replay sizes the constant by varying it, so it must be varyable."""
        self.assertFalse(revisit_would_strand_delivery(1, reserve=0))
        self.assertTrue(revisit_would_strand_delivery(1, reserve=1))
        self.assertTrue(revisit_would_strand_delivery(2, reserve=2))


class TheRuleOnlyEverRemovesAMove(unittest.TestCase):
    """The invariant that makes a new block kind safe: it can only subtract.

    Checked over every node of the shipped adaptive topology rather than at the one
    node the trial happened to reach.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = _run_paths(Path(self._tmp.name))
        self.graph = StageGraph.adaptive()

    def _moves(self, slug: str, skips_left: int | None):
        return self.graph.moves(self.paths, slug, GraphState(), skips_left=skips_left)

    def test_budget_is_a_declared_block_kind(self) -> None:
        self.assertIn("budget", BLOCK_KINDS)

    def test_an_empty_pool_withdraws_every_backward_edge_and_nothing_else(self) -> None:
        withdrawn = 0
        for stage in STAGES:
            for move in self._moves(stage.slug, 0):
                if move.blocked_kind != "budget":
                    continue
                withdrawn += 1
                self.assertEqual(move.edge.kind, "revisit")
        # The adaptive topology declares backward edges, so an empty pool has to
        # withdraw some; a rule that fired on nothing would pass every other test here.
        self.assertGreater(withdrawn, 0)

    def test_a_pool_above_the_reserve_withdraws_nothing(self) -> None:
        for stage in STAGES:
            for move in self._moves(stage.slug, DELIVERY_RESERVE + 1):
                self.assertNotEqual(move.blocked_kind, "budget")

    def test_a_caller_with_no_budget_to_declare_withdraws_nothing(self) -> None:
        """``None`` is a topology inspected outside a run, or an attended one where
        the pool is not a budget at all."""
        for stage in STAGES:
            for move in self._moves(stage.slug, None):
                self.assertNotEqual(move.blocked_kind, "budget")

    def test_the_admissible_set_only_ever_shrinks(self) -> None:
        """The archive's invariant, applied to this rule: it may never open an edge.

        Every node, every candidate pool size: what is admissible under a budget is a
        subset of what is admissible without one.
        """
        for stage in STAGES:
            unconstrained = {
                move.target for move in self._moves(stage.slug, None) if move.admissible
            }
            for left in range(0, 5):
                constrained = {
                    move.target for move in self._moves(stage.slug, left) if move.admissible
                }
                self.assertLessEqual(constrained, unconstrained, f"{stage.slug} at {left}")

    def test_it_cannot_relabel_an_edge_a_guard_already_shut(self) -> None:
        """Ordering, as a test rather than as a comment on the ``elif``.

        A guard-blocked revisit re-labelled ``budget`` would read as a refusal that
        clears when the pool refills, when in fact the research has to change.
        """
        guarded = 0
        for stage in STAGES:
            without = {move.target: move.blocked_kind for move in self._moves(stage.slug, None)}
            for move in self._moves(stage.slug, 0):
                if without.get(move.target) == "guard":
                    guarded += 1
                    self.assertEqual(move.blocked_kind, "guard", f"{stage.slug}->{move.target}")
        # The fixture workspace is empty, so the content guards are shut; a rule that
        # relabelled nothing because nothing was guarded would pass vacuously.
        self.assertGreater(guarded, 0)

    def test_the_default_move_is_unchanged_by_the_budget(self) -> None:
        """The default is never a backward move, so a rule that only shuts backward
        edges cannot move it. Asserted because ``default_move`` branches on the block
        kinds by name and ``budget`` is deliberately not in that set.

        ``last_resort`` is compared as well as the target. A rule that shut the
        forward edge too would leave the target alone and flip that flag — the
        default falls through to an advance rather than returning None — so a
        comparison of targets alone reports "unchanged" about a run whose every
        forward move is now taken under protest.
        """
        for stage in STAGES:
            without = self.graph.default_move(self.paths, stage.slug, GraphState(), skips_left=None)
            with_none_left = self.graph.default_move(self.paths, stage.slug, GraphState(), skips_left=0)
            self.assertEqual(
                None if without is None else (without.target, without.last_resort),
                None if with_none_left is None else (with_none_left.target, with_none_left.last_resort),
                stage.slug,
            )


class TheRefusalIsRecorded(unittest.TestCase):
    """A refusal nobody can read afterwards is advice, not a gate."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = _run_paths(Path(self._tmp.name))

    def test_the_reason_names_the_pool_and_the_reserve(self) -> None:
        """The agent is shown the blocked edge with this sentence in the move table,
        so it has to say what is short and by how much."""
        blocked = [
            move
            for move in StageGraph.adaptive().moves(
                self.paths, "06_analysis", GraphState(), skips_left=0
            )
            if move.blocked_kind == "budget"
        ]
        self.assertTrue(blocked)
        self.assertIn("auto-skip", blocked[0].blocked_because)
        self.assertIn(str(DELIVERY_RESERVE), blocked[0].blocked_because)

    def test_it_reaches_the_move_table_the_agent_is_shown(self) -> None:
        graph = StageGraph.adaptive()
        moves = graph.moves(self.paths, "06_analysis", GraphState(), skips_left=0)
        table = graph.describe_for_prompt(moves)
        self.assertIn("auto-skip", table)

    def test_it_reaches_the_run_census(self) -> None:
        """``Visit.blocked`` carries the kind, and the census tallies it by name, so
        a reader can count the moves the graph declined to explore."""
        census = block_census(
            [
                Visit(
                    stage="06_analysis",
                    entered_at="t",
                    offered=("07_writing",),
                    blocked={"05_experimentation": "budget"},
                    kind="advance",
                    left_at="t",
                )
            ]
        )
        self.assertEqual(census.blocked["06_analysis->05_experimentation"], {"budget": 1})


class TheManagerDeclaresTheBudgetOnlyWhenItIsOne(unittest.TestCase):
    """Who computes ``skips_left``, and when it is ``None``.

    The pool is the manager's list and the budget test against it is the manager's;
    the graph cannot see either. And an attended run never spends the pool — every
    site that does is behind ``self.unattended`` — so withdrawing a backward edge
    there would protect a reserve nothing was going to draw on.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _declared(self, *, unattended: bool, already_skipped: int) -> int | None:
        paths = _run_paths(self.root / f"{unattended}{already_skipped}")
        manager = ResearchManager(
            project_root=REPO,
            runs_dir=self.root / f"{unattended}{already_skipped}" / "runs",
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY(), interactive=not unattended),
            unattended=unattended,
            max_auto_skips=3,
        )
        manager.auto_skipped_stages = [stage.slug for stage in STAGES[:already_skipped]]
        state = GraphState()
        enter(paths, state, STAGES[0])
        seen: list[int | None] = []

        def capture(**kwargs):
            seen.append(kwargs.get("skips_left"))
            raise _Captured

        with patch.object(StageRouter, "choose", side_effect=capture):
            with self.assertRaises(_Captured):
                manager._advance_from(paths, state, STAGES[0])
        return seen[0]

    def test_an_unattended_run_declares_what_is_left(self) -> None:
        self.assertEqual(self._declared(unattended=True, already_skipped=0), 3)
        self.assertEqual(self._declared(unattended=True, already_skipped=2), 1)

    def test_an_attended_run_declares_nothing(self) -> None:
        self.assertIsNone(self._declared(unattended=False, already_skipped=2))


class _Captured(Exception):
    """Stops ``_advance_from`` at the call this test is about."""


class TheReplayInstrumentReadsARun(unittest.TestCase):
    """The reader behind the table in :data:`~src.stage_graph.DELIVERY_RESERVE`.

    The corpus it was run against is outside the repository, so what is checkable
    here is that a known walk plus a known log come out as the known answer: the
    budget is dated off ``logs.txt``, the choice set off ``Visit.offered``, and a
    withdrawal is only called consequential when a unit was spent after it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.run_dir = Path(self._tmp.name) / "workspace" / ".autor" / "20260101_000000"
        (self.run_dir / "evolution").mkdir(parents=True)

    def _write(self, path: list[dict], log: str, graph: str = "adaptive") -> None:
        (self.run_dir / "evolution" / "stage_graph.json").write_text(
            json.dumps({"path": path}), encoding="utf-8"
        )
        (self.run_dir / "run_config.json").write_text(
            json.dumps({"stage_graph": graph}), encoding="utf-8"
        )
        (self.run_dir / "logs.txt").write_text(log, encoding="utf-8")

    @staticmethod
    def _visit(
        stage: str,
        chose: str,
        kind: str,
        left_at: str,
        offered: list[str],
        entered_at: str | None = None,
    ) -> dict:
        return {
            "stage": stage,
            "entered_at": entered_at or left_at,
            "left_at": left_at,
            "chose": chose,
            "kind": kind,
            "offered": offered,
        }

    def test_the_budget_is_dated_off_the_log_not_modelled(self) -> None:
        self._write(
            [
                self._visit("06_analysis", "07_writing", "advance", "2026-01-01T02:00:00",
                            ["05_experimentation", "07_writing"]),
                self._visit("07_writing", "06_analysis", "revisit", "2026-01-01T04:00:00",
                            ["06_analysis", "finish"]),
            ],
            "=== 2026-01-01T03:00:00 | 05_experimentation unattended_auto_skip ===\n"
            "auto_skip_used: 2/3\n",
        )
        run = REPLAY.read_run(self.run_dir)
        self.assertEqual(run.ceiling, 3)
        # The first decision precedes the skip and the second follows it.
        self.assertEqual([item.skips_used for item in run.decisions], [0, 2])
        self.assertEqual([item.skips_left(run.ceiling) for item in run.decisions], [3, 1])

    def test_a_skip_inside_the_visit_counts_against_the_decision_at_its_end(self) -> None:
        """The decision is dated at ``left_at``, and it has to be.

        This is the shape the corpus's own backward move produced: the run went back
        to Stage 06, that visit exhausted its attempts and spent a unit part-way
        through, and only then did the router choose the move out. Dated at
        ``entered_at`` the decision would be priced against a pool that was still full
        when the visit began — the walk's every visit spans hours, and a unit spent
        inside one is spent before its move is chosen. Found by mutation: every other
        fixture here enters and leaves at the same instant, so swapping the two fields
        changed nothing and survived.
        """
        self._write(
            [
                self._visit(
                    "07_writing", "06_analysis", "revisit", "2026-01-01T06:00:00",
                    ["06_analysis", "finish"], entered_at="2026-01-01T02:00:00",
                ),
            ],
            "=== 2026-01-01T04:00:00 | 06_analysis unattended_auto_skip ===\n"
            "auto_skip_used: 2/3\n",
        )
        run = REPLAY.read_run(self.run_dir)
        self.assertEqual([item.skips_used for item in run.decisions], [2])
        self.assertEqual([item.skips_left(run.ceiling) for item in run.decisions], [1])
        # And the consequence: at the shipped reserve that move comes off the menu.
        self.assertEqual(
            len(REPLAY.replay(run, reserve=DELIVERY_RESERVE)["blocked_taken"]), 1
        )

    def test_the_offered_set_is_counted_not_only_the_move_taken(self) -> None:
        """A reserve's cost is every backward move it takes off the menu, not only
        the ones a run happened to walk."""
        self._write(
            [
                self._visit("06_analysis", "07_writing", "advance", "2026-01-01T02:00:00",
                            ["03_study_design", "05_experimentation", "07_writing"]),
            ],
            "=== 2026-01-01T01:00:00 | 05_experimentation unattended_auto_skip ===\n"
            "auto_skip_used: 3/3\n",
        )
        result = REPLAY.replay(REPLAY.read_run(self.run_dir), reserve=DELIVERY_RESERVE)
        self.assertEqual(result["blocked_taken"], [])
        self.assertEqual(len(result["blocked_offered"]), 2)

    def test_a_reserve_below_what_is_left_withdraws_nothing(self) -> None:
        self._write(
            [
                self._visit("07_writing", "06_analysis", "revisit", "2026-01-01T02:00:00",
                            ["06_analysis", "finish"]),
            ],
            "",
        )
        run = REPLAY.read_run(self.run_dir)
        self.assertEqual(REPLAY.replay(run, reserve=DELIVERY_RESERVE)["blocked_taken"], [])
        self.assertEqual(len(REPLAY.replay(run, reserve=3)["blocked_taken"]), 1)

    def test_a_run_that_was_never_cancelled_is_never_reported_as_still_cancelled(self) -> None:
        self._write(
            [self._visit("07_writing", "finish", "finish", "2026-01-01T02:00:00", ["finish"])],
            "",
        )
        self.assertFalse(REPLAY.replay(REPLAY.read_run(self.run_dir), reserve=3)["still_cancelled"])

    def test_a_linear_run_offers_no_backward_move_to_withdraw(self) -> None:
        """The control arm of the trial. Backward targets are read off the shipped
        topology, so a run that had none contributes nothing to either population."""
        self._write(
            [
                self._visit("06_analysis", "07_writing", "advance", "2026-01-01T02:00:00",
                            ["07_writing"]),
            ],
            "",
            graph="linear",
        )
        self.assertEqual(REPLAY.replay(REPLAY.read_run(self.run_dir), reserve=3)["blocked_offered"], [])


class TheRouterHonoursTheWithdrawal(unittest.TestCase):
    """The seam between the manager's number and the agent's menu.

    Every other test here checks one side: the graph withdraws the edge, the manager
    computes the number. Neither notices if :meth:`~src.router.StageRouter.choose`
    takes the number and forwards it to `default_move` alone — the menu the agent
    picks from would be unfiltered, the agent could name a withdrawn revisit, and the
    router would accept it as live. Found by mutation: dropping `skips_left` from the
    `moves()` call survived the whole suite.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = _run_paths(Path(self._tmp.name))
        # Enough on disk for the backward edges out of 06 to pass their own guards, so
        # what shuts them here is the budget and nothing else.
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"acc": 0.7}))
        write_text(self.paths.experiment_manifest, json.dumps({"result_artifacts": ["metrics.json"]}))
        write_text(self.paths.stage_file(STAGES[5]), "# Stage 06: Analysis\n\nBody.\n")
        self.graph = StageGraph.adaptive()

    def _choose(self, skips_left):
        operator = _FakeRoutingOperator(
            json.dumps(
                {
                    "target": "05_experimentation",
                    "reason": "H1 rests on a single seed and the ablation was never run.",
                }
            )
        )
        return StageRouter(operator, mode="agent").choose(
            paths=self.paths,
            stage=STAGES[5],
            graph=self.graph,
            state=GraphState(),
            skips_left=skips_left,
        )

    def test_a_pool_above_the_reserve_lets_the_agent_go_back(self) -> None:
        """The control. Without it, a router that refused everything would pass below."""
        decision = self._choose(DELIVERY_RESERVE + 1)
        self.assertEqual(decision.target, "05_experimentation")
        self.assertTrue(decision.agent_directed)
        self.assertEqual(decision.refusal, "")

    def test_a_pool_at_the_reserve_refuses_the_same_choice(self) -> None:
        decision = self._choose(DELIVERY_RESERVE)
        self.assertNotEqual(decision.target, "05_experimentation")
        self.assertFalse(decision.agent_directed)
        self.assertIn("auto-skip", decision.refusal)

    def test_the_withdrawn_edge_is_off_the_menu_and_on_the_record(self) -> None:
        """`offered` and `blocked` are what the run's census is built from, so the
        refusal has to leave both sides consistent: not offered, blocked as budget."""
        decision = self._choose(DELIVERY_RESERVE)
        self.assertNotIn("05_experimentation", decision.offered)
        self.assertEqual(decision.blocked.get("05_experimentation"), "budget")

    def test_the_refusal_degrades_forward_rather_than_stalling(self) -> None:
        """The module's standing guarantee: a refused choice becomes the forward edge."""
        self.assertEqual(self._choose(DELIVERY_RESERVE).target, "07_writing")


if __name__ == "__main__":
    unittest.main()
