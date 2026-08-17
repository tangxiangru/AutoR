"""The supervisor decides things, so what it can decide has to be bounded by a test.

Three questions this file answers, in the order a reviewer asks them.

**Can it ever make a gate pass?** No, and not because the docstring says so. The three
things that hold it are checkable and each has a test that dies when the rule is reverted:
:meth:`~src.supervisor.AttemptAllowance.visit_ceiling` is a ``min`` against the run's own
``--max-attempts``, so ``NoInterventionRaisesABudgetTests`` sweeps every allowance state
reachable by transfer and finds none that hands back a larger number -- and, since the
first version of this class starved every revisit instead, none that hands back zero;
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

**Does every visit get funded?** ``EveryVisitIsFundedTests`` drives
``ResearchManager._run_stage`` twice into one stage, because the defect it exists for was
arithmetic that read correctly and starved every revisit: a stage whose first visit
charged ``--max-attempts`` was handed a ceiling of 0 on its second and died before buying
an attempt. The backward edge is the one thing this project has that a plain agent loop
does not, so a supervisor that prices it out is worse than no supervisor, and no
assertion on the pool's arithmetic could have caught it -- the arithmetic was self
consistent and about the wrong quantity.

**Are the thresholds measured?** The values are pinned to the module docstring's account
of what they were measured against; every ``:data:`NAME` **= V**`` phrase has to name the
shipped constant, no stale population figure may survive anywhere in the module, and the
replay's own ``population_matches`` self-check is exercised on all three of its answers.
``tools/supervisor_threshold_replay.py`` is pinned to importing the shipped predicates
rather than reimplementing them, and to actually computing the two columns the docstring
credits it with -- the outcome of a cut iteration, and the redirect count -- because
naming an instrument as the source of a claim it has no column for is the same defect as
a number nobody ran.

**And is any of that held?** :data:`SUPERVISOR_MUTATIONS` is the answer as an instrument
rather than as a sentence. Fifteen one-anchor edits, the first of which puts the revisit
regression back exactly as it was::

    git worktree add --detach /tmp/sweep HEAD
    cd /tmp/sweep && python3 -m tests.test_run_supervisor --mutations
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.stage_cost import (
    OUTCOME_APPROVED,
    OUTCOME_AUTO_SKIPPED,
    REVIEWER_REFUSED,
    StageCostMeter,
    append_stage_cost_row,
    failure_digest,
    read_stage_cost_ledger,
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
from src.approval_agent import ReviewDecision
from src.manifest import load_run_manifest
from src.router import StageRouter
from src.stage_graph import GraphState, StageGraph
from src.utils import (
    STAGES,
    STUCK_AFTER_IDENTICAL_FAILURES,
    RunPaths,
    build_run_paths,
    ensure_run_layout,
    is_stuck,
    write_text,
)
from tests.test_stage_cost_ledger import ManagerLoopFixture, _StubReviewer

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
        for donor, recipient, units in (("a", ["b"], 7), ("b", ["c"], 5), ("c", ["a", "b"], 4)):
            allowance.transfer(donor, recipient, units)
            for slug in ("a", "b", "c"):
                with self.subTest(slug=slug):
                    self.assertLessEqual(allowance.visit_ceiling(slug), 8)

    def test_no_state_of_the_pool_can_starve_a_visit_of_every_attempt(self) -> None:
        """The other direction of the same invariant, and the one that regressed.

        A per-visit ceiling of zero is a stage that fails on entry with "Exceeded 0
        attempts" before it has run once. Swept over the same reachable states, because
        the first version of this class produced exactly that on any second visit and the
        pool is the only thing that can produce it now.
        """
        allowance = AttemptAllowance(["a", "b", "c"], 8)
        for donor, recipient, units in (("a", ["b"], 7), ("b", ["c"], 5), ("c", ["a", "b"], 4)):
            allowance.transfer(donor, recipient, units)
            for slug in ("a", "b", "c"):
                with self.subTest(slug=slug):
                    self.assertGreaterEqual(allowance.visit_ceiling(slug), 1)

    def test_a_donor_may_not_give_away_everything_it_holds(self) -> None:
        """A stage the run can never enter again is the mirror of a guarded edge opened.

        The structural floor under the policy floor: :meth:`AttemptAllowance.transfer` is
        the only method that can lower an allowance, so refusing the emptying transfer
        there is what makes a zero per-visit ceiling unreachable by any caller.
        """
        allowance = AttemptAllowance(["a", "b"], 8)
        with self.assertRaises(AllowanceError):
            allowance.transfer("a", ["b"], 8)
        self.assertEqual(allowance.allowance["a"], 8)
        self.assertTrue(allowance.conserved())

    def test_a_recipient_that_holds_more_than_the_ceiling_still_gets_the_ceiling(self) -> None:
        """The case the ``min`` exists for: allowance above ``--max-attempts``."""
        allowance = AttemptAllowance(["a", "b"], 8)
        allowance.transfer("a", ["b"], 7)
        self.assertEqual(allowance.allowance["b"], 15)
        self.assertEqual(allowance.visit_ceiling("b"), 8)

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
        self.assertIsNone(supervisor.attempt_ceiling(WRITING, None))
        self.assertIsNone(supervisor.allowance)

    def test_a_first_visit_gets_exactly_what_the_run_allows(self) -> None:
        supervisor = a_supervisor()
        self.assertEqual(supervisor.attempt_ceiling("03_study_design", CEILING), 8)

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
                    self.assertLessEqual(supervisor.attempt_ceiling(slug, CEILING), 8)


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
        self.assertEqual(STOP_AFTER_IDENTICAL_FAILURES, 3)

    def test_the_rule_is_not_a_second_copy_of_the_stuck_check(self) -> None:
        """Same count, wider population, and the docstring says so -- so pin the width.

        The two numbers agreeing is not a coincidence to hide: ``is_stuck`` reads
        ``recent_failures``, which ``_run_stage_attempts`` appends to at exactly one place
        -- the branch where validation, repair and local normalisation all failed -- so it
        cannot see a reviewer refusing identically three times, a cross-model veto
        repeating, or a backend failing the same way. This rule reads the whole census. On
        ``MEASURED_RUNS`` every repeat is a validator error, so the difference is invisible
        there and has to be pinned here instead.
        """
        refusals = [["the reviewer says no"]] * STUCK_AFTER_IDENTICAL_FAILURES
        self.assertTrue(is_stuck(refusals), "the fixture is not a run of identical failures")
        # The same three attempts, charged to the reviewer rather than the validators, are
        # invisible to `is_stuck` because nothing appends them to `recent_failures`.
        supervisor = a_supervisor()
        stage = next(item for item in STAGES if item.slug == "03_study_design")
        meter = StageCostMeter(stage)
        for number in range(1, STOP_AFTER_IDENTICAL_FAILURES + 1):
            meter.note_attempt()
            meter.note_failure(number, REVIEWER_REFUSED, "the reviewer says no")
        self.assertFalse(is_stuck([]), "the loop's own list stays empty for a reviewer refusal")
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            ruling = rule_on(
                supervisor,
                paths,
                "03_study_design",
                meter=meter,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
        self.assertEqual(ruling.kind, STOP_SPENDING)
        self.assertEqual(ruling.rule, UNCHANGING_FAILURE)

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
            meter = a_meter(
                "03_study_design",
                failures=["report_plan.json task output 1 states nothing"]
                * STOP_AFTER_IDENTICAL_FAILURES,
            )
            ruling = rule_on(
                supervisor,
                paths,
                "03_study_design",
                meter=meter,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
            self.assertEqual(ruling.kind, STOP_SPENDING)
            self.assertEqual(ruling.rule, UNCHANGING_FAILURE)
            self.assertTrue(ruling.ends_the_visit)
            self.assertEqual(
                ruling.evidence["longest_unchanged_run"], STOP_AFTER_IDENTICAL_FAILURES
            )

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
        number = 0
        for index in range(STOP_AFTER_IDENTICAL_FAILURES):
            number += 1
            meter.note_attempt()
            meter.note_failure(number, "validators_refused", "same")
            number += 1
            meter.note_attempt()
            meter.note_polish_round(number)
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

    def test_a_revisit_can_still_be_rationed_and_keeps_a_visits_worth(self) -> None:
        """The half of the pool's per-visit turn that a first-visit test cannot see.

        On a first visit the stage's lifetime spend and the open visit's spend are the
        same number, so every assertion above passes whichever of the two the ration is
        computed from. Here they differ: 6 charged in a closed visit, 1 in the open one.
        Against a per-visit allowance of 8 the lifetime figure leaves ``8 - (6 + 2) = 0``
        surplus and the rule stands down on exactly the revisits it exists to notice; the
        visit figure leaves ``8 - (1 + 2) = 5`` and the stage keeps the run's own ration
        for the visit it is in.
        """
        supervisor = a_supervisor()
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            for slug in ("01_literature_survey", "02_hypothesis_generation", "04_implementation"):
                close_a_visit(paths, slug, charged=2)
            close_a_visit(paths, "03_study_design", charged=6, outcome=OUTCOME_AUTO_SKIPPED)
            meter = a_meter("03_study_design", failures=["one"])
            ruling = rule_on(supervisor, paths, "03_study_design", meter=meter, attempt=2)
            self.assertEqual(ruling.kind, REALLOCATE)
            self.assertEqual(ruling.evidence["stage_charged_attempts"], 7)
            self.assertEqual(ruling.evidence["visit_charged_attempts"], 1)
            self.assertEqual(ruling.evidence["ration"], 3)
            self.assertEqual(ruling.effect["units_moved"], 5)
            self.assertEqual(ruling.effect["visit_ceiling_after"], 3)
            # And the narrowing it leaves is still a fundable visit, not a starved one.
            self.assertGreaterEqual(supervisor.attempt_ceiling("03_study_design", CEILING), 1)

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
            meter = a_meter(
                WRITING,
                failures=["requires at least one closed research round"]
                * STOP_AFTER_IDENTICAL_FAILURES,
            )
            ruling = rule_on(
                supervisor,
                paths,
                WRITING,
                meter=meter,
                skips_spent=3,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
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
            meter = a_meter(WRITING, failures=["same"] * STOP_AFTER_IDENTICAL_FAILURES)
            ruling = rule_on(
                supervisor,
                paths,
                WRITING,
                meter=meter,
                skips_spent=2,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
            self.assertEqual(ruling.kind, STOP_SPENDING)

    def test_an_earlier_stage_still_has_somewhere_to_be_routed(self) -> None:
        """Below the deliverable node a failure can still be skipped past, so this is not
        the last resort even with the budget spent."""
        supervisor = a_supervisor(skips=3)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter("03_study_design", failures=["same"] * STOP_AFTER_IDENTICAL_FAILURES)
            ruling = rule_on(
                supervisor,
                paths,
                "03_study_design",
                meter=meter,
                skips_spent=3,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
            self.assertEqual(ruling.kind, STOP_SPENDING)

    def test_it_outranks_a_stage_that_is_also_stuck(self) -> None:
        """Nothing can be salvaged once there is no recovery path, so it is asked first."""
        supervisor = a_supervisor(skips=1)
        with tempfile.TemporaryDirectory() as tmp:
            paths = fresh_paths(tmp)
            meter = a_meter(
                WRITING,
                failures=["requires at least one closed research round"]
                * (STOP_AFTER_IDENTICAL_FAILURES + 1),
            )
            ruling = rule_on(
                supervisor,
                paths,
                WRITING,
                meter=meter,
                skips_spent=1,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 2,
            )
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
            meter = a_meter("03_study_design", failures=["same"] * STOP_AFTER_IDENTICAL_FAILURES)
            rule_on(
                supervisor,
                paths,
                "03_study_design",
                meter=meter,
                attempt=STOP_AFTER_IDENTICAL_FAILURES + 1,
            )
            row = self.read(paths)[-1]
            self.assertEqual(row["intervention"], STOP_SPENDING)
            self.assertEqual(row["rule"], UNCHANGING_FAILURE)
            self.assertEqual(row["attempt"], STOP_AFTER_IDENTICAL_FAILURES + 1)
            self.assertEqual(
                row["evidence"]["longest_unchanged_run"], STOP_AFTER_IDENTICAL_FAILURES
            )
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

    Not to the measurement's result -- the trial runs are not in this repository and a
    test that read them would be a test that only passes on one machine. What is pinned
    here is the half that rots: that the number in the code and the number in the sentence
    explaining it are the same number, that the population figure in the prose is the one
    the instrument records, and that the instrument refuses to print a different one under
    the invocation the prose names.
    """

    def test_the_docstring_states_the_population_the_thresholds_were_measured_over(self) -> None:
        """And states the one the instrument records, not one nobody ran.

        The number this replaces was ``162``, which neither invocation of the replay ever
        printed -- the three-run command gives 141 and the four-run glob gave 166 and then
        167 as the fourth run kept being written. The docstring is now pinned against
        ``MEASURED_VISITS`` and ``MEASURED_ITERATIONS``, which the tool checks itself
        against every time it runs.
        """
        from src import supervisor
        from tools.supervisor_threshold_replay import MEASURED_ITERATIONS, MEASURED_VISITS

        doc = supervisor.__doc__ or ""
        self.assertIn(f"{MEASURED_VISITS} stage visits", doc)
        self.assertIn(f"{MEASURED_ITERATIONS} attempt-loop iterations", doc)
        self.assertIn("tools/supervisor_threshold_replay.py", doc)
        self.assertIn("MEASURED_RUNS", doc)

    def test_the_docstring_names_no_population_figure_that_is_not_the_recorded_one(self) -> None:
        """The control the previous test cannot be: a stale figure left beside a fresh one.

        ``assertIn`` passes whether or not the sentence it matched is the only one, and
        the branch this fixes shipped ``22 stage visits`` in the module docstring and
        ``26 stage visits`` in two constant docstrings at the same time. This reads every
        ``<number> stage visit`` and ``<number> ... iteration`` in the whole module -- prose
        and comments -- and refuses any that is not the recorded population.
        """
        from tools.supervisor_threshold_replay import MEASURED_ITERATIONS, MEASURED_VISITS

        # The 26/166/167 sentence in the module docstring is the one place a different
        # population is named on purpose, so it is named in words that this can exclude.
        prose = "\n".join(
            line
            for line in SUPERVISOR_SOURCE.splitlines()
            if "still being written" not in line and "and 27 and 167" not in line
        )
        visits = {int(value) for value in re.findall(r"(\d+) stage visits?\b", prose)}
        iterations = {
            int(value) for value in re.findall(r"(\d+) attempt-loop iterations?\b", prose)
        }
        self.assertLessEqual(visits, {MEASURED_VISITS}, f"a stale visit count survives: {visits}")
        self.assertLessEqual(
            iterations,
            {MEASURED_ITERATIONS},
            f"a stale iteration count survives: {iterations}",
        )

    def test_the_instrument_refuses_a_population_that_is_not_the_recorded_one(self) -> None:
        """The self-check, exercised rather than described.

        This is what makes the docstring's denominator re-derivable on a machine that has
        the trial data: run the named invocation and the report either says ``as
        recorded`` or says which way it drifted. Both wrong answers are checked here,
        because a self-check that only ever returns the happy string is the same green as
        no self-check.
        """
        from tools.supervisor_threshold_replay import (
            MEASURED_ITERATIONS,
            MEASURED_RUNS,
            MEASURED_VISITS,
            population_matches,
        )

        self.assertIn(
            "as recorded",
            population_matches(list(MEASURED_RUNS), MEASURED_VISITS, MEASURED_ITERATIONS),
        )
        self.assertIn(
            "DRIFTED",
            population_matches(list(MEASURED_RUNS), MEASURED_VISITS + 1, MEASURED_ITERATIONS),
        )
        self.assertIn(
            "DRIFTED",
            population_matches(list(MEASURED_RUNS), MEASURED_VISITS, MEASURED_ITERATIONS + 25),
        )
        self.assertIn(
            "not the recorded one",
            population_matches(
                [*MEASURED_RUNS, "Chemistry_000_20260816_173127"],
                MEASURED_VISITS + 5,
                MEASURED_ITERATIONS + 26,
            ),
        )

    def test_every_threshold_in_the_prose_is_the_shipped_one(self) -> None:
        """One sweep over the table rather than one assertion per constant.

        ``assertIn("**= 3.**")`` was satisfied by *any* threshold documented as three, so
        the sentence checked and the constant checked did not have to be about the same
        rule. The whole ``:data:`NAME` **= V**`` phrase cannot be.
        """
        from src import supervisor

        doc = supervisor.__doc__ or ""
        for name, value in (
            ("STOP_AFTER_IDENTICAL_FAILURES", STOP_AFTER_IDENTICAL_FAILURES),
            ("DISPROPORTIONATE_MULTIPLE", DISPROPORTIONATE_MULTIPLE),
            ("MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION", MIN_CLOSED_STAGES_FOR_A_DISTRIBUTION),
            ("UNSETTLED_VISITS_BEFORE_A_REDIRECT", UNSETTLED_VISITS_BEFORE_A_REDIRECT),
        ):
            with self.subTest(name=name):
                self.assertRegex(doc, rf":data:`{name}` \*\*= {value}[.*]")
        self.assertIn(f"{DISPROPORTIONATE_MULTIPLE}x", doc)

    def test_the_replay_runs_the_shipped_rule_rather_than_a_copy(self) -> None:
        """An instrument that reimplements the rule measures a program that does not exist."""
        tree = ast.parse(REPLAY_SOURCE)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "src.supervisor":
                imported |= {alias.name for alias in node.names}
        for name in (
            "unchanging_failure",
            "disproportionate",
            "ration",
            "longest_unchanged_run",
            # The redirect column's predicate. Two sentences in `src/supervisor.py` used
            # to credit this tool with a finding about `UNSETTLED_VISITS_BEFORE_A_REDIRECT`
            # while it had no redirect column and did not import this at all.
            "unsettled_visits",
        ):
            with self.subTest(name=name):
                self.assertIn(name, imported)
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        self.assertEqual(defined & imported, set(), "the replay redefines a rule it imports")

    def test_the_replay_computes_the_redirect_claim_the_docstring_credits_it_with(self) -> None:
        """Naming the instrument as the source of a claim it cannot compute is the defect.

        Driven rather than read: a hand-built walk in which one stage ends two visits
        without an approval, so the column has to reach the threshold, and a second in
        which the first visit was approved, so it must not.
        """
        from tools.supervisor_threshold_replay import redirect_fires

        def walk(*outcomes: str) -> list[dict]:
            return [
                {"stage": "06_analysis", "outcome": outcome, "attempts": [], "stage_number": 6}
                for outcome in outcomes
            ]

        twice_unsettled = redirect_fires([("run", walk("skipped", "skipped"))])
        self.assertEqual(len(twice_unsettled), 1)
        self.assertEqual(twice_unsettled[0]["unsettled"], UNSETTLED_VISITS_BEFORE_A_REDIRECT)
        self.assertEqual(
            redirect_fires([("run", walk("approved", "skipped"))]),
            [],
            "a stage with an approved visit was redirected away from",
        )

    def test_the_replay_reports_what_a_cut_iteration_produced(self) -> None:
        """The column whose absence made ``N = 2`` look measured.

        ``bought`` is the classifier and this is its contract: the entries the manager
        writes when an attempt produced something, and an empty tuple when it did not. The
        veto case is here because it is the one that flatters the rule -- an approval the
        cross-model reviewer overrode is not an approval, and counting it as one would
        have inflated the "productive" column by six attempts.
        """
        from tools.supervisor_threshold_replay import (
            PRODUCED_APPROVAL,
            PRODUCED_DRAFT,
            PRODUCED_OBLIGATIONS,
            PRODUCED_REPAIR,
            bought,
            draft_was_valid,
        )

        self.assertEqual(bought({"result": "", "prompt": ""}), ())
        self.assertEqual(bought({"reviewer_choice": "choice: 5"}), (PRODUCED_APPROVAL,))
        self.assertEqual(
            bought({"reviewer_choice": "choice: 5", "cross_review": "agrees: False"}),
            (),
            "an approval the cross-model reviewer vetoed was counted as productive",
        )
        self.assertEqual(bought({"evolution_promoted": ""}), (PRODUCED_DRAFT,))
        self.assertEqual(bought({"validation_failed": "bad"}), (PRODUCED_REPAIR,))
        self.assertEqual(
            bought({"validation_failed": "bad", "local_normalization_failed": "still bad"}),
            (),
            "a validation failure that was never repaired was counted as a repair",
        )
        self.assertEqual(bought({"obligation_recorded": ""}), ())
        self.assertEqual(bought({"obligation_discharged": ""}), (PRODUCED_OBLIGATIONS,))
        # And the column the harm turns on: after a repeated validator refusal there is
        # nothing for `_validated_draft_for_skip` to rescue.
        self.assertFalse(draft_was_valid({"local_normalization_failed": "still bad"}))
        self.assertTrue(draft_was_valid({"reviewer_choice": "choice: 4"}))

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


