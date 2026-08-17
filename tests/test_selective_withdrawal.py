"""Withdrawing one stage while the stages after it stand.

Reverse-order withdrawal always works and always takes the later stages with it. That is
correct and it is also the pipeline's answer: a late finding invalidates everything that
followed it in wall-clock order. The graph's answer is that it invalidates *a* decision, and
that is only available when the later stages did not build on the one being withdrawn.

`--redo-stage` is where this lands, and it is also the last place a re-entry left the
previous attempt's work on disk.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.effects import load_accumulator, revert_only, set_artifact, withdraw_one_stage
from src.manifest import ensure_run_manifest
from src.provenance import load_ledger, observe, plan_single_stage_withdrawal
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_03, STAGE_04, STAGE_05, STAGE_06 = STAGES[2], STAGES[3], STAGES[4], STAGES[5]


class SelectiveTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)


class RevertOnlyTests(SelectiveTestCase):
    def test_a_stage_at_its_own_key_is_withdrawn_alone(self) -> None:
        set_artifact(self.paths, STAGE_04, "code/run.py", "print(1)\n")
        set_artifact(self.paths, STAGE_06, "figures/plot.json", "{}\n")

        report = revert_only(self.paths, STAGE_04, STAGES)

        self.assertEqual(report.stages, [STAGE_04.slug])
        self.assertFalse((self.paths.code_dir / "run.py").exists())
        self.assertTrue(
            (self.paths.figures_dir / "plot.json").exists(),
            "Stage 06 wrote a different key and is not Stage 04's to take with it",
        )

    def test_a_shared_ordered_key_refuses_and_names_it(self) -> None:
        set_artifact(self.paths, STAGE_04, "writing/paper.md", "# draft\n")
        set_artifact(self.paths, STAGE_06, "writing/paper.md", "# draft\n## results\n")

        report = revert_only(self.paths, STAGE_04, STAGES)

        self.assertEqual(report.stages, [])
        self.assertIn("report.draft", " ".join(report.skipped))
        self.assertTrue((self.paths.writing_dir / "paper.md").exists())

    def test_a_shared_commutative_key_is_no_obstruction(self) -> None:
        """Two writes into a collection can be withdrawn independently. That is what makes
        the classification worth having rather than a label."""

        set_artifact(self.paths, STAGE_04, "results/a.json", "{}\n")
        set_artifact(self.paths, STAGE_06, "results/b.json", "{}\n")

        report = revert_only(self.paths, STAGE_04, STAGES)

        self.assertEqual(report.stages, [STAGE_04.slug])
        self.assertFalse((self.paths.results_dir / "a.json").exists())
        self.assertTrue((self.paths.results_dir / "b.json").exists())


class SingleStagePlanTests(SelectiveTestCase):
    def test_a_file_only_this_stage_wrote_is_planned(self) -> None:
        write_text(self.paths.data_dir / "design.csv", "v1\n")
        observe(self.paths, STAGE_04)

        plan, contested = plan_single_stage_withdrawal(self.paths, STAGE_04)

        self.assertEqual([item.rel_path for item in plan], ["data/design.csv"])
        self.assertTrue(plan[0].deletes)
        self.assertEqual(contested, [])

    def test_a_file_an_earlier_stage_created_rewinds_rather_than_deleting(self) -> None:
        target = self.paths.data_dir / "design.csv"
        write_text(target, "the original\n")
        observe(self.paths, STAGE_03)
        write_text(target, "the redo\n")
        observe(self.paths, STAGE_04)

        plan, contested = plan_single_stage_withdrawal(self.paths, STAGE_04)

        self.assertEqual(contested, [])
        assert plan[0].restore_to is not None
        self.assertEqual(plan[0].restore_to.stage, STAGE_03.slug)

    def test_a_file_a_later_stage_rewrote_is_contested(self) -> None:
        """Rewinding it would discard the later stage's work; leaving it would keep this
        stage's. Neither is 'withdrew this stage', so the caller is told instead."""

        target = self.paths.data_dir / "shared.csv"
        write_text(target, "by 04\n")
        observe(self.paths, STAGE_04)
        write_text(target, "by 06\n")
        observe(self.paths, STAGE_06)

        plan, contested = plan_single_stage_withdrawal(self.paths, STAGE_04)

        self.assertEqual(plan, [])
        self.assertEqual(contested, ["data/shared.csv"])


class WithdrawOneStageTests(SelectiveTestCase):
    def test_a_redo_takes_back_the_attempt_it_is_replacing(self) -> None:
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        observe(self.paths, STAGE_04)

        report = withdraw_one_stage(self.paths, STAGE_04)

        self.assertTrue(report.selective)
        self.assertFalse((self.paths.code_dir / "run.py").exists())
        self.assertIn("alone", report.render())

    def test_later_independent_work_survives_the_redo(self) -> None:
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        observe(self.paths, STAGE_04)
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)

        report = withdraw_one_stage(self.paths, STAGE_04)

        self.assertTrue(report.selective)
        self.assertFalse((self.paths.code_dir / "run.py").exists())
        self.assertTrue((self.paths.results_dir / "metrics.json").exists())

    def test_a_contested_file_falls_back_to_the_reverse_order_withdrawal(self) -> None:
        target = self.paths.data_dir / "shared.csv"
        write_text(target, "by 04\n")
        observe(self.paths, STAGE_04)
        write_text(target, "by 05\n")
        observe(self.paths, STAGE_05)

        report = withdraw_one_stage(self.paths, STAGE_04)

        self.assertFalse(report.selective)
        self.assertIn("data/shared.csv", report.refusal)
        self.assertIn("not available", report.render())
        self.assertFalse(target.exists(), "the range withdrawal removed it")

    def test_a_redo_of_a_stage_that_wrote_nothing_reports_nothing(self) -> None:
        report = withdraw_one_stage(self.paths, STAGE_04)
        self.assertFalse(report.touched)

    def test_the_ledger_stops_claiming_versions_the_redo_removed(self) -> None:
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        observe(self.paths, STAGE_04)

        withdraw_one_stage(self.paths, STAGE_04)

        self.assertNotIn("code/run.py", load_ledger(self.paths).entries)

    def test_an_accumulated_write_is_withdrawn_alongside_the_observed_ones(self) -> None:
        set_artifact(self.paths, STAGE_04, "notes/plan.md", "the plan\n")
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        observe(self.paths, STAGE_04)

        report = withdraw_one_stage(self.paths, STAGE_04)

        self.assertTrue(report.selective)
        self.assertFalse((self.paths.notes_dir / "plan.md").exists())
        self.assertFalse((self.paths.code_dir / "run.py").exists())
        self.assertEqual(load_accumulator(self.paths, STAGE_04), [])


if __name__ == "__main__":
    unittest.main()
