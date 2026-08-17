"""The backward edge is the contribution, and nothing gates the machinery's joint effect.

The graph is what this project has that a plain agent loop does not: a run navigating its
own topology, with a backward move first-class. Every mechanism built around it pushes the
same way -- stop spending, move on, go forward. ``STOP_SPENDING`` cuts a visit short,
``REALLOCATE`` moves budget between stages, ``REDIRECT`` returns a routing decision before
the agent is asked, ``DELIVERY_RESERVE`` withdraws backward moves outright. Each is
separately measured, separately argued and separately gated. Their *sum* was gated by
nobody, and the near miss is on the record: :mod:`src.supervisor`'s attempt pool was once
re-pooled from per visit to per stage across visits, so a stage that exhausted its first
visit was handed ``remaining = 0`` on its second and every backward edge became a
zero-attempt death. Nothing in the suite went red. A reviewer found it by driving the real
manager loop by hand.

Three gates, and why each is the shape it is
--------------------------------------------
:class:`TheOfferedSetIsTheGraphMinusDeclaredBlocksTests` -- **the offered set is a
function of the graph and the declared block kinds, and nothing else.** Under the full
stack, the backward moves a node offers must be the bare graph's set minus only moves
carrying one of :data:`~src.stage_graph.BLOCK_KINDS`. A mechanism that narrows the menu
without recording a kind is an undeclared narrowing, which is the shape of the defect that
nearly shipped.

:class:`TheFullStackFundsEveryVisitTests` -- **an offered backward move is a funded one.**
``EveryVisitIsFundedTests`` in ``tests/test_run_supervisor.py`` covers the supervisor
alone; this is the same claim with everything on at once: supervisor, delivery reserve,
effort tiers, a skip budget one unit above :data:`~src.stage_graph.DELIVERY_RESERVE`, and
a stage that has already exhausted a previous visit.

:class:`ThePreEmptedDecisionIsCountedTests` -- **the pre-emption is a field, not a
feature.** ``REDIRECT`` may be right and it must be countable, so
:func:`~src.router.routing_summary` publishes ``preempted`` beside ``agent_directed`` and
a future loosening of :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT` shows up
as a number moving rather than as a capability draining away.

Behavioural, not syntactic
--------------------------
``tests/test_cost_is_recorded_and_unread.py`` learned the general lesson in the same week
and says so in its own docstring: a scan over names was defeated by laundering the value
through one extra call, and eighty syntax tests stayed green. What closed it was replaying
the component against two inputs that differ only in the thing it must not see. So the two
set-shaped gates here drive the real :class:`~src.stage_graph.StageGraph` and the real
:class:`~src.router.StageRouter`, and the funding gate drives
``ResearchManager._run_stage`` twice into one stage. A router that dropped a backward
target out of ``live`` between the menu and the record would pass any grep and fails
:meth:`TheOfferedSetIsTheGraphMinusDeclaredBlocksTests.test_every_backward_move_the_stack_withdraws_carries_a_declared_kind`.

The instrument and the sweep
----------------------------
``tools/backward_edge_census.py`` is the before/after table as something that can be run
rather than quoted, and :class:`TheCensusInstrumentIsTheGateTests` pins it to calling the
shipped code rather than a model of it. :data:`STACK_MUTATIONS` is the gate as an
instrument; its first three entries re-pool the attempt budget from per visit to per stage
across visits at the three layers where that is expressible::

    git worktree add --detach /tmp/sweep HEAD
    cd /tmp/sweep && python3 -m tests.test_the_backward_edge_survives_the_stack --mutations
"""

from __future__ import annotations

import importlib.util
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.approval_agent import ReviewDecision
from src.archive import Archive, RunRecord
from src.effort import Concentration, EffortPlan
from src.manager import ResearchManager
from src.manifest import load_run_manifest
from src.rubric import RUBRIC_VERSION
from src.router import (
    PREEMPTIONS,
    SUPERVISOR_PREEMPTION,
    RoutingDecision,
    StageRouter,
    routing_summary,
)
from src.stage_cost import (
    OUTCOME_AUTO_SKIPPED,
    OUTCOME_BYPASSED,
    StageCostMeter,
    append_stage_cost_row,
    read_stage_cost_ledger,
)
from src.stage_graph import (
    BLOCK_KINDS,
    DELIVERY_RESERVE,
    REVISIT_EDGES,
    GraphState,
    StageGraph,
    Visit,
    enter,
    leave,
)
from src.supervisor import (
    CONTINUE,
    ESCALATE,
    REALLOCATE,
    REDIRECT,
    STOP_SPENDING,
    UNSETTLED_VISITS_BEFORE_A_REDIRECT,
    AllowanceError,
    RunSupervisor,
)
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    WRITING_STAGE,
    build_run_paths,
    ensure_run_layout,
    write_text,
)
from tests.test_stage_cost_ledger import ManagerLoopFixture, _StubReviewer

REPO = Path(__file__).resolve().parent.parent

#: The nodes a backward edge leaves from, and the ones it lands on. Derived from the
#: shipped topology rather than listed, so an edge added to
#: :data:`~src.stage_graph.REVISIT_EDGES` joins every gate here without touching this file.
BACKWARD_SOURCES = tuple(sorted({edge.source for edge in REVISIT_EDGES}))
BACKWARD_TARGETS = tuple(sorted({edge.target for edge in REVISIT_EDGES}))


