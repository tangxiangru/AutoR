"""The report source decides the score, so both degraded paths are pinned here.

Across forty ResearchClawBench runs a synthesized report scored 19.52 and the deterministic
fallback 7.50 -- the same pipeline, the same artifacts, twelve points apart. Two defects
produced that gap: synthesis was one operator call with no retry, taken at the end of a run
that had just aborted; and the fallback read only ``stages/``, so a run that cleared no
stage shipped 197 bytes while holding tens of kilobytes of drafts and five figures on disk.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.rcb import ReportSynthesizer, build_fallback_report, unapproved_stage_bodies
from src.utils import MIN_REPORT_CHARS, build_run_paths, ensure_run_layout, write_text


BODY = "Substantive finding with a number: the barrier is 0.42 eV. " * 60


class RecoverUnapprovedWorkTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def _evolution(self, stage: str, *, champion: str | None = None, attempts: dict[str, str] | None = None) -> None:
        stage_dir = self.paths.evolution_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        if champion is not None:
            write_text(stage_dir / "champion.md", champion)
        for name, text in (attempts or {}).items():
            (stage_dir / "candidates").mkdir(parents=True, exist_ok=True)
            write_text(stage_dir / "candidates" / name, text)

    def test_a_champion_is_recovered(self) -> None:
        self._evolution("01_literature_survey", champion=f"# Stage 01\n\n## Objective\n\n{BODY}")
        recovered = unapproved_stage_bodies(self.paths)
        self.assertEqual(len(recovered), 1)
        self.assertIn("unapproved", recovered[0][0].lower())
        self.assertIn("0.42 eV", recovered[0][1])

    def test_the_champion_wins_over_the_candidates(self) -> None:
        """The champion is what the ratchet converged on; a candidate is a rejected draft."""
        self._evolution(
            "01_literature_survey",
            champion=f"# Stage 01\n\nCHAMPION {BODY}",
            attempts={"attempt_01.md": f"# Stage 01\n\nCANDIDATE {BODY}"},
        )
        body = unapproved_stage_bodies(self.paths)[0][1]
        self.assertIn("CHAMPION", body)
        self.assertNotIn("CANDIDATE", body)

    def test_only_the_newest_candidate_is_read_when_there_is_no_champion(self) -> None:
        """Six failed attempts at one stage must not become six near-identical sections."""
        self._evolution(
            "02_hypothesis_generation",
            attempts={
                "attempt_01.md": f"# Stage 02\n\nFIRST {BODY}",
                "attempt_02.md": f"# Stage 02\n\nSECOND {BODY}",
                "attempt_03.md": f"# Stage 02\n\nTHIRD {BODY}",
            },
        )
        recovered = unapproved_stage_bodies(self.paths)
        self.assertEqual(len(recovered), 1)
        self.assertIn("THIRD", recovered[0][1])
        self.assertNotIn("FIRST", recovered[0][1])

    def test_a_run_with_no_evolution_tree_recovers_nothing(self) -> None:
        self.assertEqual(unapproved_stage_bodies(self.paths), [])

    def test_workflow_scaffolding_is_stripped_from_a_draft_too(self) -> None:
        """A recovered draft goes through the same filter as an approved stage summary."""
        self._evolution(
            "01_literature_survey",
            champion=f"# Stage 01\n\n## Your Options\n\n1. Use suggestion 1\n6. Abort\n\n## Findings\n\n{BODY}",
        )
        body = unapproved_stage_bodies(self.paths)[0][1]
        self.assertNotIn("Abort", body)
        self.assertIn("0.42 eV", body)


class FallbackUsesRecoveredWorkTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def _build(self, figures: list[str] | None = None) -> str:
        return build_fallback_report(
            paths=self.paths,
            figures=figures or [],
            pipeline_completed=False,
            auto_skipped_stages=[],
        )

    def _champion(self, stage: str, text: str) -> None:
        stage_dir = self.paths.evolution_dir / stage
        stage_dir.mkdir(parents=True, exist_ok=True)
        write_text(stage_dir / "champion.md", text)

    def test_material_002_shipped_197_bytes_and_should_not_have(self) -> None:
        """The exact benchmark failure: real drafts on disk, a stub report published."""
        self._champion("01_literature_survey", f"# Stage 01\n\n## Objective\n\n{BODY}")
        report = self._build(figures=["fig1_data_audit.png"])
        self.assertGreater(len(report), MIN_REPORT_CHARS)
        self.assertIn("0.42 eV", report)
        self.assertNotIn("No completed stage output was produced", report)

    def test_the_report_says_the_draft_was_never_approved(self) -> None:
        """Passing unreviewed drafts off as findings would be the worse defect."""
        self._champion("01_literature_survey", f"# Stage 01\n\n{BODY}")
        report = self._build()
        self.assertIn("No stage was approved", report)
        self.assertIn("unverified", report)

    def test_the_two_notices_do_not_contradict_each_other(self) -> None:
        """It cannot claim assembly from completed stages when none completed."""
        self._champion("01_literature_survey", f"# Stage 01\n\n{BODY}")
        self.assertNotIn("assembled from the stages that were completed", self._build())

    def test_an_approved_stage_is_never_mixed_with_a_draft(self) -> None:
        write_text(self.paths.stages_dir / "01_literature_survey.md", f"# Stage 01\n\nAPPROVED {BODY}")
        self._champion("01_literature_survey", f"# Stage 01\n\nDRAFT {BODY}")
        report = self._build()
        self.assertIn("APPROVED", report)
        self.assertNotIn("DRAFT", report)
        self.assertNotIn("unapproved draft", report)
        self.assertIn("assembled from the stages that were completed", report)

    def test_a_run_with_nothing_at_all_still_says_so(self) -> None:
        report = self._build()
        self.assertIn("No completed stage output was produced", report)

    def test_the_skip_stub_sidecar_is_never_a_report_section(self) -> None:
        """A rescued draft is promoted and the stub is kept beside it for the audit trail.

        Both are `*.md` in `stages/`. A reader that takes both ships the stage's real
        research and then, immediately below it, "This stage was skipped (auto) and its work
        was never done" -- about the work directly above. Observed on the live re-runs:
        Math_001 has 01_literature_survey.md holding a full survey next to
        01_literature_survey.skip_stub.md saying it never happened.
        """
        write_text(self.paths.stages_dir / "01_literature_survey.md", f"# Stage 01\n\nRESCUED {BODY}")
        write_text(
            self.paths.stages_dir / "01_literature_survey.skip_stub.md",
            "# Stage 01: Literature Survey\n\n## Key Results\n\n"
            "- This stage was skipped (auto) and its work was never done.\n",
        )
        report = self._build()
        self.assertIn("RESCUED", report)
        self.assertNotIn("its work was never done", report)

    def test_a_lone_skip_stub_does_not_block_champion_recovery(self) -> None:
        """The sidecar is not a stage summary, so it cannot stand in for one."""
        write_text(
            self.paths.stages_dir / "01_literature_survey.skip_stub.md",
            "# Stage 01\n\n- This stage was skipped (auto).\n",
        )
        self._champion("01_literature_survey", f"# Stage 01\n\nDRAFT {BODY}")
        report = self._build()
        self.assertIn("DRAFT", report)
        self.assertIn("No stage was approved", report)

    def test_a_draft_under_review_is_still_excluded(self) -> None:
        write_text(self.paths.stages_dir / "01_literature_survey.tmp.md", f"# Stage 01\n\nUNDER_REVIEW {BODY}")
        self.assertNotIn("UNDER_REVIEW", self._build())

    def test_figures_are_still_linked_after_a_draft_is_recovered(self) -> None:
        self._champion("01_literature_survey", f"# Stage 01\n\n{BODY}")
        report = self._build(figures=["fig1.png", "fig2.png"])
        self.assertIn("![fig1](images/fig1.png)", report)
        self.assertIn("![fig2](images/fig2.png)", report)


class _Operator:
    """Minimal stand-in for the operator seam ReportSynthesizer reaches through."""

    def __init__(self, outcomes: list[str], report_path: Path) -> None:
        self.outcomes = outcomes
        self.report_path = report_path
        self.attempts: list[int] = []

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):  # noqa: ANN001
        return (["true"], str(prompt_path.parent), None)

    def _run_streaming_command(self, *, command, cwd, stage, attempt_no, paths, mode, stdin_text):  # noqa: ANN001
        self.attempts.append(attempt_no)
        outcome = self.outcomes[min(len(self.attempts), len(self.outcomes)) - 1]
        if outcome == "crash":
            raise RuntimeError("operator died")
        if outcome == "nonzero":
            return (1, "", "", "s", {})
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        self.report_path.write_text(
            "x" if outcome == "thin" else f"# Report\n\n{BODY}", encoding="utf-8"
        )
        return (0, "", "", "s", {})


class SynthesisRetryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.workspace = root / "ws"
        self.paths = build_run_paths(root / "run_0001")
        ensure_run_layout(self.paths)
        self.report_path = self.workspace / "report" / "report.md"

    def _run(self, outcomes: list[str], **kwargs) -> tuple[str | None, _Operator]:
        operator = _Operator(outcomes, self.report_path)
        result = ReportSynthesizer(operator, **kwargs)(
            paths=self.paths, workspace=self.workspace, figures=[]
        )
        return result, operator

    def test_a_first_call_that_works_is_not_repeated(self) -> None:
        result, operator = self._run(["ok"])
        self.assertIsNotNone(result)
        self.assertEqual(operator.attempts, [1])

    def test_a_failed_call_is_retried_rather_than_costing_the_report(self) -> None:
        """The defect: one bad call at the end of an aborted run forfeited ~12 points."""
        result, operator = self._run(["nonzero", "ok"])
        self.assertIsNotNone(result)
        self.assertEqual(operator.attempts, [1, 2])

    def test_a_crash_is_retried_too(self) -> None:
        result, operator = self._run(["crash", "ok"])
        self.assertIsNotNone(result)
        self.assertEqual(len(operator.attempts), 2)

    def test_a_thin_answer_is_retried_because_export_would_discard_it(self) -> None:
        result, operator = self._run(["thin", "ok"])
        self.assertIsNotNone(result)
        self.assertGreaterEqual(len(result.strip()), MIN_REPORT_CHARS)
        self.assertEqual(operator.attempts, [1, 2])

    def test_it_gives_up_and_lets_the_fallback_stand(self) -> None:
        result, operator = self._run(["nonzero"])
        self.assertIsNone(result)
        self.assertEqual(len(operator.attempts), ReportSynthesizer.MAX_ATTEMPTS)

    def test_each_retry_is_recorded_as_its_own_attempt(self) -> None:
        """Sharing attempt_no=1 would overwrite the previous attempt's operator log."""
        _result, operator = self._run(["nonzero", "nonzero", "ok"])
        self.assertEqual(operator.attempts, [1, 2, 3])

    def test_the_attempt_count_cannot_be_configured_to_zero(self) -> None:
        _result, operator = self._run(["ok"], max_attempts=0)
        self.assertEqual(operator.attempts, [1])

    def test_an_unsupported_operator_is_not_retried(self) -> None:
        class Bare:
            pass

        self.assertIsNone(
            ReportSynthesizer(Bare())(paths=self.paths, workspace=self.workspace, figures=[])
        )


if __name__ == "__main__":
    unittest.main()
