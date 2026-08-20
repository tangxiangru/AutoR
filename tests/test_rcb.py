"""What the benchmark adapter records about how a run ended.

`ResearchClawBench` scores `report/report.md`, so for a long time the adapter treated
"a substantive report exists" as the definition of success. That is right about a run
which lost a stage to its own recovery path and finished anyway. It is wrong about a
run that stopped, and the two were indistinguishable in every artifact a reader
consults.
"""

from __future__ import annotations

import os
import signal
import tempfile
import threading
import time
import unittest
from pathlib import Path

from rcb_agent import Terminated, _sigterm_as_exception
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


class ASchedulerKillMustLeaveAVerdictTest(unittest.TestCase):
    """A run that is killed has to say so, or the arm loses a task instead of failing one.

    The class above is about a walk that raised. This is the same defect one level out:
    a walk that never gets to raise. `_meta.json` is written once, after the result
    exists, so a process ended by a signal leaves the `running` the harness wrote at
    launch -- and nothing ever revisits it. Both readers gate on that field: `run_arm.py`
    will not resume the task and the scoring driver will not score it. The workspace
    reads as still in flight, permanently.

    Measured. On the `full40_pins` arm, Earth_003 reached its 40 h wall during Stage 07
    holding a finished 45,132-byte report and eleven figures. The scoring pass logged
    `scoreable workspaces: 39`, named nothing it had dropped, and the arm was written up
    at n=39 for two days with the fortieth deliverable complete on disk. A silent drop,
    not a failure: nothing anywhere said a task was missing.

    The fix routes SIGTERM into the handler that already exists, so a kill produces the
    same salvage-and-record path a crash does.
    """

    def test_sigterm_inside_the_block_raises_rather_than_killing(self) -> None:
        caught = ""
        with _sigterm_as_exception():
            try:
                os.kill(os.getpid(), signal.SIGTERM)
                time.sleep(2)  # the handler fires long before this returns
            except Terminated as exc:
                caught = str(exc)
        self.assertIn("SIGTERM", caught)
        self.assertIn("scheduler", caught)

    def test_it_is_an_ordinary_exception_so_the_existing_handler_catches_it(self) -> None:
        """The whole design is to reuse `except Exception` around `manager.run`.

        A `BaseException` subclass would sail past it, skip the export, and leave exactly
        the silence this removes.
        """
        self.assertTrue(issubclass(Terminated, Exception))

    def test_the_previous_handler_is_restored_on_the_way_out(self) -> None:
        """Leaving the handler installed would swallow the kill that follows the export."""
        before = signal.getsignal(signal.SIGTERM)
        with _sigterm_as_exception():
            self.assertIsNot(signal.getsignal(signal.SIGTERM), before)
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_it_is_restored_even_when_the_body_raises(self) -> None:
        before = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(ZeroDivisionError):
            with _sigterm_as_exception():
                _ = 1 / 0
        self.assertIs(signal.getsignal(signal.SIGTERM), before)

    def test_off_the_main_thread_it_is_a_no_op_rather_than_a_crash(self) -> None:
        """`signal.signal` raises off the main thread; a run there must still proceed.

        Nothing in the adapter calls `run` from a worker today. The guard is here so that
        the day something does, the failure is a run without kill-handling rather than a
        run that will not start.
        """
        outcome: list[str] = []

        def body() -> None:
            try:
                with _sigterm_as_exception():
                    outcome.append("ran")
            except Exception as exc:  # noqa: BLE001 - the point of the test
                outcome.append(f"raised {type(exc).__name__}")

        thread = threading.Thread(target=body)
        thread.start()
        thread.join(timeout=10)
        self.assertEqual(outcome, ["ran"])

    def test_a_killed_run_holding_a_real_report_is_aborted_not_completed(self) -> None:
        """The record the salvage path then writes, end to end on the result object.

        Earth_003's report was substantive, so every `report exists` test passes on it.
        `status` is the field that has to disagree.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.md"
            report.write_text("x" * (MIN_REPORT_CHARS + 10), encoding="utf-8")
            result = BenchmarkResult(
                workspace=root,
                run_root=root / ".autor" / "r",
                pipeline_completed=False,
                export=ExportResult(
                    report_path=report, report_source="stage_07", figures=[], code_files=0,
                    output_files=0,
                ),
                aborted_with="Terminated: signal 15 (SIGTERM); the scheduler ended this run",
            )
            self.assertEqual(result.status, "aborted")
            self.assertEqual(result.exit_code, 1)
            self.assertTrue(result.aborted)