def _load_census():
    """Load ``tools/backward_edge_census.py`` by path.

    ``tools/`` is not a package, and this is how ``tests/test_revisit_budget_reserve.py``
    reaches its own instrument: a namespace import would work from the repository root and
    fail anywhere else, which is the shape that lets an instrument's test stop running
    without anybody noticing.
    """
    path = REPO / "tools" / "backward_edge_census.py"
    spec = importlib.util.spec_from_file_location("backward_edge_census_tool", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CENSUS = _load_census()


def furnished_run(root: Path):
    """A run root whose workspace satisfies every content guard on a backward edge.

    Deliberately furnished. A guard that is shut because the workspace is empty is the
    *graph* declining a move, and it is present in the bare column too, so it cannot tell
    a reader anything about what the machinery costs. What is wanted here is a state in
    which every backward edge is open on the bare graph, so that any narrowing under the
    stack is the stack's.
    """
    paths = build_run_paths(root / "runs" / "run_0001")
    ensure_run_layout(paths)
    write_text(paths.user_input, "Does the machinery leave the graph standing?")
    CENSUS.furnish(paths)
    return paths


# ---------------------------------------------------------------------------
# 1. The offered set is the graph, minus declared blocks, and nothing else
# ---------------------------------------------------------------------------


class TheOfferedSetIsTheGraphMinusDeclaredBlocksTests(unittest.TestCase):
    """What a node offers backward is the topology's answer, not the machinery's.

    The stack column is driven through the real :meth:`~src.router.StageRouter.choose`
    rather than over :meth:`~src.stage_graph.StageGraph.moves` alone, because the router
    is where the laundering path is. ``choose`` computes ``live`` from ``moves`` and then
    records ``offered`` off it; three lines between those two points could drop a backward
    target from the menu, the agent would never see it, and every assertion about
    ``moves`` would still pass. That is the escape
    ``tests/test_cost_is_recorded_and_unread.py`` had built against itself and could not
    close syntactically.

    The bare column is read off the *graph*, and that asymmetry is load-bearing rather
    than tidy. A comparison whose two sides go through the same function cannot see a
    defect in that function: the narrowing would land in both columns, cancel out of the
    difference, and the gate would report "no change" about a capability that had just
    been removed. Measured on this tree: with both columns routed, the sweep's "the router
    narrows the menu with nothing recorded" mutation was killed by the tests that count
    how many edges are open and *not* by
    :meth:`test_every_backward_move_the_stack_withdraws_carries_a_declared_kind`, which is
    the gate that exists for it. With the bare column read off the graph it is.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = furnished_run(Path(self._tmp.name))
        self.graph = StageGraph.adaptive()

    def _bare(self, slug: str) -> tuple[set[str], dict[str, str]]:
        return CENSUS.offered_backward(self.paths, slug, CENSUS.BARE)

    def _stack(self, slug: str, **overrides) -> tuple[set[str], dict[str, str]]:
        return CENSUS.offered_backward(self.paths, slug, CENSUS.full_stack(**overrides))

    def test_the_bare_graph_has_backward_moves_to_lose(self) -> None:
        """The control. A gate over an empty set passes for the wrong reason."""
        offered = {target for slug in BACKWARD_SOURCES for target in self._bare(slug)[0]}
        self.assertEqual(
            sum(len(self._bare(slug)[0]) for slug in BACKWARD_SOURCES),
            len(REVISIT_EDGES),
            f"the furnished fixture does not open all {len(REVISIT_EDGES)} backward edges",
        )
        self.assertTrue(offered)

    def test_the_stack_never_opens_a_backward_move_the_graph_did_not(self) -> None:
        """The one-way constraint, in the direction nobody worries about.

        The archive may reorder which move is preferred and may never open a guarded edge;
        the cross-model reviewer is a veto and never an override. Same rule here: with
        every mechanism on, the offered set is a subset of the bare one at every node and
        every pool size, so no combination of them can add an edge back.
        """
        for slug in BACKWARD_SOURCES:
            bare, _ = self._bare(slug)
            for left in range(0, 5):
                with self.subTest(stage=slug, skips_left=left):
                    stack, _ = self._stack(slug, skips_left=left)
                    self.assertLessEqual(stack, bare)

    def test_every_backward_move_the_stack_withdraws_carries_a_declared_kind(self) -> None:
        """The gate itself, over every node and every pool size the flag allows.

        A move that is on the bare menu and off the stack's must appear in the same
        decision's ``blocked`` map under one of :data:`~src.stage_graph.BLOCK_KINDS`. An
        undeclared narrowing is a capability removed with no record that it was, which is
        precisely what "the mechanisms together" can do that none of them does alone.
        """
        for slug in BACKWARD_SOURCES:
            bare, _ = self._bare(slug)
            for left in range(0, 5):
                stack, blocked = self._stack(slug, skips_left=left)
                with self.subTest(stage=slug, skips_left=left):
                    self.assertEqual(
                        CENSUS.undeclared_narrowings(bare, stack, blocked),
                        [],
                        f"{slug} lost a backward move with nothing recorded",
                    )

    def test_the_gate_notices_a_narrowing_that_records_nothing(self) -> None:
        """The control for the gate itself: a scan that finds nothing and a scan that
        looks for nothing are the same green.

        The comparison above is one function, so the control can hand it the pair a
        laundering would produce -- one backward target gone from the offered set, nothing
        added to ``blocked`` -- and require it to fire. The third case is the subtler one:
        a kind outside :data:`~src.stage_graph.BLOCK_KINDS` is a heading no reader can
        interpret, and counting it as a declaration would let a mechanism declare itself.
        """
        bare = {"05_experimentation", "03_study_design"}
        self.assertEqual(
            CENSUS.undeclared_narrowings(bare, {"03_study_design"}, {}),
            ["05_experimentation"],
        )
        self.assertEqual(
            CENSUS.undeclared_narrowings(
                bare, {"03_study_design"}, {"05_experimentation": "budget"}
            ),
            [],
        )
        self.assertEqual(
            CENSUS.undeclared_narrowings(
                bare, {"03_study_design"}, {"05_experimentation": "too_expensive"}
            ),
            ["05_experimentation"],
        )

    def _rule_every_intervention(self) -> set[str]:
        """Drive one real supervisor to each of its five rulings on this run root.

        "With the supervisor active and ruling every intervention it has" is the
        condition item 1 is stated under, and a test that only reached ``continue`` would
        be asserting it about a supervisor that had done nothing. Each rule is driven at a
        different stage so one ruling's effect is not another's precondition, and the
        kinds actually reached are returned so the caller can refuse a vacuous fixture.
        """
        supervisor = RunSupervisor(
            stage_slugs=[stage.slug for stage in STAGES], max_auto_skips=3
        )
        # Three cheap closed stages, so there is a distribution to be disproportionate
        # against, plus two unsettled visits to `04_implementation` so the redirect
        # threshold is reached.
        for slug in ("01_literature_survey", "02_hypothesis_generation", "03_study_design"):
            self._close(slug, charged=1, outcome="approved")
        for _ in range(UNSETTLED_VISITS_BEFORE_A_REDIRECT):
            self._close("04_implementation", charged=1, outcome=OUTCOME_AUTO_SKIPPED)

        seen = set()
        seen.add(self._rule(supervisor, "05_experimentation", meter=None).kind)
        seen.add(
            self._rule(
                supervisor,
                "05_experimentation",
                meter=self._meter("05_experimentation", ["the same objection"] * 3),
            ).kind
        )
        seen.add(
            self._rule(
                supervisor,
                "06_analysis",
                meter=self._meter("06_analysis", ["one", "two", "three"]),
            ).kind
        )
        seen.add(
            self._rule(
                supervisor,
                "07_writing",
                meter=self._meter("07_writing", [f"objection {n}" for n in range(8)]),
                skips_spent=3,
            ).kind
        )
        seen.add(
            supervisor.review_stage_exit(
                paths=self.paths,
                stage_slug="04_implementation",
                admissible_forward=["05_experimentation"],
            ).kind
        )
        return seen

    def _close(self, slug: str, *, charged: int, outcome: str) -> None:
        meter = StageCostMeter(next(item for item in STAGES if item.slug == slug))
        for _ in range(charged):
            meter.note_attempt()
        meter.note_outcome(outcome)
        append_stage_cost_row(self.paths, meter.close())

    def _meter(self, slug: str, failures: list[str]) -> StageCostMeter:
        meter = StageCostMeter(next(item for item in STAGES if item.slug == slug))
        for number, reason in enumerate(failures, start=1):
            meter.note_attempt()
            meter.note_failure(number, "validators_refused", reason)
        return meter

    def _rule(self, supervisor, slug: str, *, meter, skips_spent: int = 0):
        stage = next(item for item in STAGES if item.slug == slug)
        return supervisor.review_attempt(
            paths=self.paths,
            stage_slug=slug,
            stage_number=stage.number,
            meter=meter,
            attempt_no=1,
            auto_skips_spent=skips_spent,
            deliverable_number=WRITING_STAGE.number,
            per_stage_ceiling=8,
        )

    def test_a_supervisor_that_has_ruled_everything_narrows_no_menu(self) -> None:
        """Item 1 as stated: every intervention exercised, and the menu unchanged.

        The four acting rulings are about *spend*, not about topology --
        ``STOP_SPENDING`` and ``ESCALATE`` end a visit, ``REALLOCATE`` moves an attempt
        allowance, ``REDIRECT`` names one of the moves the guards already left open. None
        of them may reach the offered set, and this is that claim driven rather than read
        off the call graph: a later commit that handed the allowance ledger to
        ``StageGraph.moves`` would fail here and pass every syntax check in the tree.
        """
        before = {slug: self._bare(slug)[0] for slug in BACKWARD_SOURCES}
        reached = self._rule_every_intervention()
        self.assertEqual(
            reached,
            {CONTINUE, STOP_SPENDING, REALLOCATE, ESCALATE, REDIRECT},
            "the fixture did not reach every intervention",
        )
        for slug in BACKWARD_SOURCES:
            with self.subTest(stage=slug):
                self.assertEqual(self._bare(slug)[0], before[slug])
                stack, blocked = self._stack(
                    slug,
                    skips_left=DELIVERY_RESERVE + 1,
                    unsettled=UNSETTLED_VISITS_BEFORE_A_REDIRECT,
                )
                self.assertEqual(
                    stack,
                    before[slug],
                    "a supervisor ruling narrowed the backward menu",
                )
                self.assertEqual(
                    {target: kind for target, kind in blocked.items() if target in stack},
                    {},
                )

    def test_the_reserve_is_the_only_mechanism_that_narrows_a_furnished_graph(self) -> None:
        """Measured rather than assumed, and the number is the table in the PR body.

        With the workspace furnished, every backward edge is open bare. With the pool one
        unit above :data:`~src.stage_graph.DELIVERY_RESERVE` the stack takes none of them;
        at the reserve it takes every one, each declared ``budget``.
        """
        above = {
            slug: self._stack(slug, skips_left=DELIVERY_RESERVE + 1) for slug in BACKWARD_SOURCES
        }
        self.assertEqual(
            sum(len(offered) for offered, _ in above.values()),
            len(REVISIT_EDGES),
            "a mechanism other than the reserve narrowed a furnished graph",
        )
        at = {slug: self._stack(slug, skips_left=DELIVERY_RESERVE) for slug in BACKWARD_SOURCES}
        self.assertEqual(sum(len(offered) for offered, _ in at.values()), 0)
        kinds = {
            kind
            for _offered, blocked in at.values()
            for target, kind in blocked.items()
            if target in BACKWARD_TARGETS
        }
        self.assertEqual(kinds, {"budget"})


# ---------------------------------------------------------------------------
# 2. An offered backward move is a funded one
# ---------------------------------------------------------------------------


class FullStackFixture(ManagerLoopFixture):
    """A real manager with every mechanism that can narrow a run switched on at once.

    ``EveryVisitIsFundedTests`` drives the same loop with the supervisor alone. What this
    adds is the rest of the stack, because the failure being gated is a *joint* one: each
    mechanism is bounded on its own terms and the thing they can destroy together is the
    backward edge.

    ``ALREADY_SKIPPED`` leaves the pool at ``DELIVERY_RESERVE + 1``: the smallest value at
    which a backward move is still on any menu at all. One unit lower and the reserve has
    already withdrawn all thirteen — which
    ``TheReserveClosesTheGraphAtTheBottomOfTheFlag`` pins in
    ``tests/test_revisit_budget_reserve.py`` — and this class would pass by never reaching
    the question it exists to ask.
    """

    #: Not the stage under test: the list is the run's record of gates it gave up on, and
    #: putting the stage being driven into it would change what ``_route_to_deliverable``
    #: does rather than what the budget is.
    ALREADY_SKIPPED = ("02_hypothesis_generation",)
    STAGE = STAGES[0]

    def setUp(self) -> None:
        super().setUp()
        self.manager.unattended = True
        self.manager.auto_skipped_stages = list(self.ALREADY_SKIPPED)
        self.manager.effort_plan = EffortPlan(enabled=True)
        self.manager.concentration = Concentration(polish_routine=True)
        self.manager.stage_graph = StageGraph.adaptive()

    def _skips_left(self) -> int:
        return self.manager.max_auto_skips - len(self.manager.auto_skipped_stages)

    def _visit(self, decision: ReviewDecision) -> bool:
        self._stub_operator(self._valid_draft(self.STAGE))
        self.manager.reviewer = _StubReviewer([decision])
        return self.manager._run_stage(self.paths, self.STAGE)

    def _exhausting_visit(self) -> bool:
        """One visit that spends the whole ceiling on validation failures.

        The same fixture ``EveryVisitIsFundedTests`` uses, and for the reason recorded
        there: a reviewer refusal cannot be repeated across visits because
        ``MAX_AUTOMATED_SENDBACKS`` is counted per stage and read from disk, so the second
        visit's first refusal would be converted into an approval and the visit would end
        after one attempt for a reason that has nothing to do with funding.
        """
        draft = self.paths.stage_tmp_file(self.STAGE)
        draft.parent.mkdir(parents=True, exist_ok=True)
        draft.write_text("# nothing useful here\n", encoding="utf-8")
        self._stub_operator(draft)
        self.operator.repair_stage_summary = MagicMock(
            return_value=MagicMock(
                success=True,
                exit_code=0,
                session_id="session-1",
                stage_file_path=draft,
                stdout="",
                stderr="",
            )
        )
        self.manager.reviewer = _StubReviewer(
            [ReviewDecision(choice="5", decision_token="approve")]
        )
        return self.manager._run_stage(self.paths, self.STAGE)

    def _rows(self) -> list[dict]:
        """The visits this stage actually made.

        ``bypassed`` rows are excluded and that is not a convenience: a bypassed row is a
        stage the run stepped *over* without entering, zeroed everywhere a measurement
        would go precisely because nothing was spent. Counting one as a visit funded at
        zero attempts would make this gate fire on the ledger working correctly.
        """
        return [
            row
            for row in read_stage_cost_ledger(self.paths)
            if row.get("outcome") != OUTCOME_BYPASSED
        ]

    def _last_error(self) -> str:
        manifest = load_run_manifest(self.paths.run_manifest)
        entry = next(item for item in manifest.stages if item.slug == self.STAGE.slug)
        return entry.last_error or ""


class TheFullStackFundsEveryVisitTests(FullStackFixture, unittest.TestCase):
    """Item 2: an offered backward move is an affordable one, with everything on.

    The assertion is never "a revisit is taken". Whether to go back is the agent's
    judgement and the whole point of the topology; what has to be guaranteed is that it
    stays available *and* affordable. So this asks two things and no more: the ceiling for
    a revisit is at least one real attempt, and no visit is recorded as ending with
    ``attempts == 0``.
    """

    def test_the_fixture_really_has_the_whole_stack_on(self) -> None:
        """A precondition, not a tautology.

        Every later assertion here is worthless if one of the mechanisms is off, and
        "supervisor, delivery reserve, effort tiers, a nearly-spent skip budget, the
        adaptive topology" is a list of separate switches that a refactor can flip one at
        a time. Each is asserted rather than assumed, so this class cannot go quietly
        green by measuring a plainer run than it claims to.
        """
        self.assertIsInstance(self.manager.supervisor, RunSupervisor)
        self.assertTrue(self.manager.unattended)
        self.assertTrue(self.manager.effort_plan.enabled)
        self.assertTrue(self.manager.concentration.polish_routine)
        self.assertEqual(self._skips_left(), DELIVERY_RESERVE + 1)
        self.assertEqual(self.manager.stage_graph.name, "adaptive")

    def test_every_revisit_target_is_funded_for_at_least_one_attempt(self) -> None:
        """Over every target a backward edge lands on, after two exhausted visits.

        The ceiling is asked for the way the attempt loop asks for it, on the supervisor
        the manager built, in a state that has closed visits on disk -- which is the state
        that used to return 0.
        """
        self.manager.max_stage_attempts = 2
        self._exhausting_visit()
        self._exhausting_visit()
        self.assertEqual(
            sum(row["attempts"] for row in self._rows()),
            4,
            "the fixture did not put two exhausted visits on disk",
        )
        for target in BACKWARD_TARGETS:
            with self.subTest(target=target):
                ceiling = self.manager.supervisor.attempt_ceiling(
                    target, self.manager.max_stage_attempts
                )
                self.assertIsNotNone(ceiling)
                self.assertGreaterEqual(
                    ceiling, 1, f"a revisit to {target} could not buy one attempt"
                )

    def test_a_revisit_after_an_exhausted_visit_still_buys_attempts(self) -> None:
        """The regression itself, end to end, with the rest of the machinery running.

        Exhaust the ceiling, come back, get approved. The second visit has to charge at
        least one attempt and must not end exhausted.

        The first visit is *not* asserted to return ``False``: unattended is one of the
        switches this fixture turns on, and an unattended exhaustion is auto-skipped and
        the run continues, so the loop reports success. What it may not do is skip the
        stage without exhausting it, which the ledger row says instead.
        """
        self.manager.max_stage_attempts = 3
        self._visit(
            ReviewDecision(choice="4", decision_token="revise", reason="no", feedback="again")
        )
        self.assertTrue(self._visit(ReviewDecision(choice="5", decision_token="approve")))
        rows = self._rows()
        self.assertEqual([row["visit"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["attempts"], 3, "the first visit charged the whole ceiling")
        self.assertTrue(rows[0]["exhausted"])
        self.assertGreaterEqual(rows[1]["attempts"], 1, "the revisit bought no attempt at all")
        self.assertFalse(rows[1]["exhausted"])
        self.assertNotIn("Exceeded 0 attempts", self._last_error())

    def test_no_visit_ends_with_no_attempts_bought(self) -> None:
        """The invariant over the whole two-visit run rather than at one boundary.

        A visit funded at zero is a backward edge that died before it ran, and the audit
        trail cannot even name the rule that ended it: the supervisor's ledger records
        ``continue / nothing_to_decide`` while the manifest says ``Exceeded 0 attempts``.
        """
        self.manager.max_stage_attempts = 2
        self._exhausting_visit()
        self._exhausting_visit()
        self.assertEqual(
            [row for row in self._rows() if row["attempts"] == 0],
            [],
            "a visit was funded at zero attempts",
        )
        self.assertEqual(
            [row["attempts"] for row in self._rows()],
            [2, 2],
            "the second visit was funded at less than the first",
        )
        self.assertNotIn("Exceeded 0 attempts", self._last_error())

    def test_a_reallocation_may_not_leave_a_revisit_target_unable_to_enter(self) -> None:
        """The other way the pool can starve a revisit, driven rather than argued.

        ``REALLOCATE`` narrows a stage's per-visit allowance and that narrowing persists
        across its later visits, which is the point of it. What it may not do is narrow
        one to nothing: a stage at zero per-visit allowance fails on entry with "Exceeded
        0 attempts" before it has run once, which is the re-pooling regression arrived at
        from the other side. Checked twice over -- the emptying transfer is refused, and
        the ceiling the attempt loop reads is still at least one after the largest
        transfer that is allowed.
        """
        supervisor = self.manager.supervisor
        # The public call that builds the pool, rather than reaching for the private one:
        # this is the same call the attempt loop makes.
        supervisor.attempt_ceiling(self.STAGE.slug, 8)
        pool = supervisor.allowance
        self.assertIsNotNone(pool)
        for target in BACKWARD_TARGETS:
            with self.subTest(target=target, transfer="everything it holds"):
                held = pool.allowance[target]
                with self.assertRaises(AllowanceError):
                    pool.transfer(target, ["08_dissemination"], held)
                self.assertEqual(
                    pool.allowance[target], held, "a refused transfer moved budget anyway"
                )
        for target in BACKWARD_TARGETS:
            pool.transfer(target, ["08_dissemination"], pool.allowance[target] - 1)
        for target in BACKWARD_TARGETS:
            with self.subTest(target=target, transfer="all but one"):
                self.assertGreaterEqual(supervisor.attempt_ceiling(target, 8), 1)


# ---------------------------------------------------------------------------
# 3. The pre-emption is a field, not a feature
# ---------------------------------------------------------------------------


class _FakeRoutingOperator:
    """The two private seams :class:`~src.router.StageRouter` drives a backend through.

    Serving the boundary rather than stubbing ``choose`` keeps the menu construction and
    the pre-emption branch under test, which is the half a stubbed ``choose`` hides.
    """

    fake_mode = False

    def __init__(self, response: str) -> None:
        self.response = response
        self.asked = 0

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
        return (["fake-backend"], paths.run_root, None)

    def _run_streaming_command(self, **kwargs):
        self.asked += 1
        return (0, self.response, "", None, {})


class ThePreEmptedDecisionIsCountedTests(unittest.TestCase):
    """Item 3: ``REDIRECT`` takes the choice away, and the count says how often.

    Not a view and not an artifact -- a field on
    :class:`~src.stage_graph.Visit`, carried into the routing summary the archive already
    reads. The number exists so that loosening
    :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT` moves a figure instead of
    quietly draining a capability.
    """

    #: ``04_implementation``. The node the redirect tests use, because the supervisor may
    #: only name a move the guards already left open and this is a node whose forward edge
    #: is open in the furnished fixture: ``design_artifacts`` reads the two files
    #: :func:`~tools.backward_edge_census.furnish` writes.
    NODE = STAGES[3]

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = furnished_run(Path(self._tmp.name))
        self.graph = StageGraph.adaptive()
        self.operator = _FakeRoutingOperator(
            json.dumps(
                {
                    "target": "03_study_design",
                    "reason": "Building it showed the metric cannot be computed as specified.",
                }
            )
        )

    def _choose(self, *, stage=None, required=None) -> RoutingDecision:
        return StageRouter(self.operator, mode="agent").choose(
            paths=self.paths,
            stage=stage or self.NODE,
            graph=self.graph,
            state=GraphState(),
            required=required,
        )

    def test_the_vocabulary_is_declared_and_closed(self) -> None:
        self.assertIn(SUPERVISOR_PREEMPTION, PREEMPTIONS)
        with self.assertRaises(ValueError):
            RoutingDecision(
                "06_analysis", "advance", "why", "06_analysis", False,
                preempted_by="whoever",
            )

    def test_a_decision_the_agent_made_is_not_a_pre_emption(self) -> None:
        """The control. A field that is always set counts nothing."""
        decision = self._choose()
        self.assertEqual(decision.target, "03_study_design")
        self.assertTrue(decision.agent_directed)
        self.assertEqual(decision.preempted_by, "")
        self.assertEqual(self.operator.asked, 1)

    def test_a_supervisor_redirect_is_recorded_as_one_and_the_agent_is_not_asked(self) -> None:
        decision = self._choose(required=("05_experimentation", "two visits ended unsettled"))
        self.assertEqual(decision.target, "05_experimentation")
        self.assertFalse(decision.agent_directed)
        self.assertEqual(decision.preempted_by, SUPERVISOR_PREEMPTION)
        self.assertEqual(
            self.operator.asked, 0, "the agent was asked after the decision was pre-empted"
        )

    def test_a_redirect_the_guards_shut_is_a_refusal_and_not_a_pre_emption(self) -> None:
        """The ask did not happen, but neither did the redirect.

        Recording it as a pre-emption would count the supervisor as having taken a choice
        it did not get. It is already counted as a refusal, which is what it is. Driven at
        ``06_analysis``, where ``validity_chain`` holds ``07_writing`` shut in this
        fixture, so the refusal is a guard's rather than a typo's.
        """
        decision = self._choose(
            stage=STAGES[5], required=("07_writing", "stop revisiting and write it up")
        )
        self.assertNotIn("07_writing", decision.offered)
        self.assertEqual(decision.blocked.get("07_writing"), "guard")
        self.assertIn("the hypotheses were never frozen", decision.refusal)
        self.assertEqual(decision.preempted_by, "")
        # The target is asserted last and only for what it is *not*. `default_move`
        # last-resorts forward when every forward edge is guard-shut, so the fallback out
        # of `06_analysis` is `07_writing` too -- the same slug reached by a different
        # route, which is exactly why a test that compared targets alone would report the
        # redirect as honoured.
        self.assertFalse(decision.agent_directed)

    def test_the_count_reaches_the_routing_summary_beside_the_chosen_one(self) -> None:
        """One number, in the record that already exists.

        Written the way the manager writes it -- through ``leave`` into
        ``evolution/stage_graph.json`` -- and read back through the shipped
        :func:`~src.router.routing_summary`, so a field that reached the dataclass and not
        the file would fail here.
        """
        state = GraphState()
        enter(self.paths, state, STAGES[5])
        leave(
            self.paths, state,
            chose="07_writing", kind="advance", reason="the supervisor required it",
            default_choice="07_writing", agent_directed=False, score_total=None,
            offered=("05_experimentation", "07_writing"),
            preempted_by=SUPERVISOR_PREEMPTION,
        )
        enter(self.paths, state, STAGES[6])
        leave(
            self.paths, state,
            chose="06_analysis", kind="revisit", reason="the figure does not show it",
            default_choice="08_dissemination", agent_directed=True, score_total=None,
            offered=("06_analysis", "08_dissemination"),
        )
        summary = routing_summary(self.paths)
        self.assertEqual(summary["preempted"], 1)
        self.assertEqual(summary["agent_directed"], 1)
        self.assertEqual(summary["steps"], 2)

    def test_the_count_reaches_the_archive_record_so_it_is_comparable_across_runs(
        self,
    ) -> None:
        """A number one run holds is a number nothing can watch move.

        The threshold this counter exists to watch is
        :data:`~src.supervisor.UNSETTLED_VISITS_BEFORE_A_REDIRECT`, and a loosening of it
        is visible only against other runs -- so the count goes where every other
        run-level routing figure goes, beside ``agent_directed`` and ``bypassed`` on
        :class:`~src.archive.RunRecord`. Driven through the real
        :meth:`~src.archive.Archive.record_run` and round-tripped through the record's own
        serialisation, because a field that reaches the dataclass and not ``runs.jsonl``
        is a field the next run cannot read.
        """
        state = GraphState()
        enter(self.paths, state, self.NODE)
        leave(
            self.paths, state,
            chose="05_experimentation", kind="advance", reason="the supervisor required it",
            default_choice="05_experimentation", agent_directed=False, score_total=None,
            offered=("03_study_design", "05_experimentation"),
            preempted_by=SUPERVISOR_PREEMPTION,
        )
        write_text(
            self.paths.evolution_dir / "summary.json",
            json.dumps(
                {
                    "rubric_version": RUBRIC_VERSION,
                    "stages": {self.NODE.slug: {"total": 0.8}},
                }
            ),
        )
        archive = Archive(Path(self._tmp.name) / "archive")
        record = archive.record_run(self.paths, provenance="fake")
        self.assertIsNotNone(record)
        self.assertEqual(record.preempted, 1)
        self.assertEqual(RunRecord.from_dict(record.to_dict()).preempted, 1)
        self.assertEqual(archive.runs()[0].preempted, 1)

    def test_a_visit_written_before_the_field_existed_counts_as_not_pre_empted(self) -> None:
        """Absent is not pre-empted. An older ``stage_graph.json`` has no such key, and
        reading a missing key as a pre-emption would invent a count for every archived
        run."""
        self.assertEqual(Visit.from_dict({"stage": "06_analysis"}).preempted_by, "")
        payload = {
            "path": [
                {
                    "stage": "06_analysis",
                    "chose": "07_writing",
                    "offered": ["07_writing"],
                }
            ]
        }
        write_text(
            self.paths.evolution_dir / "stage_graph.json", json.dumps(payload)
        )
        self.assertEqual(routing_summary(self.paths)["preempted"], 0)

    def test_the_manager_carries_the_field_from_the_decision_to_the_visit(self) -> None:
        """The seam between the two halves, driven rather than read out of the source.

        A field set on the decision and dropped at ``graph_leave`` would leave every gate
        above green and the count permanently zero.
        """
        manager = ResearchManager(
            project_root=REPO,
            runs_dir=Path(self._tmp.name) / "runs",
            operator=self.operator,
            ui=TerminalUI(output_stream=io.StringIO()),
            unattended=True,
        )
        manager._print = MagicMock()
        for _ in range(UNSETTLED_VISITS_BEFORE_A_REDIRECT):
            meter = StageCostMeter(self.NODE)
            meter.note_attempt()
            meter.note_outcome(OUTCOME_AUTO_SKIPPED)
            append_stage_cost_row(self.paths, meter.close())
        ruling = manager.supervisor.review_stage_exit(
            paths=self.paths,
            stage_slug=self.NODE.slug,
            admissible_forward=["05_experimentation"],
        )
        self.assertEqual(ruling.kind, REDIRECT, "the fixture did not reach a redirect")

        state = GraphState()
        enter(self.paths, state, self.NODE)
        manager.stage_graph = self.graph
        manager._advance_from(self.paths, state, self.NODE)
        self.assertEqual(state.path[-1].preempted_by, SUPERVISOR_PREEMPTION)
        self.assertEqual(routing_summary(self.paths)["preempted"], 1)


# ---------------------------------------------------------------------------
# The instrument behind the table
# ---------------------------------------------------------------------------


class TheCensusInstrumentIsTheGateTests(unittest.TestCase):
    """The before/after table, checked to be a measurement rather than a rendering.

    An instrument that reimplements the rule measures a copy of it, and the copy is the
    one that stays right. This pins the census to importing the shipped graph and the
    shipped router, and to producing the same offered sets the gate above compares.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = furnished_run(Path(self._tmp.name))

    def test_it_calls_the_shipped_router_rather_than_a_model_of_it(self) -> None:
        source = (REPO / "tools" / "backward_edge_census.py").read_text(encoding="utf-8")
        self.assertIn("from src.router import", source)
        self.assertIn("from src.stage_graph import", source)
        self.assertIn("StageRouter(", source)
        self.assertIn("RunSupervisor(", source)
        # A copy of a rule is the copy that stays right. None of these may be redefined
        # here: the reserve's predicate, the block vocabulary, or the topology.
        for redefinition in (
            "def revisit_would_strand_delivery",
            "BLOCK_KINDS = (",
            "REVISIT_EDGES = (",
        ):
            with self.subTest(symbol=redefinition):
                self.assertNotIn(redefinition, source)

    def test_the_table_counts_the_thirteen_backward_edges(self) -> None:
        rows = CENSUS.census(self.paths, skips_left=DELIVERY_RESERVE + 1)
        self.assertEqual(len(rows), len(REVISIT_EDGES))
        self.assertEqual(
            {(row.source, row.target) for row in rows},
            {(edge.source, edge.target) for edge in REVISIT_EDGES},
        )

    def test_it_reports_a_declared_kind_for_every_difference(self) -> None:
        rows = CENSUS.census(self.paths, skips_left=DELIVERY_RESERVE)
        differing = [row for row in rows if row.bare and not row.stack]
        self.assertEqual(len(differing), len(REVISIT_EDGES))
        for row in differing:
            with self.subTest(edge=f"{row.source}->{row.target}"):
                self.assertIn(row.kind, BLOCK_KINDS)

    def test_it_names_an_undeclared_narrowing_rather_than_hiding_it(self) -> None:
        """The instrument's own control.

        A row that left the menu with no kind recorded has to be reported as
        ``undeclared``, not as an empty cell -- otherwise the table a reviewer reads is
        exactly as blind as the suite was.
        """
        row = CENSUS.Row(
            source="06_analysis", target="05_experimentation", bare=True, stack=False, kind=""
        )
        self.assertTrue(row.undeclared)
        self.assertFalse(
            CENSUS.Row(
                source="06_analysis", target="05_experimentation",
                bare=True, stack=False, kind="budget",
            ).undeclared
        )

    def test_the_docstrings_two_counts_are_the_measured_ones(self) -> None:
        """The instrument's own prose, checked against the instrument.

        Two spelled-out numbers: how many backward edges there are, and how many of them
        an empty workspace shuts in *both* columns. The second is the reason the default
        is a furnished workspace, so a reader who cannot re-derive it cannot check the
        argument for the default either. Same rule ``tests/test_doc_counts.py`` applies to
        the docs, applied to a tool: prose has no compiler.
        """
        words = {4: "four", 9: "nine", 13: "thirteen", 14: "fourteen"}
        doc = CENSUS.__doc__ or ""
        self.assertIn(f"{words[len(REVISIT_EDGES)]} backward edges", doc)

        bare_root = Path(self._tmp.name) / "unfurnished"
        paths = build_run_paths(bare_root / "runs" / "run_0001")
        ensure_run_layout(paths)
        write_text(paths.user_input, "An empty workspace.")
        rows = CENSUS.census(paths, skips_left=DELIVERY_RESERVE + 1)
        shut = [row for row in rows if not row.bare and not row.stack]
        self.assertTrue(shut, "the empty workspace shut nothing, so the claim is untestable")
        self.assertEqual({row.kind for row in shut}, {"guard"})
        self.assertIn(
            f"on {words[len(shut)]} of the {words[len(REVISIT_EDGES)]} edges", doc
        )

    def test_it_runs_and_prints_both_columns(self) -> None:
        text = CENSUS.table(self.paths, skips_left=DELIVERY_RESERVE + 1)
        self.assertIn("bare", text)
        self.assertIn("stack", text)
        for edge in REVISIT_EDGES:
            with self.subTest(edge=f"{edge.source}->{edge.target}"):
                self.assertIn(f"{edge.source}->{edge.target}", text)


# ---------------------------------------------------------------------------
# The mutation sweep, as an instrument
# ---------------------------------------------------------------------------

MANAGER_FILE = "src/manager.py"
SUPERVISOR_FILE = "src/supervisor.py"
ROUTER_FILE = "src/router.py"
GRAPH_FILE = "src/stage_graph.py"
ARCHIVE_FILE = "src/archive.py"

#: ``(what it breaks, file, the text to replace, what to replace it with)``.
#:
#: The same shape ``tests/test_run_supervisor.SUPERVISOR_MUTATIONS`` uses. The first three
#: are the mutation that matters: the attempt budget re-pooled from per visit to per stage
#: across visits, at each of the three layers where that is expressible -- the ceiling the
#: loop enforces, the loop's own counter, and the supervisor's pool. #249 shipped the
#: first of those shapes and no test went red.
STACK_MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("re-pooled at the ceiling: it charges the stage's closed visits again", MANAGER_FILE,
     "            ceiling = self.supervisor.attempt_ceiling(stage.slug, self.max_stage_attempts)",
     "            ceiling = max(\n"
     "                self.supervisor.attempt_ceiling(stage.slug, self.max_stage_attempts)\n"
     "                - self.supervisor.closed_spend(paths).get(stage.slug, 0),\n"
     "                0,\n"
     "            )"),
    ("re-pooled at the loop counter: attempts count per stage, not per visit", MANAGER_FILE,
     "        attempt_no = read_attempt_count(paths, stage) + 1\n        loop_attempts = 0",
     "        attempt_no = read_attempt_count(paths, stage) + 1\n"
     "        loop_attempts = read_attempt_count(paths, stage)"),
    ("re-pooled in the pool: a stage's closed spend is charged to its allowance",
     SUPERVISOR_FILE,
     "        pool = self._pool(per_stage_ceiling)\n        unentered = [",
     "        pool = self._pool(per_stage_ceiling)\n"
     "        if pool is not None and closed.get(stage_slug, 0):\n"
     "            pool.allowance[stage_slug] = max(\n"
     "                pool.allowance.get(stage_slug, 0) - closed.get(stage_slug, 0), 0\n"
     "            )\n"
     "        unentered = ["),
    ("the router narrows the menu with nothing recorded", ROUTER_FILE,
     "        offered = tuple(sorted(move.target for move in live))",
     "        offered = tuple(\n"
     "            sorted(\n"
     "                move.target\n"
     "                for move in live\n"
     "                if move.edge.kind != \"revisit\" or move.replay_cost < 3\n"
     "            )\n"
     "        )"),
    ("the reserve stops declaring a block kind and drops the edge instead", GRAPH_FILE,
     "        return _preempted_by_a_conclusion(results)",
     "        return _preempted_by_a_conclusion(\n"
     "            [\n"
     "                move\n"
     "                for move in results\n"
     "                if not (move.blocked_kind == \"budget\" and move.edge.kind == \"revisit\")\n"
     "            ]\n"
     "        )"),
    ("the reserve withdraws a backward move one unit early", GRAPH_FILE,
     "    return skips_left <= reserve", "    return skips_left <= reserve + 1"),
    ("the pre-emption is never recorded", ROUTER_FILE,
     "                preempted_by=SUPERVISOR_PREEMPTION,", "                preempted_by=\"\","),
    ("the pre-emption is recorded on every decision, so the count says nothing", ROUTER_FILE,
     "    preempted_by: str = \"\"\n",
     "    preempted_by: str = SUPERVISOR_PREEMPTION\n"),
    ("the visit drops the field on the way to disk", GRAPH_FILE,
     "            \"preempted_by\": self.preempted_by,", "            \"preempted_by\": \"\","),
    ("the manager drops the field on the way to the visit", MANAGER_FILE,
     "            preempted_by=decision.preempted_by,", "            preempted_by=\"\","),
    ("the summary counts a pre-emption as an agent's choice", ROUTER_FILE,
     "        if visit.get(\"preempted_by\"):", "        if False:"),
    ("the archive record drops the count on the way in", ARCHIVE_FILE,
     "            preempted=int(summary.get(\"preempted\") or 0),", "            preempted=0,"),
    ("the archive record drops the count on the way to disk", ARCHIVE_FILE,
     "            \"preempted\": self.preempted,", "            \"preempted\": 0,"),
    ("a donor may empty a revisit target's allowance", SUPERVISOR_FILE,
     "        if held is None or units >= held:", "        if held is None or units > held:"),
)

#: Tests that die under every mutation because applying one is what stops their own anchor
#: from matching. Subtracting them is what keeps a kill an actual kill.
STACK_SWEEP_SELF_TESTS = frozenset({"test_every_anchor_matches_its_file_exactly_once"})


def _dead_tests(root: Path) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", __spec__.name if __spec__ else __name__, "-v"],
        cwd=root, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    dead = set(re.findall(r"^(\w+) \(tests\.[\w.]+\) \.\.\. (?:FAIL|ERROR)", out, re.M))
    dead |= set(re.findall(r"^(?:FAIL|ERROR): (\w+) ", out, re.M))
    return dead - STACK_SWEEP_SELF_TESTS


def run_mutations(root: Path | None = None) -> int:
    """Apply each of :data:`STACK_MUTATIONS` in turn; return the survivor count.

    Restores every file in a ``finally``, so an interrupted sweep leaves the tree as it
    found it -- but it does edit the tree, so run it in a scratch checkout.
    """
    root = root or Path(__file__).resolve().parent.parent
    baseline = _dead_tests(root)
    if baseline:
        print(f"REFUSED: the tree is not green before mutating: {sorted(baseline)}")
        return len(baseline)
    print(f"baseline green; {len(STACK_MUTATIONS)} mutations to try\n")
    survivors: list[str] = []
    for name, relative, old, new in STACK_MUTATIONS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} anchor matches): {name}")
            survivors.append(name)
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        try:
            dead = _dead_tests(root)
        finally:
            path.write_text(text, encoding="utf-8")
        if dead:
            print(f"killed  {name}\n            by: {', '.join(sorted(dead))}")
        else:
            print(f"SURVIVED  {name}")
            survivors.append(name)
    print(f"\ntried {len(STACK_MUTATIONS)}, "
          f"killed {len(STACK_MUTATIONS) - len(survivors)}, survivors {len(survivors)}")
    for name in survivors:
        print("   SURVIVOR:", name)
    return len(survivors)


class TheSweepIsRunnableTests(unittest.TestCase):
    """The instrument, checked without running it: fourteen subprocess suites is not a
    unit test.

    What goes stale without anyone noticing is an *anchor*, and an anchor that no longer
    matches is a mutation silently not applied -- which reads in the output exactly like
    one that was killed.
    """

    def test_the_docstring_says_how_many_mutations_there_are(self) -> None:
        """A count in prose beside the tuple it counts, pinned to the tuple.

        The same rule ``tests/test_doc_counts.py`` applies to the docs: a spelled-out
        number next to a countable noun is a claim, and prose has no compiler.
        """
        words = {12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen"}
        self.assertIn(len(STACK_MUTATIONS), words, "spell the new count out below")
        self.assertIn(
            f"{words[len(STACK_MUTATIONS)]} subprocess suites",
            TheSweepIsRunnableTests.__doc__ or "",
        )

    def test_every_anchor_matches_its_file_exactly_once(self) -> None:
        for name, relative, old, _new in STACK_MUTATIONS:
            with self.subTest(mutation=name):
                text = (REPO / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    text.count(old), 1,
                    f"{name}: anchor matches {text.count(old)} times in {relative}",
                )

    def test_no_mutation_leaves_the_file_unchanged(self) -> None:
        for name, _relative, old, new in STACK_MUTATIONS:
            with self.subTest(mutation=name):
                self.assertNotEqual(old, new, f"{name} is not a mutation")

    def test_the_self_test_exclusion_names_a_test_that_exists(self) -> None:
        for name in STACK_SWEEP_SELF_TESTS:
            self.assertTrue(hasattr(TheSweepIsRunnableTests, name), name)

    def test_the_re_pooling_regression_is_covered_at_every_layer_it_lives_at(self) -> None:
        """The mutation that matters is the one that already happened.

        Three layers can re-pool the attempt budget from per visit to per stage: the
        ceiling the loop enforces, the loop's own counter, and the supervisor's pool. A
        sweep that covered one of them would be a sweep of the line #249 happened to
        touch rather than of the defect.
        """
        repooling = [name for name, *_ in STACK_MUTATIONS if name.startswith("re-pooled")]
        self.assertEqual(len(repooling), 3, repooling)
        self.assertEqual(
            [name for name, *_ in STACK_MUTATIONS[:3]],
            repooling,
            "the module docstring says the first three entries are the re-pooling ones",
        )
        self.assertEqual(
            {relative for _n, relative, _o, _w in STACK_MUTATIONS[:3]},
            {MANAGER_FILE, SUPERVISOR_FILE},
            "two of the three layers are the manager's and one is the supervisor's",
        )

    def test_the_sweep_covers_every_file_this_pass_touched(self) -> None:
        self.assertEqual(
            {relative for _n, relative, _o, _w in STACK_MUTATIONS},
            {MANAGER_FILE, SUPERVISOR_FILE, ROUTER_FILE, GRAPH_FILE, ARCHIVE_FILE},
        )


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        raise SystemExit(1 if run_mutations() else 0)
    unittest.main()
