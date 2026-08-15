"""What the ledger has to get right for a rollback to mean anything.

Every assertion here is a property :func:`src.manifest.rollback_to_stage` depends on. The
two that matter most are the ones a single-state ledger would get wrong: a file created
inside the withdrawn range goes away, and a file created before it and amended inside it
goes *back*, rather than going away with it.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.provenance import (
    LEDGER_PATHS,
    RESTORABLE_BYTE_LIMIT,
    count_live_files,
    format_withdrawal_plan,
    invalidate_from,
    is_live,
    load_ledger,
    observe,
    path_is_live,
    plan_withdrawal,
    stage_number_for_slug,
)
from src.utils import INTAKE_STAGE, STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_01, STAGE_02, STAGE_03, STAGE_04, STAGE_05 = STAGES[0], STAGES[1], STAGES[2], STAGES[3], STAGES[4]


class ProvenanceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)

    def rel(self, path: Path) -> str:
        return path.relative_to(self.paths.workspace_root).as_posix()


class AttributionTests(ProvenanceTestCase):
    def test_a_new_file_is_attributed_to_the_stage_whose_boundary_saw_it(self) -> None:
        write_text(self.paths.data_dir / "counts.csv", "id,n\n1,2\n")
        ledger = observe(self.paths, STAGE_03)

        entry = ledger.entries[self.rel(self.paths.data_dir / "counts.csv")]
        self.assertEqual(entry.produced_by_stage, STAGE_03.slug)
        self.assertEqual(entry.last_written_by_stage, STAGE_03.slug)
        self.assertTrue(entry.live)
        self.assertEqual(len(entry.versions), 1)

    def test_a_rewrite_appends_a_version_and_leaves_the_creator_alone(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "id,n\n1,2\n")
        observe(self.paths, STAGE_03)
        write_text(target, "id,n\n1,2\n3,4\n")
        ledger = observe(self.paths, STAGE_05)

        entry = ledger.entries[self.rel(target)]
        self.assertEqual(entry.produced_by_stage, STAGE_03.slug)
        self.assertEqual(entry.last_written_by_stage, STAGE_05.slug)
        self.assertEqual([version.stage for version in entry.versions], [STAGE_03.slug, STAGE_05.slug])

    def test_an_unchanged_file_gets_no_second_version(self) -> None:
        write_text(self.paths.data_dir / "counts.csv", "id,n\n1,2\n")
        observe(self.paths, STAGE_03)
        ledger = observe(self.paths, STAGE_04)

        entry = ledger.entries[self.rel(self.paths.data_dir / "counts.csv")]
        self.assertEqual(len(entry.versions), 1)
        self.assertEqual(entry.last_written_by_stage, STAGE_03.slug)

    def test_a_uid_is_never_reissued_even_for_identical_bytes(self) -> None:
        """A re-run after a rollback writes the same bytes. It must still be a new version.

        This is why the target view records a provider rather than a value: two stages can
        produce byte-identical output, and a consumer comparing values could not tell the
        re-run from the original.
        """

        target = self.paths.data_dir / "counts.csv"
        write_text(target, "same\n")
        first = observe(self.paths, STAGE_03).entries[self.rel(target)].version_uid

        write_text(target, "different\n")
        observe(self.paths, STAGE_04)
        write_text(target, "same\n")
        third = observe(self.paths, STAGE_05).entries[self.rel(target)].version_uid

        self.assertNotEqual(first, third)
        self.assertEqual(load_ledger(self.paths).next_uid, 4)

    def test_bootstrap_material_belongs_to_intake_and_no_rollback_reaches_it(self) -> None:
        write_text(self.paths.notes_dir / "brief.md", "the question\n")
        observe(self.paths, INTAKE_STAGE)

        self.assertEqual(plan_withdrawal(self.paths, STAGE_01), [])

    def test_a_run_level_ledger_is_never_attributed(self) -> None:
        """A rollback that rewound ``research_rounds.json`` would launder an abandonment."""

        write_text(self.paths.research_rounds, '{"rounds": []}\n')
        ledger = observe(self.paths, STAGE_05)

        self.assertNotIn("notes/research_rounds.json", ledger.entries)
        self.assertIn("notes/research_rounds.json", LEDGER_PATHS)
        self.assertEqual(plan_withdrawal(self.paths, STAGE_01), [])

    def test_a_file_over_the_restorable_limit_is_recorded_as_delete_only(self) -> None:
        target = self.paths.data_dir / "checkpoint.npy"
        target.write_bytes(b"x" * (RESTORABLE_BYTE_LIMIT + 1))
        ledger = observe(self.paths, STAGE_04)

        entry = ledger.entries[self.rel(target)]
        self.assertFalse(entry.restorable)
        self.assertEqual(entry.blob_hash, "")

    def test_intake_and_every_stage_resolve_to_a_number(self) -> None:
        self.assertEqual(stage_number_for_slug(INTAKE_STAGE.slug), 0)
        self.assertEqual(stage_number_for_slug(STAGE_05.slug), 5)
        self.assertIsNone(stage_number_for_slug("not_a_stage"))


class WithdrawalPlanTests(ProvenanceTestCase):
    def test_a_file_created_inside_the_range_is_planned_for_deletion(self) -> None:
        write_text(self.paths.data_dir / "late.csv", "id\n1\n")
        observe(self.paths, STAGE_05)

        plan = plan_withdrawal(self.paths, STAGE_03)
        self.assertEqual([item.rel_path for item in plan], ["data/late.csv"])
        self.assertTrue(plan[0].deletes)

    def test_a_file_created_before_the_range_is_planned_for_a_rewind(self) -> None:
        """The case a single-state ledger gets wrong, and the reason the graph exists.

        Stage 02 wrote an honest hypothesis set and Stage 05 amended it. Rolling back to
        Stage 04 withdraws Stage 05, and Stage 02's work is not Stage 05's to take with it.
        """

        target = self.paths.data_dir / "counts.csv"
        write_text(target, "early\n")
        observe(self.paths, STAGE_02)
        write_text(target, "late\n")
        observe(self.paths, STAGE_05)

        plan = plan_withdrawal(self.paths, STAGE_04)
        self.assertEqual(len(plan), 1)
        self.assertFalse(plan[0].deletes)
        assert plan[0].restore_to is not None
        self.assertEqual(plan[0].restore_to.stage, STAGE_02.slug)

    def test_a_file_untouched_by_the_range_is_not_in_the_plan(self) -> None:
        write_text(self.paths.data_dir / "early.csv", "early\n")
        observe(self.paths, STAGE_02)

        self.assertEqual(plan_withdrawal(self.paths, STAGE_04), [])

    def test_the_plan_renders_both_kinds_separately(self) -> None:
        write_text(self.paths.data_dir / "kept.csv", "early\n")
        observe(self.paths, STAGE_02)
        write_text(self.paths.data_dir / "kept.csv", "late\n")
        write_text(self.paths.data_dir / "new.csv", "new\n")
        observe(self.paths, STAGE_05)

        rendered = format_withdrawal_plan(plan_withdrawal(self.paths, STAGE_04))
        self.assertIn("1 deleted", rendered)
        self.assertIn("1 rewound", rendered)
        self.assertIn("delete data/new.csv", rendered)


class LivenessTests(ProvenanceTestCase):
    def test_an_unattributed_file_counts(self) -> None:
        """Fail-open. A run with no ledger must behave as it did before one existed."""

        write_text(self.paths.data_dir / "counts.csv", "id\n1\n")
        self.assertTrue(is_live(load_ledger(self.paths), "data/counts.csv"))
        self.assertEqual(count_live_files(self.paths, self.paths.data_dir, {".csv"}), 1)

    def test_a_withdrawn_file_stops_counting_while_staying_on_disk(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "id\n1\n")
        observe(self.paths, STAGE_05)
        invalidate_from(self.paths, STAGE_03, "design was wrong")

        self.assertTrue(target.exists())
        self.assertEqual(count_live_files(self.paths, self.paths.data_dir, {".csv"}), 0)
        self.assertFalse(path_is_live(self.paths, target))

    def test_a_withdrawn_row_is_kept_rather_than_dropped(self) -> None:
        """Dropping it would make the file unattributed, and unattributed files count."""

        write_text(self.paths.data_dir / "counts.csv", "id\n1\n")
        observe(self.paths, STAGE_05)
        invalidate_from(self.paths, STAGE_03)

        entry = load_ledger(self.paths).entries["data/counts.csv"]
        self.assertFalse(entry.live)
        self.assertEqual(entry.invalidated_by_stage, STAGE_03.slug)

    def test_a_rewrite_after_a_withdrawal_revives_the_row(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "abandoned\n")
        observe(self.paths, STAGE_05)
        invalidate_from(self.paths, STAGE_03)

        write_text(target, "redone\n")
        ledger = observe(self.paths, STAGE_03)
        self.assertTrue(ledger.entries["data/counts.csv"].live)
        self.assertEqual(count_live_files(self.paths, self.paths.data_dir, {".csv"}), 1)

    def test_a_withdrawal_that_is_not_rewritten_stays_withdrawn(self) -> None:
        """The point of the whole mechanism, stated as one assertion.

        A rollback that could not delete the file leaves it on disk and withdrawn. A later
        visit that does not touch it must not have it counted back in.
        """

        write_text(self.paths.data_dir / "counts.csv", "abandoned\n")
        observe(self.paths, STAGE_05)
        invalidate_from(self.paths, STAGE_03)
        observe(self.paths, STAGE_03)

        self.assertEqual(count_live_files(self.paths, self.paths.data_dir, {".csv"}), 0)


if __name__ == "__main__":
    unittest.main()
