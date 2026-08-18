from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.prereg_support import write_validity_chain
from src.experiment_manifest import write_experiment_manifest
from src.utils import (
    DEFAULT_VENUE,
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    load_run_config,
    selected_venue_key,
    validate_stage_artifacts,
    write_text,
)
from src.writing_manifest import (
    build_writing_manifest,
    format_manifest_for_prompt,
    generate_layout_review,
    scan_figures,
    validate_layout_review,
)


STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")
REPO_ROOT = Path(__file__).resolve().parent.parent


class WritingPipelineTests(unittest.TestCase):
    def _build_paths(self) -> tuple[Path, object]:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, "Test writing pipeline")
        write_text(paths.memory, "# Approved Run Memory\n\n## Original User Goal\nTest\n\n## Approved Stage Summaries\n\n_None yet._\n")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="latex")
        write_text(paths.data_dir / "design.json", '{"task":"test"}')
        write_text(paths.results_dir / "metrics.json", '{"accuracy": 0.9}')
        write_validity_chain(paths, evidence="results/metrics.json")
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")
        return run_root, paths

    def _populate_valid_stage07_outputs(self, paths: object) -> None:
        write_experiment_manifest(paths)
        sections_dir = paths.writing_dir / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)

        write_text(
            paths.writing_dir / "main.tex",
            (
                "% AutoR venue: neurips_2025\n"
                "\\documentclass{article}\n"
                "\\usepackage{neurips_2023}\n"
                "\\begin{document}\n"
                "\\input{sections/introduction}\n"
                "\\end{document}\n"
            ),
        )
        write_text(
            paths.writing_dir / "references.bib",
            (
                "@article{test2024,\n"
                "  title={Test},\n"
                "  author={Author, A.},\n"
                "  year={2024}\n"
                "}\n"
            ),
        )
        write_text(sections_dir / "introduction.tex", "\\section{Introduction}\nContent.\n")
        write_text(sections_dir / "method.tex", "\\section{Method}\nContent.\n")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4 minimal but present")
        write_text(paths.artifacts_dir / "build_log.txt", "=== Build Log ===\nFinal status: SUCCESS\n")
        write_text(
            paths.artifacts_dir / "citation_verification.json",
            json.dumps(
                {
                    "overall_status": "pass",
                    "total_citations": 1,
                    "verified_citations": 1,
                    "unresolved_citations": 0,
                    "claim_coverage": [
                        {
                            "claim": "The method improves accuracy on the benchmark.",
                            "citation_keys": ["test2024"],
                        }
                    ],
                }
            ),
        )
        write_text(
            paths.artifacts_dir / "self_review.json",
            json.dumps({"overall_score": 8.0, "final_verdict": "ready", "rounds": 1}),
        )
        # The deliverables contract is a Stage 07 gate in both formats now, not only in
        # markdown -- whether the run answered the question it was given is not a
        # question about how the answer was typeset. The fixture states what a valid
        # latex Stage 07 looks like, so it has to carry one.
        from src.deliverables import COVERAGE_FILENAME

        write_text(
            paths.artifacts_dir / COVERAGE_FILENAME,
            json.dumps({"deliverables": [
                {"task_quote": "Test writing pipeline", "addressed": False,
                 "reason": "the fixture builds a manuscript shape, not research"},
            ]}),
        )
        generate_layout_review(paths)

    def test_stage07_validation_passes_with_expected_outputs(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_stage07_validation_requires_supported_venue_signal(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.writing_dir / "main.tex",
            "\\documentclass{article}\n\\begin{document}\nHello\n\\end{document}\n",
        )
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("supported conference or journal manuscript" in problem for problem in problems))

    def test_stage07_validation_accepts_journal_profile_with_inline_bibliography(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="sonnet", venue="nature")
        self._populate_valid_stage07_outputs(paths)
        (paths.writing_dir / "references.bib").unlink()
        write_text(
            paths.writing_dir / "main.tex",
            (
                "% AutoR venue: nature\n"
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "Journal draft.\n"
                "\\begin{thebibliography}{9}\n"
                "\\bibitem{test2024} Author. Test. 2024.\n"
                "\\end{thebibliography}\n"
                "\\end{document}\n"
            ),
        )
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_run_config_defaults_to_neurips_when_missing(self) -> None:
        _, paths = self._build_paths()
        paths.run_config.unlink()
        self.assertEqual(selected_venue_key(paths), DEFAULT_VENUE)

    def test_run_config_persists_selected_venue(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="opus", venue="nature")
        config = load_run_config(paths)
        self.assertEqual(config["model"], "opus")
        self.assertEqual(config["operator"], "claude")
        self.assertEqual(config["venue"], "nature")

    def test_run_config_persists_selected_operator(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="default", operator="codex", venue="nature")
        config = load_run_config(paths)
        self.assertEqual(config["model"], "default")
        self.assertEqual(config["operator"], "codex")
        self.assertEqual(config["venue"], "nature")

    def test_resume_without_explicit_venue_preserves_existing_run_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "demo_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Resume test goal")
            write_text(
                paths.memory,
                "# Approved Run Memory\n\n## Original User Goal\nResume test\n\n## Approved Stage Summaries\n\n_None yet._\n",
            )
            ensure_run_config(paths, model="opus", venue="nature")

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "demo_run",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config = load_run_config(paths)
            self.assertEqual(config["model"], "opus")
            self.assertEqual(config["operator"], "claude")
            self.assertEqual(config["venue"], "nature")

    def test_resume_without_explicit_operator_preserves_existing_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "codex_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Resume codex goal")
            write_text(
                paths.memory,
                "# Approved Run Memory\n\n## Original User Goal\nResume codex\n\n## Approved Stage Summaries\n\n_None yet._\n",
            )
            ensure_run_config(paths, model="default", operator="codex", venue="nature")

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "codex_run",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config = load_run_config(paths)
            self.assertEqual(config["model"], "default")
            self.assertEqual(config["operator"], "codex")
            self.assertEqual(config["venue"], "nature")

    def test_resume_old_run_without_run_config_falls_back_to_sonnet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            run_root = runs_dir / "legacy_run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Legacy resume goal")
            write_text(
                paths.memory,
                "# Approved Run Memory\n\n## Original User Goal\nLegacy test\n\n## Approved Stage Summaries\n\n_None yet._\n",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    "main.py",
                    "--fake-operator",
                    "--resume-run",
                    "legacy_run",
                    "--runs-dir",
                    str(runs_dir),
                ],
                cwd=REPO_ROOT,
                input="6\n",
                text=True,
                capture_output=True,
            )

            self.assertEqual(result.returncode, 1, msg=result.stderr)
            config = load_run_config(paths)
            self.assertEqual(config["model"], "sonnet")
            self.assertEqual(config["operator"], "claude")
            self.assertEqual(config["venue"], DEFAULT_VENUE)

    def test_stage07_validation_does_not_accept_generic_journal_word_for_nature(self) -> None:
        _, paths = self._build_paths()
        ensure_run_config(paths, model="sonnet", venue="nature")
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.writing_dir / "main.tex",
            (
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "This is a journal-style draft.\n"
                "\\end{document}\n"
            ),
        )
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("Expected venue: nature" in problem for problem in problems))

    def test_stage07_validation_requires_build_log(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "build_log.txt").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("build_log.txt" in problem for problem in problems))

    def test_stage07_validation_requires_self_review(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "self_review.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("self_review.json" in problem for problem in problems))

    def test_stage07_validation_requires_layout_review(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        (paths.artifacts_dir / "layout_review.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("layout_review.json" in problem for problem in problems))

    def test_stage07_validation_requires_claim_coverage_in_citation_verification(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.artifacts_dir / "citation_verification.json",
            json.dumps({"overall_status": "pass", "total_citations": 1}),
        )
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("claim_coverage" in problem for problem in problems))

    def test_scan_figures_returns_expected_metadata(self) -> None:
        _, paths = self._build_paths()
        figures = scan_figures(paths.figures_dir)
        self.assertEqual(len(figures), 1)
        self.assertEqual(figures[0]["filename"], "accuracy.png")

    def test_build_writing_manifest_creates_manifest_json(self) -> None:
        _, paths = self._build_paths()
        generate_layout_review(paths)
        manifest = build_writing_manifest(paths)
        self.assertIn("figures", manifest)
        self.assertIn("result_files", manifest)
        self.assertTrue((paths.writing_dir / "manifest.json").exists())
        self.assertIn("layout_review", manifest)

    def test_format_manifest_for_prompt_mentions_figures_and_results(self) -> None:
        _, paths = self._build_paths()
        generate_layout_review(paths)
        manifest = build_writing_manifest(paths)
        formatted = format_manifest_for_prompt(manifest)
        self.assertIn("accuracy.png", formatted)
        self.assertIn("metrics.json", formatted)
        self.assertIn("layout_review.json", formatted)

    def test_generate_layout_review_captures_latex_warnings(self) -> None:
        _, paths = self._build_paths()
        self._populate_valid_stage07_outputs(paths)
        write_text(
            paths.artifacts_dir / "build_log.txt",
            (
                "Overfull \\hbox (12.0pt too wide) in paragraph at lines 12--13\n"
                "LaTeX Warning: Citation `missing2026' on page 2 undefined\n"
            ),
        )
        review = generate_layout_review(paths)

        self.assertEqual(review["overall_status"], "needs_attention")
        self.assertEqual(review["issue_counts"]["overfull_hboxes"], 1)
        self.assertEqual(review["issue_counts"]["undefined_citations"], 1)
        self.assertEqual(validate_layout_review(paths.artifacts_dir / "layout_review.json"), [])

    def test_registry_yaml_exists_and_mentions_conference_and_journal_profiles(self) -> None:
        registry_path = Path("templates/registry.yaml")
        self.assertTrue(registry_path.exists())
        text = registry_path.read_text(encoding="utf-8")
        self.assertIn("neurips_2025:", text)
        self.assertIn("nature:", text)
        self.assertIn('venue_type: "journal"', text)


if __name__ == "__main__":
    unittest.main()
