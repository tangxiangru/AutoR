"""What the benchmark adapter records about how a run ended.

`ResearchClawBench` scores `report/report.md`, so for a long time the adapter treated
"a substantive report exists" as the definition of success. That is right about a run
which lost a stage to its own recovery path and finished anyway. It is wrong about a
run that stopped, and the two were indistinguishable in every artifact a reader
consults.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rcb import MIN_REPORT_CHARS, BenchmarkResult, ExportResult




class AnAbortedRunIsNotACompletedOneTest(unittest.TestCase):
    """A crashed walk and a finished one must not produce the same record.

    Measured on the `full40_pins` arm. Life_002 died at Stage 03 of 7 on a
    `UnicodeDecodeError` raised while a prompt was being assembled; four stages were
    never attempted. The adapter caught it, exported a synthesised report from the
    partial state, and `exit_code` returned 0 because a 40 KB file existed. So
    `_meta.json` said `completed`, `run_arm.py` logged `DONE Life_002: completed`, the
    judge scored it 22.6, and that number entered a 40-task arm mean beside runs that
    had finished. The evidence was in `_agent_output.jsonl` -- `"pipeline_completed":
    false` next to `"report_source": "synthesized"` -- and nothing downstream read
    either field.

    An auto-skipped stage is deliberately still `completed`: the recovery path is
    designed, the walk reached the end, and the report is what the benchmark scores.
    The distinction here is finishing versus stopping, not degraded versus perfect.
    """

    def _result(self, body: str, *, aborted: str = "", skips: list[str] | None = None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        report = root / "report.md"
        report.write_text(body, encoding="utf-8")
        return BenchmarkResult(
            workspace=root,
            run_root=root / ".autor" / "r",
            pipeline_completed=not aborted,
            export=ExportResult(
                report_path=report, report_source="stage_07", figures=[], code_files=0,
                output_files=0,
            ),
            auto_skipped_stages=list(skips or []),
            aborted_with=aborted,
        )

    def test_a_finished_walk_with_a_real_report_is_completed(self) -> None:
        r = self._result("x" * (MIN_REPORT_CHARS + 10))
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.exit_code, 0)
        self.assertFalse(r.aborted)

    def test_an_auto_skipped_stage_is_still_completed(self) -> None:
        """The existing argument, kept: the benchmark scores the report."""
        r = self._result("x" * (MIN_REPORT_CHARS + 10), skips=["02_hypothesis_generation"])
        self.assertEqual(r.status, "completed")
        self.assertEqual(r.exit_code, 0)

    def test_an_aborted_walk_is_not_completed_however_big_the_report(self) -> None:
        r = self._result("x" * 40_000, aborted="UnicodeDecodeError: invalid start byte")
        self.assertTrue(r.aborted)
        self.assertEqual(r.status, "aborted")
        self.assertEqual(r.exit_code, 1)

    def test_a_finished_walk_with_a_stub_report_is_failed(self) -> None:
        r = self._result("too short")
        self.assertEqual(r.status, "failed")
        self.assertEqual(r.exit_code, 1)

    def test_an_aborted_walk_with_no_report_is_aborted_not_failed(self) -> None:
        """Which one it is matters: `failed` means it tried and produced nothing."""
        r = self._result("", aborted="MemoryError: ")
        self.assertEqual(r.status, "aborted")
