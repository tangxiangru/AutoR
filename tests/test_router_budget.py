"""What the move costs, against what the run has left.

The routing prompt showed every move, what each one discards, the route so far, the
backward moves already taken, the finished stage's score, archive evidence, the goal and
the stage summary — and no budget of any kind. Then it told the agent not to weigh cost:
"a correct expensive correction beats a wrong cheap one every time, and a run that shops
on price writes up around the flaw it should have gone back for."

That is right in the abstract and it was addressed to an agent that could not see the
balance. Measured on the four runs of the first live paired trial, by reading
`evolution/stage_graph.json` and `logs.txt` under
`/rmeng_data/robtang/rcb-trial-graph/workspaces/*/.autor/*/`: every run was given
twenty steps and the longest walk took nine of them, so the step budget never bound;
the auto-skip allowance was three on all four and two runs spent all three. On the run
that spent them, the next exhaustion landed at Stage 07, which is already the stage
that writes the deliverable, so there was nowhere left to route and the run ended
`cancelled`.

A backward move re-runs stages. A re-run stage can exhaust its attempts like any other,
and an exhausted stage spends a skip. So revisiting and reaching the deliverable draw on
one allowance, and the prompt named neither. These tests hold four things:

* the three pools reach the prompt, with numbers;
* the worst case of each move reaches the prompt, divided by what is left;
* the auto-skip figures come from the counters that *enforce* the budget, not from a
  reconstruction of them — see :class:`TheSkipPoolComesFromTheEnforcerTest`, which pins
  the case a reconstruction gets wrong;
* **none of it refuses anything.** A move whose worst case does not fit is still on the
  menu and is still taken when it is chosen. The refusal is somebody else's item, and a
  display that quietly became a gate would be the more expensive mistake: the run that
  cannot afford to go back is exactly the run that most needs to be able to.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.manager import ResearchManager
from src.router import StageRouter
from src.stage_graph import (
    DEFAULT_MAX_STEPS,
    DEFAULT_MAX_VISITS,
    GraphState,
    StageGraph,
    Visit,
    WalkBudget,
    describe_budget_for_prompt,
    worst_case,
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


STAGE_06 = next(stage for stage in STAGES if stage.number == 6)


def _budget(**overrides: object) -> WalkBudget:
    fields: dict[str, object] = {
        "steps_taken": 9,
        "max_steps": 20,
        "node": "06_analysis",
        "node_visits": 2,
        "max_visits": 3,
        "skips_spent": 1,
        "max_skips": 3,
    }
    fields.update(overrides)
    return WalkBudget(**fields)  # type: ignore[arg-type]


class WalkBudgetArithmeticTest(unittest.TestCase):
    def test_what_is_left_is_what_was_given_minus_what_was_spent(self) -> None:
        budget = _budget()
        self.assertEqual(budget.steps_left, 11)
        self.assertEqual(budget.skips_left, 2)

    def test_an_overspent_pool_reads_as_empty_rather_than_negative(self) -> None:
        """A run resumed with a smaller cap than it has already spent is a real state.

        `--graph-max-steps` is re-read on resume and `load_graph_state` overwrites the
        stored cap with it, so a walk of nine steps resumed at `--graph-max-steps 4` is
        reachable from the CLI. "-5 left" is not a quantity a reader can act on.
        """
        self.assertEqual(_budget(max_steps=4).steps_left, 0)
        self.assertEqual(_budget(skips_spent=5).skips_left, 0)

    def test_an_unrecorded_allowance_is_none_rather_than_a_guess(self) -> None:
        self.assertIsNone(_budget(max_skips=None).skips_left)

    def test_it_reads_the_graphs_two_pools_off_the_state(self) -> None:
        state = GraphState(
            path=[
                Visit(stage="05_experimentation", entered_at="t"),
                Visit(stage="06_analysis", entered_at="t"),
                Visit(stage="05_experimentation", entered_at="t"),
            ]
        )
        budget = WalkBudget.of(state, "05_experimentation")
        self.assertEqual(budget.steps_taken, 3)
        self.assertEqual(budget.max_steps, DEFAULT_MAX_STEPS)
        self.assertEqual(budget.node_visits, 2)
        self.assertEqual(budget.max_visits, DEFAULT_MAX_VISITS)
        # Not the graph's to know, and not invented.
        self.assertEqual(budget.skips_spent, 0)
        self.assertIsNone(budget.max_skips)


class StageRunsTest(unittest.TestCase):
    """`Discards` is zero for three different situations and they cost differently."""

    def setUp(self) -> None:
        self.graph = StageGraph.adaptive()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)

    def _move(self, source: str, target: str):
        moves = self.graph.moves(self.paths, source, GraphState())
        return next(move for move in moves if move.target == target)

    def test_an_advance_discards_nothing_and_still_runs_a_stage(self) -> None:
        move = self._move("06_analysis", "07_writing")
        self.assertEqual(move.replay_cost, 0)
        self.assertEqual(move.stage_runs, 1)

    def test_a_finish_runs_nothing(self) -> None:
        move = self._move("06_analysis", "finish")
        self.assertEqual(move.stage_runs, 0)

    def test_a_revisit_re_runs_everything_it_threw_away(self) -> None:
        move = self._move("06_analysis", "03_study_design")
        self.assertEqual(move.replay_cost, 4)
        self.assertEqual(move.stage_runs, 4)


class WorstCaseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = StageGraph.adaptive()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)

    def _move(self, source: str, target: str):
        moves = self.graph.moves(self.paths, source, GraphState())
        return next(move for move in moves if move.target == target)

    def test_it_divides_the_cost_by_what_is_left(self) -> None:
        cell = worst_case(self._move("06_analysis", "03_study_design"), _budget())
        self.assertIn("4 steps of 11 left", cell)
        self.assertIn("up to 2 of the 2 auto-skips left", cell)

    def test_the_skips_at_risk_are_capped_by_the_skips_that_remain(self) -> None:
        """Four re-runs cannot spend five skips out of an allowance of two."""
        cell = worst_case(self._move("06_analysis", "03_study_design"), _budget(skips_spent=2))
        self.assertIn("up to 1 of the 1 auto-skip left", cell)

    def test_a_move_the_walk_cannot_finish_says_so(self) -> None:
        cell = worst_case(self._move("06_analysis", "02_hypothesis_generation"), _budget(steps_taken=18))
        self.assertIn("5 steps of 2 left", cell)
        self.assertIn("does not fit", cell)

    def test_a_move_that_fits_does_not_say_it_does_not(self) -> None:
        self.assertNotIn("does not fit", worst_case(self._move("06_analysis", "05_experimentation"), _budget()))

    def test_an_unrecorded_allowance_gives_a_ceiling_without_a_denominator(self) -> None:
        cell = worst_case(self._move("06_analysis", "03_study_design"), _budget(max_skips=None))
        self.assertEqual(cell, "4 steps of 11 left; up to 4 auto-skips")

    def test_finishing_costs_nothing_and_is_shown_as_nothing(self) -> None:
        self.assertEqual(worst_case(self._move("06_analysis", "finish"), _budget()), "—")


class BudgetBlockTest(unittest.TestCase):
    def test_all_three_pools_are_named_with_what_is_left(self) -> None:
        block = describe_budget_for_prompt(_budget())
        self.assertIn("9 of 20 spent, 11 left", block)
        self.assertIn("Visits to `06_analysis`**: 2 of 3", block)
        self.assertIn("1 of 3 spent, 2 left", block)

    def test_an_unrecorded_allowance_is_declared_missing_rather_than_filled_in(self) -> None:
        block = describe_budget_for_prompt(_budget(skips_spent=0, max_skips=None))
        skip_line = next(line for line in block.splitlines() if "Auto-skips" in line)
        self.assertIn("0 spent so far", skip_line)
        self.assertIn("against no declared allowance", skip_line)
        # The two shapes a fabricated denominator would take.
        self.assertNotIn(" left", skip_line)
        self.assertNotIn(" of ", skip_line.split(".")[0])


class TheSkipPoolComesFromTheEnforcerTest(unittest.TestCase):
    """Where the auto-skip figures come from, and the case that decided it.

    The obvious source is `logs.txt`: the manager writes `auto_skip_used: N/M` beside
    every stage it auto-skips, both halves on one line, and a regex over the run's own
    record needs no new parameter anywhere. It is also wrong twice, and this class pins
    the more serious half.

    `_route_to_deliverable` extends `auto_skipped_stages` — the list the budget test
    `len(self.auto_skipped_stages) >= self.max_auto_skips` reads — with every stage it
    bypasses, and writes a `routed_to_deliverable` entry that carries no
    `auto_skip_used:` line. It is reachable with the pool untouched: the approval-gate
    abort branch calls it in unattended mode without consulting the budget at all. So a
    log reader can report an untouched pool to the very next routing decision after the
    pool has been emptied and overdrawn.

    Measured on the trial, not just constructed here: on
    `workspaces/Astronomy_000_20260814_175426/.autor/20260814_175429/logs.txt` the last
    `auto_skip_used:` line reads `3/3` while the `already_skipped:` list in the same
    file's `routed_to_deliverable` entry names five stages.

    Asking the enforcer cannot disagree with the enforcer. The second half — `logs.txt`
    is at the run root, where the operator runs `bypassPermissions` — is why it would
    have been the wrong source even if it were complete.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = build_run_paths(self.root / "runs" / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")

    def _manager(self, *, max_auto_skips: int = 3, unattended: bool = True) -> ResearchManager:
        class StubOperator:
            model = "stub-model"
            backend_name = "claude"

        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.root / "runs",
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), input_stream=io.StringIO(), interactive=False),
            unattended=unattended,
            max_auto_skips=max_auto_skips,
        )

    def test_an_untouched_pool_reads_as_spent_nothing_of_the_allowance(self) -> None:
        self.assertEqual(self._manager()._auto_skip_budget(), (0, 3))

    def test_a_spent_skip_moves_it(self) -> None:
        manager = self._manager()
        self.assertTrue(
            manager._handle_stage_exhaustion(
                paths=self.paths,
                stage=STAGES[1],
                attempt_no=8,
                last_validation_errors=["Missing 'Key Results' section"],
            )
        )
        self.assertEqual(manager._auto_skip_budget(), (1, 3))
        self.assertEqual(len(manager.auto_skipped_stages), 1)

    def test_it_tracks_the_spend_across_several_skips(self) -> None:
        manager = self._manager()
        for stage in STAGES[:2]:
            manager._handle_stage_exhaustion(
                paths=self.paths, stage=stage, attempt_no=8, last_validation_errors=[]
            )
        self.assertEqual(manager._auto_skip_budget(), (2, 3))

    def test_a_non_default_allowance_is_reported_rather_than_assumed(self) -> None:
        """The one thing a constant kept in `src/router.py` could not have got right."""
        self.assertEqual(self._manager(max_auto_skips=7)._auto_skip_budget(), (0, 7))

    def test_a_human_skip_does_not_draw_on_the_unattended_pool(self) -> None:
        """`/skip` costs the run a stage and costs the unattended allowance nothing."""
        manager = self._manager()
        manager._skip_stage(
            paths=self.paths,
            stage=STAGES[0],
            attempt_no=1,
            reason="Human operator skipped this stage via /skip.",
            kind="human",
        )
        self.assertIn("skipped", read_text(self.paths.logs))
        self.assertEqual(manager._auto_skip_budget(), (0, 3))

    def test_an_attended_run_reports_no_allowance_because_none_is_in_play(self) -> None:
        self.assertEqual(self._manager(unattended=False)._auto_skip_budget(), (0, None))

    def test_a_route_to_the_deliverable_spends_the_pool_and_writes_no_tally(self) -> None:
        """The case a `logs.txt` reader gets wrong, both halves in one test.

        Reachable with the budget untouched: `_route_to_deliverable` is called from the
        approval-gate abort branch without a budget check. Four stages land in the
        tally, and the words `auto_skip_used` never reach the log — so a reader of the
        record would tell the next routing decision that nothing had been spent.
        """
        manager = self._manager()
        self.assertTrue(
            manager._route_to_deliverable(
                paths=self.paths,
                stage=STAGES[2],
                attempt_no=1,
                because="the approval gate aborted with no human to ask",
                errors_note="- (the stage was aborted rather than failing validation)",
            )
        )
        self.assertEqual(manager._auto_skip_budget(), (4, 3))
        self.assertNotIn("auto_skip_used", read_text(self.paths.logs))

    def test_the_manager_hands_the_router_that_very_method(self) -> None:
        """Wiring, not shape. A provider nothing passes shows the same "not declared"
        line as no provider at all, and the whole block would go quietly blank."""
        manager = self._manager()
        self.assertEqual(manager.router.skip_budget, manager._auto_skip_budget)

    def test_a_router_with_no_provider_declares_no_allowance_rather_than_guessing(self) -> None:
        self.assertIsNone(StageRouter(None, mode="agent").skip_budget)


class RoutingPromptTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.stage_file(STAGE_06), "# Stage 06: Analysis\n\nBody.\n")
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"acc": 0.7}))
        write_text(self.paths.experiment_manifest, json.dumps({"result_artifacts": ["metrics.json"]}))
        self.graph = StageGraph.adaptive()

    def _state(self, steps: int = 6) -> GraphState:
        return GraphState(
            path=[Visit(stage=stage.slug, entered_at="t") for stage in STAGES[:steps]]
        )

    def _prompt(
        self,
        state: GraphState | None = None,
        skip_budget: object | None = None,
    ) -> str:
        state = state or self._state()
        moves = self.graph.moves(self.paths, STAGE_06.slug, state)
        return StageRouter(None, mode="agent", skip_budget=skip_budget).build_prompt(  # type: ignore[arg-type]
            paths=self.paths, stage=STAGE_06, moves=moves, state=state, score=None
        )

    def test_the_prompt_carries_the_three_pools(self) -> None:
        prompt = self._prompt(skip_budget=lambda: (1, 3))
        self.assertIn("## What this run has left", prompt)
        self.assertIn("6 of 20 spent, 14 left", prompt)
        self.assertIn("Visits to `06_analysis`**: 1 of 3", prompt)
        self.assertIn("1 of 3 spent, 2 left", prompt)

    def test_the_menu_carries_a_worst_case_per_move(self) -> None:
        prompt = self._prompt(skip_budget=lambda: (1, 3))
        self.assertIn("| Worst case |", prompt)
        # `06 -> 03` discards four stages; four of the fourteen steps left, and it can
        # spend both of the two skips left.
        self.assertIn("4 steps of 14 left; up to 2 of the 2 auto-skips left", prompt)

    def test_the_prompt_says_what_a_re_run_stage_can_cost(self) -> None:
        """The sentence that connects a backward edge to the allowance it competes with."""
        prompt = self._prompt()
        self.assertIn("a re-run stage can exhaust its attempts", prompt)
        self.assertIn("up to one auto-skip each", prompt)

    def test_cost_is_still_not_the_criterion(self) -> None:
        prompt = self._prompt()
        self.assertIn("Cost is not the criterion", prompt)
        self.assertIn("A correct expensive correction beats a wrong cheap one", prompt)

    def test_and_an_unaffordable_correction_is_no_longer_recommended(self) -> None:
        prompt = self._prompt()
        self.assertIn("cannot afford to finish is not a correction", prompt)

    def test_it_does_not_invent_an_allowance_it_was_never_told(self) -> None:
        prompt = self._prompt()
        self.assertIn("against no declared allowance", prompt)
        self.assertNotIn("auto-skips left", prompt)

    def test_a_run_out_of_steps_is_told_the_move_does_not_fit(self) -> None:
        state = self._state()
        state.max_steps = 8
        prompt = self._prompt(state)
        self.assertIn("6 of 8 spent, 2 left", prompt)
        # `06 -> 03` re-runs four stages and the walk has two left.
        self.assertIn("4 steps of 2 left — does not fit", prompt)
        # `06 -> 05` re-runs two and still fits.
        self.assertIn("| 2 steps of 2 left; up to 2 auto-skips |", prompt)