class EveryVisitIsFundedTests(ManagerLoopFixture, unittest.TestCase):
    """The backward edge has to be affordable, and only the real loop can say it is.

    This is the regression that made the reviewer refuse the branch. The pool used to
    charge a stage's *closed* visits against a single lifetime allowance, so a stage whose
    first visit spent ``--max-attempts`` was handed ``remaining = 0`` on its second,
    ``attempt_ceiling`` returned 0, and ``attempts_exhausted(1, 0)`` ended the visit before
    it bought anything -- with the manifest reading ``Exceeded 0 attempts`` and the
    supervisor's own ledger recording ``continue / nothing_to_decide``, which
    :func:`~src.supervisor.ration`'s docstring forbids in as many words.

    Driven through ``ResearchManager._run_stage`` twice rather than asserted on the
    arithmetic, because the arithmetic is what was wrong: reading
    ``min(per_stage, allowance - spent)`` and concluding it funds a revisit is exactly the
    mistake, and only the loop knows that ``loop_attempts`` restarts at zero on every
    entry and so already accounts for what the visit itself has spent.
    """

    STAGE = STAGES[0]

    def _visit(self, decision: ReviewDecision) -> bool:
        self._stub_operator(self._valid_draft(self.STAGE))
        self.manager.reviewer = _StubReviewer([decision])
        return self.manager._run_stage(self.paths, self.STAGE)

    def _exhausting_visit(self) -> bool:
        """One visit that spends the whole ceiling on validation failures.

        Reviewer refusals cannot be used for this: ``MAX_AUTOMATED_SENDBACKS`` is counted
        per *stage* and read from disk, so the second visit's first refusal is converted
        into an approval and the visit ends after one attempt for a reason that has
        nothing to do with funding. A draft the validators refuse is refused every time.
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
        return read_stage_cost_ledger(self.paths)

    def _ledger(self) -> list[dict]:
        text = supervisor_ledger_path(self.paths).read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def _last_error(self) -> str:
        manifest = load_run_manifest(self.paths.run_manifest)
        entry = next(item for item in manifest.stages if item.slug == self.STAGE.slug)
        return entry.last_error or ""

    def test_a_second_visit_to_an_exhausted_stage_still_buys_attempts(self) -> None:
        """The whole item, end to end: exhaust the ceiling, come back, get approved."""
        self.manager.max_stage_attempts = 3
        self.assertFalse(
            self._visit(
                ReviewDecision(
                    choice="4", decision_token="revise", reason="no", feedback="again"
                )
            )
        )
        self.assertTrue(self._visit(ReviewDecision(choice="5", decision_token="approve")))
        rows = self._rows()
        self.assertEqual([row["visit"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["attempts"], 3, "the first visit charged the whole ceiling")
        self.assertGreaterEqual(rows[1]["attempts"], 1, "the revisit bought no attempt at all")
        self.assertFalse(rows[1]["exhausted"])
        self.assertEqual(rows[1]["outcome"], OUTCOME_APPROVED)
        self.assertNotIn("Exceeded 0 attempts", self._last_error())

    def test_a_revisit_gets_the_whole_ceiling_and_not_one_attempt(self) -> None:
        """"Floor it at one" is not the fix: one attempt is a revisit that cannot work.

        Both visits fail the same way to exhaustion, so what each *charges* is the ceiling
        it was funded at. Anything less on the second than on the first would mean the
        supervisor still narrowed the revisit, and a floor of one would show up here as
        ``[2, 1]``.
        """
        self.manager.max_stage_attempts = 2
        self.assertFalse(self._exhausting_visit())
        self.assertFalse(self._exhausting_visit())
        self.assertEqual([row["attempts"] for row in self._rows()], [2, 2])
        self.assertEqual(self.manager.supervisor.attempt_ceiling(self.STAGE.slug, 2), 2)

    def test_no_visit_dies_at_a_boundary_the_ledger_calls_nothing_to_decide(self) -> None:
        """A ration of zero is ``stop_spending``, and the ledger has to be able to say so.

        The failure this pins is not "the ruling was wrong" -- ``continue`` was the right
        ruling for every one of those boundaries -- it is that the visit died anyway, so
        the audit trail could not name the rule that ended it. Checked as an invariant over
        the whole two-visit run rather than at one boundary: no visit may end without
        buying an attempt, and no ``continue`` may be the last word on one that did.
        """
        self.manager.max_stage_attempts = 2
        self._exhausting_visit()
        self._exhausting_visit()
        starved = [row for row in self._rows() if row["attempts"] == 0]
        self.assertEqual(starved, [], "a visit was funded at zero attempts")
        acting = [row for row in self._ledger() if row["intervention"] != CONTINUE]
        self.assertEqual(
            acting,
            [],
            "the supervisor acted on a run where nothing should have moved it",
        )
        self.assertNotIn("Exceeded 0 attempts", self._last_error())

    def test_the_manager_asks_for_a_per_visit_ceiling_and_gets_the_runs_own(self) -> None:
        """The ceiling the loop enforces, read from the supervisor the manager built.

        Two closed visits' worth of spend is on disk when this asks, which is the state
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
        self.assertEqual(self.manager.supervisor.attempt_ceiling(self.STAGE.slug, 2), 2)


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


