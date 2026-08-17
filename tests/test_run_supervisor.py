"""The supervisor decides things, so what it can decide has to be bounded by a test.

Three questions this file answers, in the order a reviewer asks them.

**Can it ever make a gate pass?** No, and not because the docstring says so. The three
things that hold it are checkable and each has a test that dies when the rule is reverted:
:meth:`~src.supervisor.AttemptAllowance.ceiling` is a ``min`` against the run's own
``--max-attempts``, so ``NoInterventionRaisesABudgetTests`` sweeps every allowance state
reachable by transfer and finds none that hands back a larger number;
:meth:`~src.supervisor.AttemptAllowance.transfer` asserts conservation on the way out, so
a transfer that would not conserve raises rather than clamps; and the manager's only
response to a ruling that ends a visit is the stage-exhaustion recovery path that already
existed, which ``TheManagerIsWiredToTheSupervisorTests`` reads out of the source rather
than trusting.

**Does it read anything the party it constrains can write?**
``SupervisorReadsOnlyHarnessFieldsTests`` parses every ``paths.<field>`` in
``src/supervisor.py``, resolves each against ``build_run_paths``, and fails if one lands
under ``workspace/`` -- the directory every stage prompt sends an operator running with
``bypassPermissions``. The control below fabricates a module that reads one and shows the
scan catching it, because a scan that finds nothing and a scan that looks for nothing are
the same green.

**Are the thresholds measured?** The values are pinned to the module docstring's account
of what they were measured against, and the replay that produced them,
``tools/supervisor_threshold_replay.py``, is pinned to importing the shipped predicates
rather than reimplementing them. An instrument that reimplements the rule it measures
reports on a program that does not exist.
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
import unittest
from pathlib import Path

from src.stage_cost import (
    OUTCOME_APPROVED,
    OUTCOME_AUTO_SKIPPED,
    StageCostMeter,
    append_stage_cost_row,
    failure_digest,
)
from src.supervisor import (
    CONTINUE,
    DISPROPORTIONATE_MULTIPLE,
    DISPROPORTIONATE_SPEND,
    ESCALATE,
    INTERVENTION_EFFECTS,
    INTERVENTIONS,
    MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION,
    NO_RECOVERY_LEFT,
    NOTHING_TO_DECIDE,
    REALLOCATE,
    REDIRECT,
    STOP_AFTER_IDENTICAL_FAILURES,
    STOP_SPENDING,
    SUPERVISOR_LEDGER_FILENAME,
    SUPERVISOR_RULES,
    UNCHANGING_FAILURE,
    UNFUNDED_REVISIT,
    UNSETTLED_VISITS_BEFORE_A_REDIRECT,
    AllowanceError,
    AttemptAllowance,
    Intervention,
    RunSupervisor,
    disproportionate,
    longest_unchanged_run,
    ration,
    supervisor_ledger_path,
    unchanging_failure,
    unsettled_visits,
)
from src.router import StageRouter
from src.stage_graph import GraphState, StageGraph
from src.utils import STAGES, RunPaths, build_run_paths, ensure_run_layout, write_text

REPO = Path(__file__).resolve().parent.parent
SUPERVISOR_SOURCE = (REPO / "src" / "supervisor.py").read_text(encoding="utf-8")
REPLAY_SOURCE = (REPO / "tools" / "supervisor_threshold_replay.py").read_text(encoding="utf-8")
MANAGER_SOURCE = (REPO / "src" / "manager.py").read_text(encoding="utf-8")

SLUGS = [stage.slug for stage in STAGES]
WRITING = "07_writing"
WRITING_NUMBER = next(stage.number for stage in STAGES if stage.slug == WRITING)


def fresh_paths(root: str) -> RunPaths:
    paths = build_run_paths(Path(root) / "run")
    ensure_run_layout(paths)
    paths.run_root.mkdir(parents=True, exist_ok=True)
    return paths


def a_meter(slug: str, *, failures: list[str] | None = None, polish: int = 0) -> StageCostMeter:
    """An open meter carrying *failures* as one attempt each, plus *polish* rounds."""
    stage = next(item for item in STAGES if item.slug == slug)
    meter = StageCostMeter(stage)
    number = 0
    for reason in failures or []:
        number += 1
        meter.note_attempt()
        meter.note_failure(number, "validators_refused", reason)
    for _ in range(polish):
        number += 1
        meter.note_attempt()
        meter.note_polish_round(number)
    return meter


def close_a_visit(paths: RunPaths, slug: str, *, charged: int, outcome: str = OUTCOME_APPROVED) -> None:
    """Put one finished visit in the cost ledger, charging *charged* attempts."""
    meter = a_meter(slug)
    for _ in range(charged):
        meter.note_attempt()
    meter.note_outcome(outcome)
    append_stage_cost_row(paths, meter.close())


CEILING = 8


def a_supervisor(*, skips: int = 3) -> RunSupervisor:
    return RunSupervisor(stage_slugs=SLUGS, max_auto_skips=skips)


def rule_on(
    supervisor: RunSupervisor,
    paths: RunPaths,
    slug: str,
    *,
    meter: StageCostMeter | None = None,
    attempt: int = 1,
    skips_spent: int = 0,
    ceiling: int | None = CEILING,
) -> Intervention:
    number = next(item.number for item in STAGES if item.slug == slug)
    return supervisor.review_attempt(
        paths=paths,
        stage_slug=slug,
        stage_number=number,
        meter=meter,
        attempt_no=attempt,
        auto_skips_spent=skips_spent,
        deliverable_number=WRITING_NUMBER,
        per_stage_ceiling=ceiling,
    )


# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------


class TheVocabularyIsDeclaredAndBoundedTests(unittest.TestCase):
    def test_the_five_interventions_are_exactly_the_declared_ones(self) -> None:
        self.assertEqual(
            INTERVENTIONS,
            (CONTINUE, STOP_SPENDING, REALLOCATE, REDIRECT, ESCALATE),
        )

    def test_every_intervention_has_a_permitted_effect_and_no_other_does(self) -> None:
        """A ruling nobody wrote a bound for is a ruling with no bound."""
        self.assertEqual(sorted(INTERVENTION_EFFECTS), sorted(INTERVENTIONS))

    def test_no_permitted_effect_approves_anything(self) -> None:
        """The invariant, read off the table a caller is allowed to act on."""
        for kind, effect in INTERVENTION_EFFECTS.items():
            with self.subTest(kind=kind):
                for forbidden in ("approve", "pass", "discharge", "satisfy", "raise the"):
                    self.assertNotIn(forbidden, effect.lower())

    def test_a_ruling_outside_the_vocabulary_is_refused_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            Intervention(kind="approve", rule=NOTHING_TO_DECIDE, stage=WRITING, because="")

    def test_a_rule_outside_the_registry_is_refused_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            Intervention(kind=CONTINUE, rule="because_i_said_so", stage=WRITING, because="")

    def test_every_rule_in_the_registry_is_reachable(self) -> None:
        """A rule nothing can decide is a row in a table and not a rule.

        Each name has to appear in a ``rule=`` argument somewhere in the module, which is
        the only place a ruling can be built.
        """
        built = set(re.findall(r"rule=([A-Z_]+),", SUPERVISOR_SOURCE))
        expected = {
            "NOTHING_TO_DECIDE",
            "UNCHANGING_FAILURE",
            "DISPROPORTIONATE_SPEND",
            "UNFUNDED_REVISIT",
            "NO_RECOVERY_LEFT",
        }
        self.assertEqual(built, expected)
        self.assertEqual(len(SUPERVISOR_RULES), len(expected))


# ---------------------------------------------------------------------------
# The invariant
# ---------------------------------------------------------------------------


class NoInterventionRaisesABudgetTests(unittest.TestCase):
    """The supervisor may stop and may move; it may never add."""

    def test_the_ceiling_is_never_above_the_runs_own(self) -> None:
        """Swept over every allowance state a sequence of transfers can reach.

        Not a spot check: the whole point of the ``min`` is that no state of the ledger
        can defeat it, and a single example would leave that as a hope.
        """
        allowance = AttemptAllowance(["a", "b", "c"], 8)
        for donor, recipient, units in (("a", ["b"], 8), ("b", ["c"], 5), ("c", ["a", "b"], 4)):
            allowance.transfer(donor, recipient, units)
            for slug in ("a", "b", "c"):
                for spent in range(0, 20):
                    with self.subTest(slug=slug, spent=spent):
                        self.assertLessEqual(allowance.ceiling(slug, spent), 8)

    def test_a_recipient_that_holds_more_than_the_ceiling_still_gets_the_ceiling(self) -> None:
        """The case the ``min`` exists for: allowance above ``--max-attempts``."""
        allowance = AttemptAllowance(["a", "b"], 8)
        allowance.transfer("a", ["b"], 8)
        self.assertEqual(allowance.allowance["b"], 16)
        self.assertEqual(allowance.ceiling("b", 0), 8)

    def test_a_transfer_conserves_the_total(self) -> None:
        allowance = AttemptAllowance(SLUGS, 8)
        before = allowance.total
        allowance.transfer(SLUGS[0], SLUGS[1:4], 6)
        self.assertTrue(allowance.conserved())
        self.assertEqual(allowance.total, before)
        self.assertEqual(sum(allowance.allowance.values()), before)

    def test_a_transfer_that_would_not_conserve_is_refused_rather_than_clamped(self) -> None:
        """The net under a future edit, and what it catches.

        The arithmetic in :meth:`AttemptAllowance.transfer` conserves by construction
        today, so the only way to reach the check is to hand it a ledger that has already
        drifted from its declared total -- which is exactly the state a later edit
        recomputing an allowance somewhere else would produce, and exactly what the check
        is a net under. A budget that silently rounds itself back into shape is a budget
        nobody can audit, so it raises.
        """
        allowance = AttemptAllowance(["a", "b"], 8)
        allowance.total = 99
        with self.assertRaises(AllowanceError):
            allowance.transfer("a", ["b"], 1)

    def test_a_transfer_larger_than_the_donor_holds_is_refused(self) -> None:
        allowance = AttemptAllowance(["a", "b"], 8)
        with self.assertRaises(AllowanceError):
            allowance.transfer("a", ["b"], 9)
        self.assertTrue(allowance.conserved())

    def test_a_transfer_to_nobody_moves_nothing(self) -> None:
        allowance = AttemptAllowance(["a"], 8)
        self.assertEqual(allowance.transfer("a", [], 4), 0)
        self.assertEqual(allowance.allowance["a"], 8)

    def test_the_run_declaring_no_ceiling_gets_no_pool(self) -> None:
        """The supervisor does not invent a bound the operator declined."""
        supervisor = a_supervisor()
        self.assertIsNone(supervisor.allowance)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            self.assertIsNone(supervisor.attempt_ceiling(paths, WRITING, None))
            self.assertIsNone(supervisor.allowance)

    def test_a_first_visit_gets_exactly_what_the_run_allows(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            self.assertEqual(supervisor.attempt_ceiling(paths, "03_study_design", CEILING), 8)

    def test_a_second_visit_gets_what_the_stage_has_left_and_not_a_fresh_ceiling(self) -> None:
        """The status quo hands every visit a fresh ``--max-attempts``; the pool does not."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            close_a_visit(paths, "06_analysis", charged=6)
            self.assertEqual(supervisor.attempt_ceiling(paths, "06_analysis", CEILING), 2)

    def test_reallocating_never_lifts_a_ceiling_above_the_runs_own(self) -> None:
        """End to end: the one intervention that moves budget, then the ceiling."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=1)
            # Three charged against a median of one is disproportionate, and the ration it
            # leaves (3 + 1) is still under the stage's allowance, so there is a surplus to
            # move. A stage that has already charged more than its allowance minus the
            # median has nothing unspent left and gets a `continue` instead -- budget that
            # is spent cannot be reallocated, which is arithmetic rather than policy.
            meter = a_meter("03_study_design", failures=["a", "b", "c"])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=4)
            self.assertEqual(ruling.kind, REALLOCATE)
            self.assertTrue(supervisor.allowance.conserved())
            for slug in SLUGS:
                with self.subTest(slug=slug):
                    self.assertLessEqual(supervisor.attempt_ceiling(paths, slug, CEILING), 8)


# ---------------------------------------------------------------------------
# What it is allowed to read
# ---------------------------------------------------------------------------


def paths_fields_read(source: str) -> set[str]:
    """Every ``<name>.<field>`` where ``<name>`` is a ``RunPaths`` parameter.

    An AST walk rather than a text search, because a text search is what a comment
    mentioning ``paths.workspace`` would fool, and this check is the one that has to be
    hard to fool.
    """
    tree = ast.parse(source)
    holders = {"paths"}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in holders:
                found.add(node.attr)
    return found


class SupervisorReadsOnlyHarnessFieldsTests(unittest.TestCase):
    def test_no_path_the_supervisor_reads_is_under_the_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            workspace = paths.workspace_root.resolve()
            for attr in sorted(paths_fields_read(SUPERVISOR_SOURCE)):
                value = getattr(paths, attr, None)
                if not isinstance(value, Path):
                    continue
                with self.subTest(field=attr):
                    self.assertFalse(
                        value.resolve().is_relative_to(workspace),
                        f"src/supervisor.py reads paths.{attr}, which is under workspace/ -- "
                        "the directory the supervised operator is sent to write in",
                    )

    def test_the_ledger_it_writes_is_outside_the_workspace_too(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            self.assertFalse(
                supervisor_ledger_path(paths).resolve().is_relative_to(paths.workspace_root.resolve())
            )
            self.assertEqual(supervisor_ledger_path(paths).name, SUPERVISOR_LEDGER_FILENAME)

    def test_the_scan_would_catch_a_supervisor_that_read_the_workspace(self) -> None:
        """Control. The assertion above passes whether or not the scan sees anything."""
        fabricated = "def rule(paths):\n    return paths.workspace_root.exists()\n"
        self.assertIn("workspace_root", paths_fields_read(fabricated))


# ---------------------------------------------------------------------------
# stop_spending
# ---------------------------------------------------------------------------


class UnchangingFailureTests(unittest.TestCase):
    def test_the_threshold_is_the_shipped_one(self) -> None:
        self.assertEqual(STOP_AFTER_IDENTICAL_FAILURES, 2)

    def test_it_fires_at_the_threshold_and_not_one_short(self) -> None:
        digest = failure_digest("validators_refused", "report_plan.json task output 1 states nothing")
        self.assertFalse(unchanging_failure([digest] * (STOP_AFTER_IDENTICAL_FAILURES - 1)))
        self.assertTrue(unchanging_failure([digest] * STOP_AFTER_IDENTICAL_FAILURES))

    def test_two_objections_alternating_are_not_one_objection_repeating(self) -> None:
        """A stage being told different things is still being told something."""
        self.assertFalse(unchanging_failure(["a", "b", "a", "b", "a", "b"]))
        self.assertEqual(longest_unchanged_run(["a", "b", "a", "b"]), 1)

    def test_progress_then_a_repeat_only_counts_the_tail(self) -> None:
        self.assertEqual(longest_unchanged_run(["a", "b", "b", "c"]), 2)
        self.assertEqual(longest_unchanged_run([]), 0)

    def test_the_supervisor_stops_a_visit_repeating_one_refusal(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter("03_study_design", failures=["report_plan.json task output 1 states nothing"] * 2)
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=3)
            self.assertEqual(ruling.kind, STOP_SPENDING)
            self.assertEqual(ruling.rule, UNCHANGING_FAILURE)
            self.assertTrue(ruling.ends_the_visit)
            self.assertEqual(ruling.evidence["longest_unchanged_run"], 2)

    def test_a_visit_failing_differently_is_left_alone(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter("03_study_design", failures=["one", "two", "three", "four"])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=5)
            self.assertEqual(ruling.kind, CONTINUE)
            self.assertFalse(ruling.ends_the_visit)

    def test_a_polish_round_does_not_break_a_run_of_one_refusal(self) -> None:
        """Polish rounds are not failures, and the meter leaves them out of the digests."""
        stage = next(item for item in STAGES if item.slug == "03_study_design")
        meter = StageCostMeter(stage)
        meter.note_attempt()
        meter.note_failure(1, "validators_refused", "same")
        meter.note_attempt()
        meter.note_polish_round(2)
        meter.note_attempt()
        meter.note_failure(3, "validators_refused", "same")
        digests = [entry["digest"] for entry in meter.attempt_digests()]
        self.assertTrue(unchanging_failure(digests))


# ---------------------------------------------------------------------------
# reallocate
# ---------------------------------------------------------------------------


class DisproportionateSpendTests(unittest.TestCase):
    def test_the_thresholds_are_the_shipped_ones(self) -> None:
        self.assertEqual(DISPROPORTIONATE_MULTIPLE, 2)
        self.assertEqual(MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION, 3)

    def test_it_fires_above_the_multiple_and_not_at_it(self) -> None:
        closed = [2, 2, 4]
        self.assertFalse(disproportionate(4, closed))
        self.assertTrue(disproportionate(5, closed))

    def test_there_is_nothing_to_be_disproportionate_against_early_in_a_run(self) -> None:
        """The answer to "what does it do before there is a distribution" is nothing."""
        for population in ([], [2], [2, 2]):
            with self.subTest(population=population):
                self.assertFalse(disproportionate(99, population))
        self.assertTrue(disproportionate(99, [2, 2, 2]))

    def test_a_run_of_free_stages_does_not_make_every_stage_disproportionate(self) -> None:
        """A median of zero would make ``spent > 0`` the whole rule."""
        self.assertFalse(disproportionate(5, [0, 0, 0]))

    def test_the_ration_is_the_runs_own_median_and_never_zero(self) -> None:
        self.assertEqual(ration(5, [2, 2, 4]), 7)
        self.assertEqual(ration(5, [0, 0, 0]), 6)

    def test_the_early_ruling_says_which_precondition_was_short(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            ruling = rule_on(supervisor, paths, "03_study_design", meter=a_meter("03_study_design"))
            self.assertEqual(ruling.kind, CONTINUE)
            self.assertEqual(ruling.rule, NOTHING_TO_DECIDE)
            self.assertIn(str(MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION), ruling.because)
            self.assertEqual(ruling.evidence["closed_stages"], 0)

    def test_it_moves_the_surplus_to_the_stages_that_have_not_run(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=2)
            meter = a_meter("03_study_design", failures=[f"e{i}" for i in range(5)])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=6)
            self.assertEqual(ruling.kind, REALLOCATE)
            self.assertEqual(ruling.rule, DISPROPORTIONATE_SPEND)
            self.assertEqual(ruling.evidence["median"], 2)
            self.assertEqual(ruling.evidence["ration"], 7)
            self.assertEqual(ruling.effect["units_moved"], 1)
            self.assertTrue(ruling.effect["total_conserved"])
            self.assertNotIn("03_study_design", ruling.effect["to"])
            for entered in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                self.assertNotIn(entered, ruling.effect["to"])

    def test_it_rations_a_stage_once_and_not_at_every_boundary_after(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=2)
            meter = a_meter("03_study_design", failures=[f"e{i}" for i in range(5)])
            first = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=6)
            second = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=7)
            self.assertEqual(first.kind, REALLOCATE)
            self.assertEqual(second.kind, CONTINUE)

    def test_a_stage_with_nothing_unspent_left_is_a_continue_too(self) -> None:
        """Budget that is already spent cannot be moved, however disproportionate it is."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=2)
            # 7 charged of an allowance of 8, so the ration (7 + the median 2) is above
            # what the stage holds and the surplus is nothing.
            meter = a_meter("03_study_design", failures=[f"e{i}" for i in range(7)])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=8)
            self.assertEqual(ruling.kind, CONTINUE)

    def test_a_reallocate_that_would_move_nothing_is_a_continue(self) -> None:
        """An audit trail may not overstate what was done.

        With every other stage already entered there is nobody to give the surplus to, so
        recording a `reallocate` would put an intervention in the ledger against a run
        where no budget changed hands.
        """
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in SLUGS:
                if slug != "03_study_design":
                    close_a_visit(paths, slug, charged=2)
            meter = a_meter("03_study_design", failures=[f"e{i}" for i in range(5)])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=6)
            self.assertEqual(ruling.kind, CONTINUE)

    def test_a_run_with_no_pool_reallocates_nothing(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=2)
            meter = a_meter("03_study_design", failures=[f"e{i}" for i in range(9)])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=10, ceiling=None)
            self.assertEqual(ruling.kind, CONTINUE)