class TheBudgetIsShownAndNotEnforcedTest(unittest.TestCase):
    """The line this item is not allowed to cross.

    A refusal on cost grounds belongs to the budget-separation work and to the
    supervisor above it. What is added here is a number on a page. These tests fail if
    it ever becomes a gate — which is the accident this shape invites, because the
    arithmetic for the display and the arithmetic for a refusal are the same arithmetic.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.stage_file(STAGE_06), "# Stage 06: Analysis\n\nBody.\n")
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"acc": 0.7}))
        write_text(self.paths.experiment_manifest, json.dumps({"result_artifacts": ["metrics.json"]}))
        self.graph = StageGraph.adaptive()

    def _choose(self, response: str, state: GraphState, skip_budget: object | None = None):
        class FakeOperator:
            fake_mode = False

            def __init__(self) -> None:
                self.prompts: list[str] = []

            def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
                self.prompts.append(read_text(prompt_path))
                return (["fake-backend"], paths.run_root, None)

            def _run_streaming_command(self, **kwargs):
                return (0, response, "", None, {})

        operator = FakeOperator()
        decision = StageRouter(operator, mode="agent", skip_budget=skip_budget).choose(  # type: ignore[arg-type]
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=state
        )
        return decision, operator

    def test_the_dearest_move_is_taken_with_the_allowance_spent(self) -> None:
        state = GraphState(path=[Visit(stage=stage.slug, entered_at="t") for stage in STAGES[:6]])
        decision, operator = self._choose(
            json.dumps(
                {
                    "target": "02_hypothesis_generation",
                    "reason": "The evidence refutes H1 and points at a different mechanism.",
                }
            ),
            state,
            skip_budget=lambda: (3, 3),
        )
        self.assertIn("3 of 3 spent, 0 left", operator.prompts[0])
        self.assertEqual(decision.target, "02_hypothesis_generation")
        self.assertTrue(decision.agent_directed)
        self.assertEqual(decision.refusal, "")

    def test_a_move_that_does_not_fit_the_step_budget_is_still_on_the_menu(self) -> None:
        state = GraphState(
            path=[Visit(stage=stage.slug, entered_at="t") for stage in STAGES[:6]], max_steps=7
        )
        decision, operator = self._choose(
            json.dumps(
                {
                    "target": "02_hypothesis_generation",
                    "reason": "The evidence refutes H1 and points at a different mechanism.",
                }
            ),
            state,
        )
        self.assertIn("does not fit", operator.prompts[0])
        self.assertEqual(decision.target, "02_hypothesis_generation")
        self.assertEqual(decision.refusal, "")

    def test_the_router_source_records_no_refusal_on_a_budget_it_only_displays(self) -> None:
        """A grep, deliberately. The reader after the supervisor lands will be looking
        for whether this module ever learned to say no, and the answer has to be no."""
        text = (Path(__file__).resolve().parent.parent / "src" / "router.py").read_text(encoding="utf-8")
        body = text.split("def choose(", 1)[1].split("def _refuse(", 1)[0]
        for symbol in ("skips_left", "steps_left", "skip_budget", "WalkBudget"):
            self.assertNotIn(symbol, body, f"`choose` reads {symbol}; a display became a gate")


class WritingStageHasNowhereToRouteTest(unittest.TestCase):
    """Why the auto-skip pool is the one worth showing.

    The chain the trial walked: a stage burns its attempts, an auto-skip fires, repeat
    until the allowance is spent, and then the next exhaustion happens at the stage that
    writes the deliverable — where `_route_to_deliverable` has nowhere to send it. This
    pins the last link, which is the one that turns a spent allowance into a cancelled
    run rather than into a shorter one.
    """

    def test_an_exhaustion_at_the_writing_stage_with_no_allowance_left_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = build_run_paths(root / "runs" / "run_0001")
            ensure_run_layout(paths)
            write_text(paths.user_input, "goal")
            write_text(paths.memory, "# Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")

            class StubOperator:
                model = "stub-model"
                backend_name = "claude"

            manager = ResearchManager(
                project_root=Path(__file__).resolve().parent.parent,
                runs_dir=root / "runs",
                operator=StubOperator(),
                ui=TerminalUI(output_stream=io.StringIO(), input_stream=io.StringIO(), interactive=False),
                unattended=True,
                max_auto_skips=0,
            )
            self.assertFalse(
                manager._handle_stage_exhaustion(
                    paths=paths, stage=WRITING_STAGE, attempt_no=8, last_validation_errors=[]
                )
            )
            self.assertIn("unattended_abort", read_text(paths.logs))


if __name__ == "__main__":
    unittest.main()