# ---------------------------------------------------------------------------
# The mutation sweep, as an instrument
# ---------------------------------------------------------------------------

SUPERVISOR = "src/supervisor.py"
MANAGER_FILE = "src/manager.py"
REPLAY = "tools/supervisor_threshold_replay.py"

#: ``(what it breaks, file, the text to replace, what to replace it with)``.
#:
#: The same shape ``tests/test_stage_cost_ledger.MUTATIONS`` uses, and for the same
#: reason: "N mutations, all killed" is a number a reader has to believe unless the sweep
#: is a thing they can run::
#:
#:     git worktree add --detach /tmp/sweep HEAD
#:     cd /tmp/sweep && python3 -m tests.test_run_supervisor --mutations
#:
#: What it covers is what this pass changed -- the per-visit funding rule, the floor under
#: a transfer, the ration's spend, the shipped repeat count, and the three replay columns
#: whose absence let a docstring claim things the instrument could not compute. The first
#: entry is the regression itself, put back exactly: an ``attempt_ceiling`` that subtracts
#: what the stage's closed visits charged.
SUPERVISOR_MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("the revisit regression, restored: the ceiling charges closed visits again", MANAGER_FILE,
     "            ceiling = self.supervisor.attempt_ceiling(stage.slug, self.max_stage_attempts)",
     "            ceiling = max(\n"
     "                self.supervisor.attempt_ceiling(stage.slug, self.max_stage_attempts)\n"
     "                - self.supervisor.closed_spend(paths).get(stage.slug, 0),\n"
     "                0,\n"
     "            )"),
    ("visit_ceiling loses the min against --max-attempts", SUPERVISOR,
     "        return min(self.per_stage, self.allowance.get(stage_slug, self.per_stage))",
     "        return self.allowance.get(stage_slug, self.per_stage)"),
    ("a donor may empty itself again", SUPERVISOR,
     "        if held is None or units >= held:", "        if held is None or units > held:"),
    ("the ration is computed from the stage's lifetime rather than the visit", SUPERVISOR,
     "        keep = ration(live_charged, others) if others else 0",
     "        keep = ration(stage_spend, others) if others else 0"),
    ("the transfer stops conserving", SUPERVISOR,
     "        if not self.conserved():", "        if False:"),
    ("the repeat count goes back to the value the replay refused", SUPERVISOR,
     "STOP_AFTER_IDENTICAL_FAILURES = 3", "STOP_AFTER_IDENTICAL_FAILURES = 2"),
    ("the repeat rule stops requiring the repeats to be consecutive", SUPERVISOR,
     "        run = run + 1 if digest == previous else 1", "        run = run + 1"),
    ("the redirect threshold drops to one unsettled visit", SUPERVISOR,
     "UNSETTLED_VISITS_BEFORE_A_REDIRECT = 2", "UNSETTLED_VISITS_BEFORE_A_REDIRECT = 1"),
    ("an approval the cross-model reviewer vetoed counts as productive", REPLAY,
     "    if not vetoed and (\"approved\" in entry or (gate is not None and _field(gate, \"choice\") == \"5\")):",
     "    if \"approved\" in entry or (gate is not None and _field(gate, \"choice\") == \"5\"):"),
    ("an obligation merely recorded counts as discharged", REPLAY,
     '    if "obligation_discharged" in entry:',
     '    if "obligation_discharged" in entry or "obligation_recorded" in entry:'),
    ("a validation failure nothing repaired counts as a repair", REPLAY,
     '    if "validation_failed" in entry and "local_normalization_failed" not in entry:',
     '    if "validation_failed" in entry:'),
    ("the draft is always reported as inside the gate", REPLAY,
     '    return "local_normalization_failed" not in entry', "    return True"),
    ("the redirect column never fires", REPLAY,
     "            if unsettled >= unsettled_before:", "            if False:"),
    ("the population self-check always says the population is the recorded one", REPLAY,
     "    if tuple(names) != MEASURED_RUNS:", "    if False:"),
    ("the recorded population goes back to the figure no invocation printed", REPLAY,
     "MEASURED_ITERATIONS = 141", "MEASURED_ITERATIONS = 162"),
)

