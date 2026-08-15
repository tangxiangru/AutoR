"""The recovery half: inverses, the accumulator, and what a rollback does to the disk.

The end-to-end assertion is :class:`RecoverToStageTests`. Everything above it is a
property that one depends on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.effects import (
    COMMUTATIVE_KEYS,
    EffectRecord,
    Inverse,
    ORDERED_KEYS,
    accumulator_path,
    apply_withdrawal,
    independence_obstruction,
    is_commutative,
    key_for_workspace_path,
    load_accumulator,
    record_effect,
    recover_to_stage,
    reverted_path,
    revert_from,
    set_artifact,
)
from src.emissions import pending as pending_emissions, withhold
from src.provenance import load_ledger, observe, plan_withdrawal
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_02, STAGE_03, STAGE_04, STAGE_05, STAGE_06 = (
    STAGES[1],
    STAGES[2],
    STAGES[3],
    STAGES[4],
    STAGES[5],
)


class EffectsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)


class KeyClassificationTests(unittest.TestCase):
    def test_the_two_sets_are_disjoint(self) -> None:
        self.assertEqual(COMMUTATIVE_KEYS & ORDERED_KEYS, frozenset())

    def test_an_unclassified_key_is_treated_as_ordered(self) -> None:
        """Safe default. Reading it as commutative would license the reordering the
        classification exists to authorise, on a location nobody has checked."""

        self.assertFalse(is_commutative("something.nobody.classified"))

    def test_a_table_shaped_key_is_commutative_and_a_narrative_is_not(self) -> None:
        self.assertTrue(is_commutative("literature.sources"))
        self.assertTrue(is_commutative("results"))
        self.assertFalse(is_commutative("report.draft"))


class KeyForPathTests(EffectsTestCase):
    def test_a_workspace_path_maps_to_the_table_it_belongs_to(self) -> None:
        self.assertEqual(key_for_workspace_path(self.paths, "data/counts.csv"), "data")
        self.assertEqual(key_for_workspace_path(self.paths, "writing/paper.tex"), "report.draft")
        self.assertEqual(key_for_workspace_path(self.paths, "results/a/b.json"), "results")


class SetArtifactTests(EffectsTestCase):
    def test_creating_a_file_accumulates_an_inverse_that_deletes_it(self) -> None:
        record = set_artifact(self.paths, STAGE_04, "data/counts.csv", "id\n1\n")
        target = self.paths.workspace_root / "data/counts.csv"

        self.assertTrue(target.exists())
        self.assertEqual(record.inverse.kind, "delete_path")
        revert_from(self.paths, STAGE_04, STAGES)
        self.assertFalse(target.exists())

    def test_overwriting_a_file_accumulates_an_inverse_that_restores_the_bytes(self) -> None:
        set_artifact(self.paths, STAGE_03, "data/counts.csv", "first\n")
        record = set_artifact(self.paths, STAGE_04, "data/counts.csv", "second\n")
        target = self.paths.workspace_root / "data/counts.csv"

        self.assertEqual(record.inverse.kind, "restore_blob")
        self.assertEqual(target.read_text(encoding="utf-8"), "second\n")
        revert_from(self.paths, STAGE_04, STAGES)
        self.assertEqual(target.read_text(encoding="utf-8"), "first\n")

    def test_the_accumulator_survives_being_read_back_from_disk(self) -> None:
        """Inverses are data, not closures. A run resumes in a new process."""

        set_artifact(self.paths, STAGE_04, "data/counts.csv", "id\n1\n")
        reloaded = load_accumulator(self.paths, STAGE_04)

        self.assertEqual(len(reloaded), 1)
        self.assertEqual(reloaded[0].inverse.payload["rel_path"], "data/counts.csv")


class AccumulatorOrderTests(EffectsTestCase):
    def test_inverses_are_applied_last_in_first_out(self) -> None:
        target = self.paths.workspace_root / "data/counts.csv"
        set_artifact(self.paths, STAGE_04, "data/counts.csv", "one\n")
        set_artifact(self.paths, STAGE_04, "data/counts.csv", "two\n")
        set_artifact(self.paths, STAGE_04, "data/counts.csv", "three\n")

        revert_from(self.paths, STAGE_04, STAGES)
        self.assertFalse(target.exists())

    def test_later_stages_are_withdrawn_before_earlier_ones(self) -> None:
        target = self.paths.workspace_root / "data/counts.csv"
        set_artifact(self.paths, STAGE_03, "data/counts.csv", "design\n")
        set_artifact(self.paths, STAGE_05, "data/counts.csv", "experiment\n")

        report = revert_from(self.paths, STAGE_03, STAGES)
        self.assertEqual(report.stages, [STAGE_05.slug, STAGE_03.slug])
        self.assertFalse(target.exists())

    def test_a_spent_accumulator_is_archived_rather_than_deleted(self) -> None:
        set_artifact(self.paths, STAGE_04, "data/counts.csv", "id\n1\n")
        revert_from(self.paths, STAGE_04, STAGES)

        self.assertFalse(accumulator_path(self.paths, STAGE_04).exists())
        archive = reverted_path(self.paths, STAGE_04)
        self.assertTrue(archive.exists())
        self.assertIn("reverted_at", json.loads(archive.read_text(encoding="utf-8").splitlines()[0]))

    def test_an_unrecognised_inverse_is_skipped_rather_than_raised_on(self) -> None:
        """One unreadable row must not stop the rest of a rollback: the rows after it are
        the ones nearest the current state."""

        set_artifact(self.paths, STAGE_04, "data/counts.csv", "id\n1\n")
        record_effect(
            self.paths,
            EffectRecord(
                stage=STAGE_04.slug,
                key="data",
                action="mystery",
                rel_path="data/counts.csv",
                inverse=Inverse("from_a_future_autor", {}),
                at="",
            ),
        )

        report = revert_from(self.paths, STAGE_04, STAGES)
        self.assertEqual(len(report.skipped), 1)
        self.assertFalse((self.paths.workspace_root / "data/counts.csv").exists())


class IndependenceTests(EffectsTestCase):
    def _record(self, stage, key: str) -> EffectRecord:
        return EffectRecord(
            stage=stage.slug, key=key, action="create", rel_path="x", inverse=Inverse("noop"), at=""
        )

    def test_effects_at_distinct_keys_never_obstruct_each_other(self) -> None:
        obstruction = independence_obstruction(
            [self._record(STAGE_04, "data")], [self._record(STAGE_06, "figures")]
        )
        self.assertIsNone(obstruction)

    def test_effects_sharing_a_commutative_key_do_not_obstruct_each_other(self) -> None:
        obstruction = independence_obstruction(
            [self._record(STAGE_04, "results")], [self._record(STAGE_06, "results")]
        )
        self.assertIsNone(obstruction)

    def test_effects_sharing_an_ordered_key_obstruct_a_selective_withdrawal(self) -> None:
        obstruction = independence_obstruction(
            [self._record(STAGE_04, "report.draft")], [self._record(STAGE_06, "report.draft")]
        )
        self.assertIsNotNone(obstruction)
        assert obstruction is not None
        self.assertIn("report.draft", obstruction)
        self.assertIn("ordered", obstruction)

    def test_an_unclassified_shared_key_says_so_rather_than_reading_as_ordered(self) -> None:
        obstruction = independence_obstruction(
            [self._record(STAGE_04, "brand.new")], [self._record(STAGE_06, "brand.new")]
        )
        assert obstruction is not None
        self.assertIn("neither COMMUTATIVE_KEYS nor ORDERED_KEYS", obstruction)


class ApplyWithdrawalTests(EffectsTestCase):
    def test_an_observed_file_created_inside_the_range_is_deleted(self) -> None:
        write_text(self.paths.data_dir / "late.csv", "id\n1\n")
        observe(self.paths, STAGE_05)

        apply_withdrawal(self.paths, plan_withdrawal(self.paths, STAGE_03))
        self.assertFalse((self.paths.data_dir / "late.csv").exists())
        self.assertNotIn("data/late.csv", load_ledger(self.paths).entries)

    def test_an_observed_file_amended_inside_the_range_is_rewound(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "early\n")
        observe(self.paths, STAGE_02)
        write_text(target, "late\n")
        observe(self.paths, STAGE_05)

        apply_withdrawal(self.paths, plan_withdrawal(self.paths, STAGE_04))
        self.assertEqual(target.read_text(encoding="utf-8"), "early\n")


class RecoverToStageTests(EffectsTestCase):
    def test_a_rollback_takes_the_workspace_back_and_leaves_the_earlier_work(self) -> None:
        kept = self.paths.data_dir / "design.csv"
        amended = self.paths.data_dir / "shared.csv"
        abandoned = self.paths.results_dir / "measurement.json"

        write_text(kept, "the design\n")
        write_text(amended, "as designed\n")
        observe(self.paths, STAGE_03)

        write_text(amended, "as measured\n")
        write_text(abandoned, '{"value": 1}\n')
        observe(self.paths, STAGE_05)

        report = recover_to_stage(self.paths, STAGE_04, "the design was wrong")

        self.assertTrue(report.touched)
        self.assertTrue(kept.exists(), "Stage 03's own work is not Stage 05's to take with it")
        self.assertEqual(amended.read_text(encoding="utf-8"), "as designed\n")
        self.assertFalse(abandoned.exists())

    def test_a_rollback_discards_the_withheld_emissions_of_the_range(self) -> None:
        withhold(self.paths, STAGE_05, "pull_request", "publish the result")
        withhold(self.paths, STAGE_02, "network", "fetch a corpus")

        report = recover_to_stage(self.paths, STAGE_04)

        self.assertEqual(report.emissions_discarded, 1)
        self.assertEqual([item.stage for item in pending_emissions(self.paths)], [STAGE_02.slug])

    def test_a_rollback_over_an_untouched_workspace_reports_that_it_did_nothing(self) -> None:
        report = recover_to_stage(self.paths, STAGE_04)
        self.assertFalse(report.touched)
        self.assertIn("withdrew nothing", report.render())


if __name__ == "__main__":
    unittest.main()
