"""A skipped stage's residue is flagged, not withdrawn, and the record stops contradicting it.

Two states were doing the work of three. ``live`` meant "the run stands behind this" and
its negation meant "a rollback repudiated this", and a skipped stage's artifacts are
neither: nobody accepted them and nobody threw them away. They were counted as accepted,
and the skip summary said the work "was never done" under a heading listing only its own
summary file.

The load-bearing assertion is
:meth:`ItIsNotAWithdrawalTests.test_the_forward_gate_still_counts_them`. Across the run
archive an auto-skip is how most runs get past a stage that stalls, so withdrawing the
residue would close the forward edge on the majority of them -- turning "this stage did not
finish" into "the run stops".
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.artifact_index import format_artifact_index_for_prompt, write_artifact_index
from src.manifest import (
    ensure_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_skipped_manifest,
    rollback_to_stage,
)
from src.provenance import observe, paths_written_by, unreviewed_paths, unreviewed_stage_slugs
from src.stage_graph import GUARDS, GraphState
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_03, STAGE_04, STAGE_05 = STAGES[2], STAGES[3], STAGES[4]


class UnreviewedTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)

    def skip(self, stage, kind: str = "auto") -> None:
        mark_stage_skipped_manifest(
            self.paths, stage, 1, [], reason="ran out of attempts", kind=kind
        )


class DerivedNotStoredTests(UnreviewedTestCase):
    def test_an_approved_stage_leaves_nothing_unreviewed(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        mark_stage_approved_manifest(self.paths, STAGE_05, 1, [])

        self.assertEqual(unreviewed_stage_slugs(self.paths), set())
        self.assertEqual(unreviewed_paths(self.paths), set())

    def test_a_skipped_stage_flags_what_it_last_wrote(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)

        self.assertEqual(unreviewed_stage_slugs(self.paths), {STAGE_05.slug})
        self.assertEqual(unreviewed_paths(self.paths), {"results/metrics.json"})

    def test_a_human_skip_counts_too(self) -> None:
        """The property is "nobody accepted it", and the manifest records both kinds the
        same way."""

        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05, kind="human")

        self.assertEqual(unreviewed_paths(self.paths), {"results/metrics.json"})

    def test_the_flag_keys_on_the_last_writer_not_the_creator(self) -> None:
        """A file Stage 03 created and a skipped Stage 05 rewrote holds Stage 05's content."""

        target = self.paths.data_dir / "counts.csv"
        write_text(target, "first\n")
        observe(self.paths, STAGE_03)
        mark_stage_approved_manifest(self.paths, STAGE_03, 1, [])
        write_text(target, "second\n")
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)

        self.assertEqual(unreviewed_paths(self.paths), {"data/counts.csv"})

    def test_it_clears_by_itself_when_the_stage_is_later_approved(self) -> None:
        """The reason the state is derived rather than stored: nothing has to remember to
        clear it."""

        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)
        self.assertTrue(unreviewed_paths(self.paths))

        mark_stage_approved_manifest(self.paths, STAGE_05, 2, [])

        self.assertEqual(unreviewed_paths(self.paths), set())

    def test_a_withdrawn_file_is_not_also_reported_as_unreviewed(self) -> None:
        """The two states are different claims and a file makes only the stronger one."""

        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)
        rollback_to_stage(self.paths, STAGE_04, "the implementation was wrong")

        self.assertEqual(unreviewed_paths(self.paths), set())


class ItIsNotAWithdrawalTests(UnreviewedTestCase):
    def test_the_forward_gate_still_counts_them(self) -> None:
        """The measurement this whole choice rests on.

        An auto-skip is a decision to continue past a failure. Closing the forward edge out
        of every skipped stage would defeat the mechanism that keeps those runs alive.
        """

        write_text(self.paths.code_dir / "run.py", "print('hi')\n")
        observe(self.paths, STAGE_04)
        self.skip(STAGE_04)

        self.assertTrue(GUARDS["runnable_code"](self.paths, GraphState()).ok)

    def test_the_index_counts_them_and_says_what_they_are(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)

        index = write_artifact_index(self.paths)

        self.assertEqual(index.artifact_count, 1)
        self.assertEqual(index.unreviewed_count, 1)
        self.assertTrue(index.artifacts[0].from_unreviewed_stage)

    def test_the_prompt_block_flags_them_without_hiding_them(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)

        block = format_artifact_index_for_prompt(write_artifact_index(self.paths))

        self.assertIn("results/metrics.json", block)
        self.assertIn("skipped rather than approved", block)

    def test_a_clean_run_carries_no_such_line(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        mark_stage_approved_manifest(self.paths, STAGE_05, 1, [])

        block = format_artifact_index_for_prompt(write_artifact_index(self.paths))

        self.assertNotIn("skipped rather than approved", block)

    def test_the_flag_survives_a_round_trip(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)
        self.skip(STAGE_05)
        first = write_artifact_index(self.paths)

        from src.artifact_index import load_artifact_index

        reloaded = load_artifact_index(self.paths.artifact_index)
        assert reloaded is not None
        self.assertEqual(reloaded.unreviewed_count, first.unreviewed_count)
        self.assertTrue(reloaded.artifacts[0].from_unreviewed_stage)


class TheRecordStopsContradictingTheDiskTests(UnreviewedTestCase):
    def test_a_stage_can_name_what_it_last_wrote(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        write_text(self.paths.data_dir / "counts.csv", "id\n1\n")
        observe(self.paths, STAGE_05)

        self.assertEqual(
            paths_written_by(self.paths, STAGE_05), ["data/counts.csv", "results/metrics.json"]
        )
        self.assertEqual(paths_written_by(self.paths, STAGE_03), [])

    def test_the_summary_lists_the_files_and_stops_denying_them(self) -> None:
        """Two sentences used to be false together: "its work was never done", under a
        heading reading "Files Produced" that listed only the summary itself."""

        from src.manager import ResearchManager

        write_text(self.paths.results_dir / "metrics.json", '{"a": 1}\n')
        observe(self.paths, STAGE_05)

        markdown = ResearchManager._build_skipped_stage_markdown(
            ResearchManager.__new__(ResearchManager),
            self.paths,
            STAGE_05,
            "ran out of attempts",
            "auto",
        )

        self.assertIn("workspace/results/metrics.json", markdown)
        self.assertIn("did leave 1 file(s)", markdown)
        self.assertIn("was not accepted", markdown)
        self.assertNotIn("its work was never done", markdown)

    def test_a_stage_that_left_nothing_says_nothing_extra(self) -> None:
        from src.manager import ResearchManager

        markdown = ResearchManager._build_skipped_stage_markdown(
            ResearchManager.__new__(ResearchManager),
            self.paths,
            STAGE_05,
            "ran out of attempts",
            "auto",
        )

        self.assertNotIn("did leave", markdown)
        self.assertIn("was not accepted", markdown)


if __name__ == "__main__":
    unittest.main()
