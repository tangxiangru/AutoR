"""A forward gate must not be satisfied by the future the run has just repudiated.

Six of the graph's forward edges are guarded by counting files under ``workspace/``. A
rollback set flags on the manifest and left ``workspace/`` alone, so the count those guards
read still included everything the abandoned stages had written. A run that reached Stage
06, found the study design wrong and rolled back to Stage 03 met an already-open edge out
of Stage 03 — opened by the data Stage 04 and Stage 05 had produced under the design being
abandoned. The gate that exists to prove *this* visit did the work was answering for the
visit the run had just repudiated.

``_guard_round_abandoned`` states the invariant the rest were relying on: "Every other
guard here reads stage artifacts, which a rollback invalidates." It was not true. This
module is where it becomes true, and the first test is the one that failed before
:mod:`src.provenance` and :mod:`src.effects` existed.

The same class of defect had already been patched once by hand, at one path, in
``_skip_stage``: a skipped Stage 06's round declaration was "never consumed and never
unlinked", so the next Stage 06 closed its round from the previous visit's file. One
instance, one patch. The general shape is what these tests hold.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.manifest import ensure_run_manifest, rollback_to_stage, update_stage_entry
from src.provenance import observe
from src.stage_graph import GUARDS, GraphState
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_03, STAGE_04, STAGE_05, STAGE_06 = STAGES[2], STAGES[3], STAGES[4], STAGES[5]


class RollbackClosesTheGateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)

    def _guard(self, name: str) -> bool:
        return GUARDS[name](self.paths, GraphState()).ok

    def test_the_design_gate_closes_when_the_design_it_counted_is_withdrawn(self) -> None:
        write_text(
            self.paths.experimental_protocol,
            '{"baselines": [{"name": "control"}]}\n',
        )
        write_text(self.paths.data_dir / "design_matrix.csv", "arm,n\ncontrol,30\n")
        observe(self.paths, STAGE_04)
        self.assertTrue(self._guard("design_artifacts"), "precondition: the gate is open")

        rollback_to_stage(self.paths, STAGE_03, "the design answered a different question")

        self.assertFalse(
            self._guard("design_artifacts"),
            "the edge out of Stage 03 was open on the strength of Stage 04's own output",
        )

    def test_the_results_gate_closes_when_the_experiment_is_withdrawn(self) -> None:
        write_text(self.paths.results_dir / "metrics.json", '{"accuracy": 0.9}\n')
        write_text(
            self.paths.experiment_manifest,
            '{"result_artifacts": [{"rel_path": "results/metrics.json"}]}\n',
        )
        observe(self.paths, STAGE_05)
        self.assertTrue(self._guard("results_exist"))

        rollback_to_stage(self.paths, STAGE_04, "the implementation was wrong")

        self.assertFalse(self._guard("results_exist"))

    def test_the_code_gate_closes_when_the_implementation_is_withdrawn(self) -> None:
        write_text(self.paths.code_dir / "run.py", "print('hi')\n")
        observe(self.paths, STAGE_04)
        self.assertTrue(self._guard("runnable_code"))

        rollback_to_stage(self.paths, STAGE_04, "wrong implementation")

        self.assertFalse(self._guard("runnable_code"))

    def test_the_report_gate_closes_when_the_manuscript_is_withdrawn(self) -> None:
        write_text(self.paths.writing_dir / "paper.md", "# Findings\n")
        observe(self.paths, STAGE_06)
        self.assertTrue(self._guard("report_exists"))

        rollback_to_stage(self.paths, STAGE_05, "the analysis was wrong")

        self.assertFalse(self._guard("report_exists"))

    def test_the_hypothesis_gate_closes_when_the_manifest_is_withdrawn(self) -> None:
        write_text(
            self.paths.hypothesis_manifest,
            '{"empirical_hypotheses": [{"id": "H1", "type": "empirical"}]}\n',
        )
        observe(self.paths, STAGE_04)
        self.assertTrue(self._guard("has_hypotheses"))

        rollback_to_stage(self.paths, STAGE_03, "the hypotheses were not falsifiable")

        self.assertFalse(self._guard("has_hypotheses"))

    def test_a_gate_reopens_once_the_re_run_actually_redoes_the_work(self) -> None:
        """The withdrawal is not a permanent closure. It is a demand for this visit's work.

        A run that rolls back and then genuinely re-does the stage must get its edge back,
        or the mechanism has replaced one broken gate with another.
        """

        write_text(self.paths.experimental_protocol, '{"baselines": [{"name": "control"}]}\n')
        write_text(self.paths.data_dir / "design_matrix.csv", "arm,n\ncontrol,30\n")
        observe(self.paths, STAGE_04)
        rollback_to_stage(self.paths, STAGE_03, "wrong design")
        self.assertFalse(self._guard("design_artifacts"))

        # Both halves have to be redone, and the gate is right to want both. The protocol
        # was Stage 04's too, so the rollback withdrew it; a re-run that rewrote only the
        # data matrix would be declaring a design against baselines it had disowned.
        write_text(self.paths.data_dir / "design_matrix.csv", "arm,n\ncontrol,60\ntreatment,60\n")
        self.assertFalse(self._guard("design_artifacts"))
        write_text(
            self.paths.experimental_protocol,
            '{"baselines": [{"name": "control"}, {"name": "treatment"}]}\n',
        )
        observe(self.paths, STAGE_03)

        self.assertTrue(self._guard("design_artifacts"))

    def test_work_from_before_the_rollback_target_still_counts(self) -> None:
        """A rollback withdraws a range, not a directory.

        Stage 03's own data must survive a rollback to Stage 04, or the graph's backward
        edge costs more than the pipeline it replaced.
        """

        write_text(self.paths.experimental_protocol, '{"baselines": [{"name": "control"}]}\n')
        write_text(self.paths.data_dir / "design_matrix.csv", "arm,n\ncontrol,30\n")
        observe(self.paths, STAGE_03)
        write_text(self.paths.data_dir / "run_log.csv", "step,loss\n1,0.5\n")
        observe(self.paths, STAGE_05)

        rollback_to_stage(self.paths, STAGE_04, "the implementation was wrong")

        self.assertTrue((self.paths.data_dir / "design_matrix.csv").exists())
        self.assertFalse((self.paths.data_dir / "run_log.csv").exists())
        self.assertTrue(self._guard("design_artifacts"))

    def test_a_run_with_no_ledger_behaves_as_it_did_before_one_existed(self) -> None:
        """Fail-open, checked. Every counting gate would close at once if it did not."""

        write_text(self.paths.experimental_protocol, '{"baselines": [{"name": "control"}]}\n')
        write_text(self.paths.data_dir / "design_matrix.csv", "arm,n\ncontrol,30\n")

        self.assertTrue(self._guard("design_artifacts"))
        rollback_to_stage(self.paths, STAGE_03, "no attribution exists for any of this")
        self.assertTrue(self._guard("design_artifacts"))

    def test_the_manifest_half_of_the_rollback_still_happens(self) -> None:
        update_stage_entry(self.paths, STAGE_05, status="approved", approved=True)
        rollback_to_stage(self.paths, STAGE_03, "reason")

        manifest = ensure_run_manifest(self.paths)
        by_number = {entry.number: entry for entry in manifest.stages}
        self.assertEqual(by_number[STAGE_03.number].status, "pending")
        self.assertTrue(by_number[STAGE_05.number].stale)
        self.assertEqual(manifest.current_stage_slug, STAGE_03.slug)


if __name__ == "__main__":
    unittest.main()