#: Tests that die under every mutation because applying one is what stops their own
#: anchor from matching. Subtracting them is what keeps a kill an actual kill; see
#: ``tests/test_stage_cost_ledger.SWEEP_SELF_TESTS``, which this mirrors.
SUPERVISOR_SWEEP_SELF_TESTS = frozenset({"test_every_anchor_matches_its_file_exactly_once"})


def _dead_tests(root: Path) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", __spec__.name if __spec__ else __name__, "-v"],
        cwd=root, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    dead = set(re.findall(r"^(\w+) \(tests\.[\w.]+\) \.\.\. (?:FAIL|ERROR)", out, re.M))
    dead |= set(re.findall(r"^(?:FAIL|ERROR): (\w+) ", out, re.M))
    return dead - SUPERVISOR_SWEEP_SELF_TESTS


def run_mutations(root: Path | None = None) -> int:
    """Apply each of :data:`SUPERVISOR_MUTATIONS` in turn; return the survivor count.

    Restores every file in a ``finally``, so an interrupted sweep leaves the tree as it
    found it -- but it does edit the tree, so run it in a scratch checkout.
    """
    root = root or Path(__file__).resolve().parent.parent
    baseline = _dead_tests(root)
    if baseline:
        print(f"REFUSED: the tree is not green before mutating: {sorted(baseline)}")
        return len(baseline)
    print(f"baseline green; {len(SUPERVISOR_MUTATIONS)} mutations to try\n")
    survivors: list[str] = []
    for name, relative, old, new in SUPERVISOR_MUTATIONS:
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
    print(f"\ntried {len(SUPERVISOR_MUTATIONS)}, "
          f"killed {len(SUPERVISOR_MUTATIONS) - len(survivors)}, survivors {len(survivors)}")
    for name in survivors:
        print("   SURVIVOR:", name)
    return len(survivors)