# ---------------------------------------------------------------------------
# redirect
# ---------------------------------------------------------------------------


class UnfundedRevisitTests(unittest.TestCase):
    def test_it_counts_only_the_visits_that_ended_without_an_approval(self) -> None:
        rows = [
            {"stage": "06_analysis", "outcome": OUTCOME_APPROVED},
            {"stage": "06_analysis", "outcome": OUTCOME_AUTO_SKIPPED},
            {"stage": "07_writing", "outcome": OUTCOME_AUTO_SKIPPED},
        ]
        self.assertEqual(unsettled_visits(rows, "06_analysis"), 1)
        self.assertEqual(unsettled_visits(rows, "07_writing"), 1)

    def test_it_names_an_edge_only_from_the_ones_it_was_handed(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for _ in range(UNSETTLED_VISITS_BEFORE_A_REDIRECT):
                close_a_visit(paths, "06_analysis", charged=3, outcome=OUTCOME_AUTO_SKIPPED)
            ruling = supervisor.review_stage_exit(
                paths=paths, stage_slug="06_analysis", admissible_forward=["07_writing"]
            )
            self.assertEqual(ruling.kind, REDIRECT)
            self.assertEqual(ruling.rule, UNFUNDED_REVISIT)
            self.assertEqual(ruling.target, "07_writing")
            self.assertIn(ruling.target, ruling.evidence["chosen_from"])

    def test_with_no_open_forward_edge_it_names_nothing(self) -> None:
        """It picks from the admissible set; it cannot construct a move."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for _ in range(UNSETTLED_VISITS_BEFORE_A_REDIRECT):
                close_a_visit(paths, "06_analysis", charged=3, outcome=OUTCOME_AUTO_SKIPPED)
            ruling = supervisor.review_stage_exit(
                paths=paths, stage_slug="06_analysis", admissible_forward=[]
            )
            self.assertEqual(ruling.kind, CONTINUE)
            self.assertEqual(ruling.target, "")

    def test_one_unsettled_visit_is_not_enough(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            close_a_visit(paths, "06_analysis", charged=3, outcome=OUTCOME_AUTO_SKIPPED)
            ruling = supervisor.review_stage_exit(
                paths=paths, stage_slug="06_analysis", admissible_forward=["07_writing"]
            )
            self.assertEqual(ruling.kind, CONTINUE)

    def test_a_stage_that_kept_being_approved_is_never_redirected_away_from(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for _ in range(4):
                close_a_visit(paths, "06_analysis", charged=3, outcome=OUTCOME_APPROVED)
            ruling = supervisor.review_stage_exit(
                paths=paths, stage_slug="06_analysis", admissible_forward=["07_writing"]
            )
            self.assertEqual(ruling.kind, CONTINUE)


# ---------------------------------------------------------------------------
# escalate
# ---------------------------------------------------------------------------


class NoRecoveryLeftTests(unittest.TestCase):
    def test_it_fires_on_exactly_the_state_that_aborts_a_run(self) -> None:
        """Skip budget spent, at the node that writes the deliverable, nothing left to buy."""
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter(WRITING, failures=["requires at least one closed research round"] * 2)
            ruling = rule_on(supervisor, paths, WRITING, meter=meter, skips_spent=3, attempt=3)
            self.assertEqual(ruling.kind, ESCALATE)
            self.assertEqual(ruling.rule, NO_RECOVERY_LEFT)
            self.assertTrue(ruling.needs_a_human)
            self.assertTrue(ruling.ends_the_visit)

    def test_it_does_not_take_the_deliverable_stage_s_first_attempt_away(self) -> None:
        """The defect this precondition's third clause exists for, pinned.

        A run whose skip budget is spent got to the writing stage by ``_route_to_deliverable``
        -- spending the last of the budget is *how* it got there -- so without the "nothing
        left to buy" clause the last resort fires at the writing stage's first attempt
        boundary, on every such run, and ends the visit before the stage has run once. That
        turns the trade the route exists to make ("spend what is left writing up rather than
        exiting with nothing") into exiting with nothing.
        """
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            ruling = rule_on(supervisor, paths, WRITING, meter=a_meter(WRITING), skips_spent=6)
            self.assertEqual(ruling.kind, CONTINUE)
            self.assertFalse(ruling.ends_the_visit)

    def test_it_fires_when_the_ceiling_leaves_nothing_to_buy(self) -> None:
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter(WRITING, failures=[f"e{i}" for i in range(CEILING)])
            ruling = rule_on(
                supervisor, paths, WRITING, meter=meter, skips_spent=3, attempt=CEILING + 1
            )
            self.assertEqual(ruling.kind, ESCALATE)
            self.assertEqual(ruling.evidence["attempts_at_stake"], 0)

    def test_a_skip_still_in_hand_is_not_a_last_resort(self) -> None:
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter(WRITING, failures=["same"] * 2)
            ruling = rule_on(supervisor, paths, WRITING, meter=meter, skips_spent=2, attempt=3)
            self.assertEqual(ruling.kind, STOP_SPENDING)

    def test_an_earlier_stage_still_has_somewhere_to_be_routed(self) -> None:
        """Below the deliverable node a failure can still be skipped past, so this is not
        the last resort even with the budget spent."""
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter("03_study_design", failures=["same"] * 2)
            ruling = rule_on(
                supervisor, paths, "03_study_design", meter=meter, skips_spent=3, attempt=3
            )
            self.assertEqual(ruling.kind, STOP_SPENDING)

    def test_it_outranks_a_stage_that_is_also_stuck(self) -> None:
        """Nothing can be salvaged once there is no recovery path, so it is asked first."""
        supervisor = a_supervisor(skips=1)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter(WRITING, failures=["requires at least one closed research round"] * 3)
            ruling = rule_on(supervisor, paths, WRITING, meter=meter, skips_spent=1, attempt=4)
            self.assertEqual(ruling.kind, ESCALATE)


# ---------------------------------------------------------------------------
# The record
# ---------------------------------------------------------------------------


class EveryRulingIsRecordedTests(unittest.TestCase):
    def read(self, paths: RunPaths) -> list[dict]:
        text = supervisor_ledger_path(paths).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def test_a_continue_is_written_too(self) -> None:
        """A supervisor that speaks only when it acts cannot be audited."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            rule_on(supervisor, paths, "01_literature_survey", meter=a_meter("01_literature_survey"))
            rows = self.read(paths)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["intervention"], CONTINUE)
            self.assertTrue(rows[0]["because"])

    def test_the_row_carries_what_the_rule_read(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter("03_study_design", failures=["same"] * 2)
            rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=3)
            row = self.read(paths)[-1]
            self.assertEqual(row["intervention"], STOP_SPENDING)
            self.assertEqual(row["rule"], UNCHANGING_FAILURE)
            self.assertEqual(row["attempt"], 3)
            self.assertEqual(row["evidence"]["longest_unchanged_run"], 2)
            self.assertEqual(row["permitted_effect"], INTERVENTION_EFFECTS[STOP_SPENDING])

    def test_a_stage_exit_ruling_says_which_boundary_it_came_from(self) -> None:
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            supervisor.review_stage_exit(paths=paths, stage_slug=WRITING, admissible_forward=[])
            self.assertEqual(self.read(paths)[-1]["boundary"], "stage_exit")

    def test_an_unwritable_ledger_does_not_fail_the_run(self) -> None:
        """A run that produced good work is not lost because the account could not be written."""
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            supervisor_ledger_path(paths).mkdir(parents=True)  # a directory where the file goes
            ruling = rule_on(supervisor, paths, WRITING, meter=a_meter(WRITING))
            self.assertEqual(ruling.kind, CONTINUE)

    def test_a_rule_that_raises_becomes_a_continue_and_not_an_exception(self) -> None:
        """Bookkeeping may not fail a run, and neither may the supervisor's own arithmetic."""

        class Exploding:
            def attempt_digests(self):
                raise RuntimeError("boom")

        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            ruling = supervisor.review_attempt(
                paths=paths,
                stage_slug=WRITING,
                stage_number=WRITING_NUMBER,
                meter=Exploding(),  # type: ignore[arg-type]
                attempt_no=1,
                auto_skips_spent=0,
                deliverable_number=WRITING_NUMBER,
                per_stage_ceiling=CEILING,
            )
            self.assertEqual(ruling.kind, CONTINUE)
            self.assertIn("boom", ruling.because)


# ---------------------------------------------------------------------------
# The thresholds, and the instrument that produced them
# ---------------------------------------------------------------------------


class TheThresholdsAreMeasuredTests(unittest.TestCase):
    """Each value is pinned to the docstring's account of what it was measured against.

    Not to the measurement's result -- the four trial runs are not in this repository and
    a test that read them would be a test that only passes on one machine. What is pinned
    is that the number in the code and the number in the sentence explaining it are the
    same number, which is the half that rots.
    """

    def test_the_docstring_states_the_population_the_thresholds_were_measured_over(self) -> None:
        from src import supervisor

        doc = supervisor.__doc__ or ""
        self.assertIn("22 stage visits", doc)
        self.assertIn("141 attempt-loop iterations", doc)
        self.assertIn("tools/supervisor_threshold_replay.py", doc)

    def test_the_stop_threshold_in_the_prose_is_the_shipped_one(self) -> None:
        from src import supervisor

        doc = supervisor.__doc__ or ""
        self.assertIn(f"**= {STOP_AFTER_IDENTICAL_FAILURES}.**", doc)

    def test_the_proportionality_thresholds_in_the_prose_are_the_shipped_ones(self) -> None:
        from src import supervisor

        doc = supervisor.__doc__ or ""
        self.assertIn(f"**= {DISPROPORTIONATE_MULTIPLE}**", doc)
        self.assertIn(f"**= {MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION}.**", doc)
        self.assertIn(f"{DISPROPORTIONATE_MULTIPLE}x", doc)

    def test_the_replay_runs_the_shipped_rule_rather_than_a_copy(self) -> None:
        """An instrument that reimplements the rule measures a program that does not exist."""
        tree = ast.parse(REPLAY_SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.supervisor":
                imported |= {alias.name for alias in node.names}
        for name in ("unchanging_failure", "disproportionate", "ration", "longest_unchanged_run"):
            with self.subTest(name=name):
                self.assertIn(name, imported)
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(defined & imported, set(), "the replay redefines a rule it imports")

    def test_the_replay_also_takes_its_digest_from_the_ledger_module(self) -> None:
        tree = ast.parse(REPLAY_SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.stage_cost":
                imported |= {alias.name for alias in node.names}
        self.assertIn("failure_digest", imported)


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


class TheManagerIsWiredToTheSupervisorTests(unittest.TestCase):
    """A supervisor nothing asks is a module, not a role.

    Read out of ``src/manager.py`` rather than exercised through a full stage, because
    what these assert is *where* the calls are -- inside the attempt loop and at the stage
    boundary -- and a behavioural test passes just as well when the only call is at the
    end.
    """

    def _function(self, name: str) -> ast.FunctionDef:
        tree = ast.parse(MANAGER_SOURCE)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        raise AssertionError(f"{name} is not in src/manager.py")

    def _calls_in(self, node: ast.AST) -> set[str]:
        found: set[str] = set()
        for item in ast.walk(node):
            if isinstance(item, ast.Call) and isinstance(item.func, ast.Attribute):
                found.add(item.func.attr)
        return found

    def test_the_attempt_loop_asks_before_it_buys_an_attempt(self) -> None:
        """Inside the stage, not only between stages.

        The whole point of the component: the grinding happens within one visit, so a
        supervisor woken only at stage boundaries watches the money leave.
        """
        loop = self._function("_run_stage_attempts")
        whiles = [node for node in ast.walk(loop) if isinstance(node, ast.While)]
        self.assertTrue(whiles, "_run_stage_attempts has no attempt loop")
        self.assertTrue(
            any("review_attempt" in self._calls_in(node) for node in whiles),
            "the attempt loop does not consult the supervisor",
        )

    def test_the_stage_boundary_asks_too(self) -> None:
        self.assertIn("review_stage_exit", self._calls_in(self._function("_advance_from")))

    def test_the_ceiling_the_loop_enforces_is_the_supervisors(self) -> None:
        """Computed *and* used. Calling it and then comparing against `--max-attempts`
        anyway is the shape a source check for the call alone cannot see."""
        loop = self._function("_run_stage_attempts")
        self.assertIn("attempt_ceiling", self._calls_in(loop))
        exhausted = [
            node
            for node in ast.walk(loop)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "attempts_exhausted"
        ]
        self.assertTrue(exhausted, "the attempt loop no longer bounds itself at all")
        ceilings = {
            arg.id
            for call in exhausted
            for arg in call.args
            if isinstance(arg, ast.Name)
        }
        self.assertIn(
            "ceiling",
            ceilings,
            "the loop bounds itself on something other than the supervisor's ceiling",
        )

    def test_the_only_thing_a_ruling_can_do_inside_a_stage_is_end_the_visit(self) -> None:
        """The invariant, read off the branch that acts on a ruling.

        ``ends_the_visit`` is the sole gate on the supervisor changing control flow in the
        attempt loop, and the branch it guards is the one that already existed for an
        exhausted stage -- whose outcomes are a skip stub and an abort, neither of which
        is an approval.
        """
        loop = self._function("_run_stage_attempts")
        guarded = [
            node
            for node in ast.walk(loop)
            if isinstance(node, ast.If)
            and "ends_the_visit" in (ast.get_source_segment(MANAGER_SOURCE, node.test) or "")
        ]
        self.assertTrue(guarded, "no branch in the attempt loop is guarded by the ruling")
        # The outermost such branch is the one that decides whether the visit ends; the
        # inner mention is the message saying which of the three reasons it was.
        outermost = min(guarded, key=lambda node: node.lineno)
        body = "\n".join(
            ast.get_source_segment(MANAGER_SOURCE, statement) or "" for statement in outermost.body
        )
        self.assertIn("_handle_stage_exhaustion", body)
        for approving in ("mark_stage_approved", "promote", "approve"):
            with self.subTest(call=approving):
                self.assertNotIn(approving, body)

    def test_the_supervisor_is_built_once_per_run(self) -> None:
        self.assertIn("RunSupervisor(", MANAGER_SOURCE)

    def test_a_redirect_goes_through_the_router_and_not_around_it(self) -> None:
        """Going around the router is how the archive learns a move the run did not make."""
        advance = self._function("_advance_from")
        chooses = [
            node
            for node in ast.walk(advance)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "choose"
        ]
        self.assertEqual(len(chooses), 1, "_advance_from no longer routes through the router")
        required = [kw for kw in chooses[0].keywords if kw.arg == "required"]
        self.assertEqual(len(required), 1, "the router is called with no required target")
        # And the value has to come from the ruling, not from a literal `None` left behind
        # when the wiring was removed.
        names = {
            node.id
            for node in ast.walk(required[0].value)
            if isinstance(node, ast.Name)
        }
        self.assertIn(
            "exit_ruling",
            names,
            "the required target is not the supervisor's ruling",
        )


class TheRouterRefusesARedirectTheGuardsShutTests(unittest.TestCase):
    """``redirect`` may only name an edge the guards already leave open.

    Driven through the real :meth:`~src.router.StageRouter.choose` rather than read out of
    its source, because what has to hold is the behaviour: a required target is checked
    against the *live* moves, and one the guards have shut degrades to the forward edge
    with a refusal recorded rather than being taken.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        self.stage = next(item for item in STAGES if item.number == 6)
        write_text(self.paths.stage_file(self.stage), "# Stage 06: Analysis\n\nBody.\n")
        self.graph = StageGraph.adaptive()
        self.state = GraphState()
        self.router = StageRouter(None, mode="off")

    def _moves(self) -> list:
        return self.graph.moves(self.paths, self.stage.slug, self.state)

    def test_a_required_target_the_guards_left_open_is_taken(self) -> None:
        live = [move for move in self._moves() if move.admissible]
        self.assertTrue(live, "the fixture leaves no move open, so this proves nothing")
        target = live[0].edge.target
        decision = self.router.choose(
            paths=self.paths,
            stage=self.stage,
            graph=self.graph,
            state=self.state,
            required=(target, "the supervisor stopped funding another visit"),
        )
        self.assertEqual(decision.target, target)
        self.assertEqual(decision.refusal, "")

    def test_a_required_target_the_guards_shut_is_refused_and_not_opened(self) -> None:
        """The refusal, not the target, is what has to hold.

        The default out of this node is itself a guard-blocked advance that
        ``default_move`` takes as a last resort, so a refusal can land on the same slug
        the redirect asked for. What distinguishes "the guards let it through" from "the
        guards refused and the run fell back" is the recorded refusal and the edge kind,
        so the case picked here is a blocked *revisit* -- a different kind from the
        default -- and both are asserted.
        """
        default = self.graph.default_move(self.paths, self.stage.slug, self.state)
        blocked = [
            move
            for move in self._moves()
            if not move.admissible and move.edge.target != default.target
        ]
        self.assertTrue(blocked, "the fixture blocks nothing else, so this proves nothing")
        target = blocked[0].edge.target
        decision = self.router.choose(
            paths=self.paths,
            stage=self.stage,
            graph=self.graph,
            state=self.state,
            required=(target, "the supervisor stopped funding another visit"),
        )
        self.assertNotEqual(decision.target, target)
        self.assertEqual(decision.target, default.target)
        self.assertIn("the supervisor required", decision.refusal)

    def test_a_supervisor_redirect_is_not_recorded_as_the_agents_choice(self) -> None:
        """The archive learns from ``agent_directed``; a redirect is not an agent's move,
        and recording one as the agent's is how the archive learns a move nobody made."""
        live = [move for move in self._moves() if move.admissible]
        decision = self.router.choose(
            paths=self.paths,
            stage=self.stage,
            graph=self.graph,
            state=self.state,
            required=(live[0].edge.target, "because"),
        )
        self.assertFalse(decision.agent_directed)

    def test_a_closed_round_outranks_the_supervisor(self) -> None:
        """A round has reasoned about the results; this has reasoned about the spend."""
        live = [move.edge.target for move in self._moves() if move.admissible]
        self.assertGreaterEqual(len(live), 2, "the fixture cannot distinguish the two")
        decision = self.router.choose(
            paths=self.paths,
            stage=self.stage,
            graph=self.graph,
            state=self.state,
            declared=(live[0], "the round asked"),
            required=(live[1], "the supervisor required"),
        )
        self.assertEqual(decision.target, live[0])


if __name__ == "__main__":
    unittest.main()
