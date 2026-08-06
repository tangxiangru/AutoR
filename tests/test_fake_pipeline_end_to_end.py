"""End-to-end coverage for ``--fake-operator``.

Fake mode is the only way to exercise all nine stages without a model, so it is
the only end-to-end signal CI can have. That is worth an explicit test: before
this existed, fake mode could reach stage 02 and no further — stages 03 through
06 each failed the same artifact gate, burned their retry budget and were
auto-skipped, and the run aborted. Every unit test still passed, because none of
them ran the pipeline.

The assertions below are deliberately about *how* the run completed, not just
that it exited zero. An auto-skipped stage also lets a run "continue".
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.manifest import load_run_manifest
from src.utils import STAGES, build_run_paths, validate_stage_artifacts


REPO_ROOT = Path(__file__).resolve().parent.parent


class FakePipelineEndToEndTest(unittest.TestCase):
    #: Overridden by the LaTeX subclass. ``None`` means "whatever the default is",
    #: which is the path most users take and the one that must not regress.
    OUTPUT_FORMAT: str | None = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        runs_dir = Path(self._tmp.name) / "runs"

        command = [
            sys.executable,
            "main.py",
            "--fake-operator",
            "--full-auto",
            "--goal",
            "End-to-end fake pipeline coverage.",
            "--runs-dir",
            str(runs_dir),
        ]
        if self.OUTPUT_FORMAT is not None:
            command.extend(["--output-format", self.OUTPUT_FORMAT])

        self.result = subprocess.run(
            command,
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=300,
        )
        run_roots = sorted(path for path in runs_dir.iterdir() if path.is_dir())
        self.assertEqual(len(run_roots), 1, msg=self.result.stdout[-2000:])
        self.run_root = run_roots[0]
        self.paths = build_run_paths(self.run_root)
        manifest = load_run_manifest(self.paths.run_manifest)
        assert manifest is not None
        self.manifest = manifest

    def test_the_run_completes(self) -> None:
        self.assertEqual(self.result.returncode, 0, msg=self.result.stdout[-4000:])
        self.assertEqual(self.manifest.run_status, "completed")
        self.assertIsNotNone(self.manifest.completed_at)

    def test_every_stage_is_approved_and_none_is_skipped(self) -> None:
        by_slug = {entry.slug: entry for entry in self.manifest.stages}
        self.assertEqual(sorted(by_slug), sorted(stage.slug for stage in STAGES))
        for slug, entry in sorted(by_slug.items()):
            with self.subTest(stage=slug):
                self.assertEqual(entry.status, "approved")
                self.assertTrue(entry.approved)
                self.assertFalse(entry.skipped, msg=f"{slug} was skipped, not completed")
                self.assertIsNone(entry.last_error)

    def test_no_stage_needed_a_retry(self) -> None:
        """A retry in fake mode means a gate the fake operator cannot clear.

        This is the assertion that actually fails when a new artifact gate is
        added without teaching fake mode to satisfy it. Without it the run still
        passes, just slower and via the auto-skip path.
        """
        retried = {
            entry.slug: entry.attempt_count
            for entry in self.manifest.stages
            if entry.attempt_count != 1
        }
        self.assertEqual(retried, {}, msg=f"stages that did not pass first try: {retried}")

    def test_each_stage_satisfies_its_own_artifact_gates(self) -> None:
        for stage in STAGES:
            with self.subTest(stage=stage.slug):
                self.assertEqual(validate_stage_artifacts(stage, self.paths), [])

    def test_the_manuscript_package_is_a_real_pdf(self) -> None:
        pdf = self.paths.writing_dir / "main.pdf"
        self.assertTrue(pdf.exists())
        self.assertTrue(pdf.read_bytes().startswith(b"%PDF-"))

    def test_the_placeholder_artifacts_say_they_are_placeholders(self) -> None:
        """Fake output must never be mistakable for a result.

        The run directory outlives the run, and these files sit in the same
        paths a real run writes to.
        """
        for rel in (
            "data/fake_dataset.json",
            "results/fake_results.json",
            "artifacts/layout_review.json",
            "reviews/readiness_review.json",
        ):
            with self.subTest(artifact=rel):
                path = self.paths.workspace_root / rel
                self.assertTrue(path.exists(), msg=f"{rel} missing")
                payload = json.dumps(json.loads(path.read_text(encoding="utf-8"))).lower()
                self.assertTrue(
                    "placeholder" in payload or "not real" in payload,
                    msg=f"{rel} does not disclose that it is fake output",
                )

    def test_the_markdown_report_is_a_real_report_that_admits_it_is_fake(self) -> None:
        if self.OUTPUT_FORMAT == "latex":
            self.skipTest("markdown report is not the deliverable in latex mode")
        report = self.paths.report_file
        self.assertTrue(report.exists())
        text = report.read_text(encoding="utf-8")
        self.assertIn("fake operator", text.lower())
        image = self.paths.report_images_dir / "fake_comparison.png"
        self.assertTrue(image.exists())
        self.assertTrue(image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


class FakePipelineLatexEndToEndTest(FakePipelineEndToEndTest):
    """The same run with ``--output-format latex``.

    Stage 07's gates fork on the output format, so a fake operator that only
    satisfies one branch leaves the other exactly as broken as both used to be.
    """

    OUTPUT_FORMAT = "latex"


if __name__ == "__main__":
    unittest.main()