class TheSweepIsRunnableTests(unittest.TestCase):
    """The instrument, checked without running it: fifteen subprocess suites is not a unit test.

    What goes stale without anyone noticing is an *anchor*, and an anchor that no longer
    matches is a mutation silently not applied -- which reads in the output exactly like
    one that was killed.
    """

    def test_every_anchor_matches_its_file_exactly_once(self) -> None:
        for name, relative, old, _new in SUPERVISOR_MUTATIONS:
            with self.subTest(mutation=name):
                text = (REPO / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    text.count(old), 1,
                    f"{name}: anchor matches {text.count(old)} times in {relative}",
                )

    def test_no_mutation_leaves_the_file_unchanged(self) -> None:
        for name, _relative, old, new in SUPERVISOR_MUTATIONS:
            with self.subTest(mutation=name):
                self.assertNotEqual(old, new, f"{name} is not a mutation")

    def test_the_self_test_exclusion_names_a_test_that_exists(self) -> None:
        """An exclusion pointing at nothing would silently stop excluding."""
        for name in SUPERVISOR_SWEEP_SELF_TESTS:
            self.assertTrue(hasattr(TheSweepIsRunnableTests, name), name)

    def test_the_sweep_covers_all_three_files_this_pass_touched(self) -> None:
        self.assertEqual(
            {relative for _n, relative, _o, _w in SUPERVISOR_MUTATIONS},
            {SUPERVISOR, MANAGER_FILE, REPLAY},
        )


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        raise SystemExit(1 if run_mutations() else 0)
    unittest.main()
