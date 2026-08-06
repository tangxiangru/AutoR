from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.artifact_index import write_artifact_index
from src.manifest import (
    initialize_run_manifest,
    mark_stage_approved_manifest,
    mark_stage_human_review_manifest,
)
from src.studio_service import IterationRequest, StudioService
from src.utils import STAGES, build_run_paths, ensure_run_layout, initialize_run_config, write_text


STAGE_01 = next(stage for stage in STAGES if stage.slug == "01_literature_survey")
STAGE_02 = next(stage for stage in STAGES if stage.slug == "02_hypothesis_generation")
STAGE_03 = next(stage for stage in STAGES if stage.slug == "03_study_design")
STAGE_04 = next(stage for stage in STAGES if stage.slug == "04_implementation")
STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")
STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")


class StudioServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.tempdir.name)
        self.runs_dir = self.repo_root / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_root = self.repo_root / ".autor-test"
        self.service = StudioService(
            repo_root=self.repo_root,
            runs_dir=self.runs_dir,
            metadata_root=self.metadata_root,
        )
        self.review_run_id = self._create_review_run("20260409_101010")
        self.writing_run_id = self._create_writing_run("20260409_202020")

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_create_project_and_attach_run(self) -> None:
        project = self.service.create_project(
            title="Sparse MoE Study",
            thesis="Compare routing and training stability choices.",
            tags=["moe", "routing"],
        )

        attached = self.service.attach_run_to_project(project.project_id, self.review_run_id)
        projects = self.service.list_projects()

        self.assertEqual(project.project_id, "sparse-moe-study")
        self.assertEqual(project.participation_model, "human_in_loop")
        self.assertEqual(attached.active_run_id, self.review_run_id)
        self.assertEqual(projects[0].run_ids, [self.review_run_id])
        self.assertEqual(projects[0].tags, ["moe", "routing"])

    def test_get_project_summary_includes_active_run_state(self) -> None:
        project = self.service.create_project(
            title="Sparse MoE Study",
            thesis="Compare routing and training stability choices.",
        )
        self.service.attach_run_to_project(project.project_id, self.review_run_id)

        summary = self.service.get_project_summary(project.project_id)

        self.assertEqual(summary.project_id, project.project_id)
        self.assertEqual(summary.active_run_id, self.review_run_id)
        self.assertEqual(summary.latest_run_status, "human_review")
        self.assertEqual(summary.latest_completed_stage_slug, STAGE_04.slug)

    def test_get_run_history_exposes_versions_and_trace(self) -> None:
        history = self.service.get_run_history(self.review_run_id)

        self.assertEqual(history.run_id, self.review_run_id)
        self.assertTrue(any(version.kind == "auto_checkpoint" for version in history.versions))
        self.assertTrue(any(version.kind == "awaiting_review" for version in history.versions))
        self.assertTrue(any(event.title == "Run Started" for event in history.trace_events))
        self.assertTrue(any(event.title == "Approved" and event.actor == "human" for event in history.trace_events))

    def test_get_run_summary_reads_manifest_and_artifacts(self) -> None:
        summary = self.service.get_run_summary(self.review_run_id)

        self.assertEqual(summary.run_id, self.review_run_id)
        self.assertEqual(summary.goal, "Evaluate a staged review run.")
        self.assertEqual(summary.model, "sonnet")
        self.assertEqual(summary.venue, "neurips_2025")
        self.assertEqual(summary.run_status, "human_review")
        self.assertEqual(summary.current_stage_slug, STAGE_05.slug)
        self.assertEqual(summary.artifact_count, 3)
        self.assertEqual(summary.counts_by_category["data"], 1)
        self.assertEqual(summary.counts_by_category["results"], 1)
        self.assertEqual(summary.counts_by_category["figures"], 1)
        self.assertEqual(summary.stages[4].status, "human_review")
        self.assertEqual(summary.stages[4].attempt_count, 2)

    def test_get_stage_document_returns_saved_markdown(self) -> None:
        markdown = self.service.get_stage_document(self.review_run_id, STAGE_01.slug)
        self.assertIn("# Stage 01: Literature Survey", markdown)
        self.assertIn("## Key Results", markdown)

    def test_get_paper_preview_reports_markdown_runs_as_markdown(self) -> None:
        run_id = self._create_markdown_report_run("20260409_303030")

        preview = self.service.get_paper_preview(run_id)

        self.assertEqual(preview.output_format, "markdown")
        self.assertTrue(preview.report_available)
        self.assertEqual(preview.report_relative_path, "workspace/report/report.md")
        self.assertIn("## Results", preview.report_content)
        # A markdown run has no PDF by design; the panel must not read as a failed build.
        self.assertFalse(preview.pdf_available)

    def test_get_paper_preview_returns_pdf_and_manuscript_sources(self) -> None:
        preview = self.service.get_paper_preview(self.writing_run_id)
        self.assertEqual(preview.output_format, "latex")
        self.assertFalse(preview.report_available)

        self.assertEqual(preview.run_id, self.writing_run_id)
        self.assertTrue(preview.pdf_available)
        self.assertEqual(preview.pdf_relative_path, "workspace/artifacts/paper.pdf")
        self.assertEqual(preview.tex_relative_path, "workspace/writing/main.tex")
        self.assertIn("\\input{sections/method}", preview.tex_content)
        self.assertIn("workspace/writing/sections/method.tex", preview.section_paths)
        self.assertEqual(preview.build_log_relative_path, "workspace/writing/build.log")
        self.assertIn("latexmk -pdf main.tex", preview.build_log_content)

    def test_build_file_tree_lists_workspace_files(self) -> None:
        tree = self.service.build_file_tree(self.review_run_id)
        rel_paths = _collect_tree_paths(tree)

        self.assertEqual(tree.rel_path, "workspace")
        self.assertIn("workspace/literature/survey_notes.md", rel_paths)
        self.assertIn("workspace/results/results.json", rel_paths)
        self.assertIn("workspace/figures/accuracy.png", rel_paths)
        self.assertIn("workspace/writing/main.tex", rel_paths)
        self.assertNotIn("workspace/.hidden.txt", rel_paths)

    def test_plan_iteration_redo_marks_only_materialized_downstream_stages_stale(self) -> None:
        plan = self.service.plan_iteration(
            IterationRequest(
                run_id=self.review_run_id,
                base_stage_slug=STAGE_03.slug,
                scope_type="stage",
                scope_value=STAGE_03.slug,
                mode="redo",
            )
        )

        self.assertEqual(plan.preserved_stages, [STAGE_01.slug, STAGE_02.slug])
        self.assertEqual(plan.affected_stages, [stage.slug for stage in STAGES if stage.number >= 3])
        self.assertEqual(plan.stale_stages, [STAGE_04.slug, STAGE_05.slug])
        self.assertTrue(plan.reuses_current_run)
        self.assertIsNone(plan.branch_run_id)
        self.assertIn("Treat downstream stages as stale", plan.operator_brief)
        self.assertEqual(plan.reviewer_actions[0], "Inspect the selected stage summary before resuming the run.")

    def test_plan_iteration_branch_proposes_new_run_lineage(self) -> None:
        plan = self.service.plan_iteration(
            IterationRequest(
                run_id=self.writing_run_id,
                base_stage_slug=STAGE_07.slug,
                scope_type="file",
                scope_value="workspace/writing/sections/method.tex",
                mode="branch",
                user_feedback="Revise the method framing before packaging the paper.",
            )
        )

        self.assertEqual(plan.preserved_stages, [stage.slug for stage in STAGES if stage.number < 7])
        self.assertEqual(plan.affected_stages, [stage.slug for stage in STAGES if stage.number >= 7])
        self.assertEqual(plan.branch_run_id, f"{self.writing_run_id}-branch-{STAGE_07.slug}")
        self.assertFalse(plan.reuses_current_run)
        self.assertEqual(plan.stale_stages, [])
        self.assertIn("Revise the method framing", plan.user_feedback)
        self.assertIn("Create branch run id", plan.operator_brief)

    def _create_review_run(self, run_id: str) -> str:
        run_root = self.runs_dir / run_id
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        initialize_run_config(paths, model="sonnet", venue="neurips_2025")
        initialize_run_manifest(paths)
        write_text(paths.user_input, "Evaluate a staged review run.")

        write_text(paths.literature_dir / "survey_notes.md", "# Survey\n\n- Core evidence.\n")
        write_text(paths.data_dir / "dataset_manifest.json", json.dumps({"dataset": "digits"}))
        write_text(paths.results_dir / "results.json", json.dumps({"accuracy": 0.91}))
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG test figure")
        write_text(paths.writing_dir / "main.tex", "\\documentclass{article}\n\\begin{document}\nTest\n\\end{document}\n")
        write_text(paths.run_root / ".hidden.txt", "outside workspace")
        write_text(paths.workspace_root / ".hidden.txt", "hidden workspace file")
        write_text(
            paths.logs,
            (
                "=== 2026-04-09T10:10:10 | run_start ===\n"
                "Run root\n\n"
                "=== 2026-04-09T10:10:11 | 01_literature_survey approved ===\n"
                "Approved\n\n"
                "=== 2026-04-09T10:10:12 | 05_experimentation attempt 2 result ===\n"
                "Result ready\n"
            ),
        )
        write_artifact_index(paths)

        for stage in (STAGE_01, STAGE_02, STAGE_03, STAGE_04):
            write_text(paths.stage_file(stage), _stage_markdown(stage))
            mark_stage_approved_manifest(paths, stage, 1, [])

        write_text(paths.stage_file(STAGE_05), _stage_markdown(STAGE_05))
        mark_stage_human_review_manifest(paths, STAGE_05, 2, ["workspace/results/results.json"])
        return run_id

    def _create_markdown_report_run(self, run_id: str) -> str:
        run_root = self.runs_dir / run_id
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        initialize_run_config(paths, model="sonnet", venue="neurips_2025", output_format="markdown")
        initialize_run_manifest(paths)
        write_text(paths.user_input, "Evaluate a markdown report run.")
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(
            paths.report_file,
            "# Report\n\n## Results\n\nAccuracy 0.873.\n\n![Accuracy](images/accuracy.png)\n",
        )
        return run_id

    def _create_writing_run(self, run_id: str) -> str:
        run_root = self.runs_dir / run_id
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        initialize_run_config(paths, model="sonnet", venue="neurips_2025", output_format="latex")
        initialize_run_manifest(paths)
        write_text(paths.user_input, "Evaluate a writing branch run.")

        write_text(paths.writing_dir / "main.tex", "\\documentclass{article}\n\\begin{document}\n\\input{sections/method}\n\\end{document}\n")
        write_text(paths.writing_dir / "build.log", "latexmk -pdf main.tex\nOutput written on main.pdf\n")
        write_text(
            paths.logs,
            (
                "=== 2026-04-09T20:20:20 | run_start ===\n"
                "Run root\n\n"
                "=== 2026-04-09T20:22:20 | 07_writing approved ===\n"
                "Writing approved\n"
            ),
        )
        sections_dir = paths.writing_dir / "sections"
        sections_dir.mkdir(parents=True, exist_ok=True)
        write_text(sections_dir / "method.tex", "\\section{Method}\nThe operator loop.\n")
        (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4 writing test")

        for stage in STAGES:
            if stage.number > 7:
                break
            write_text(paths.stage_file(stage), _stage_markdown(stage))
            mark_stage_approved_manifest(paths, stage, 1, [])
        return run_id


def _stage_markdown(stage) -> str:
    return (
        f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
        "## Objective\n"
        "Test objective.\n\n"
        "## Previously Approved Stage Summaries\n"
        "_None yet._\n\n"
        "## What I Did\n"
        "Executed a test stage.\n\n"
        "## Key Results\n"
        "- Produced stable test artifacts.\n\n"
        "## Files Produced\n"
        "- `workspace/notes/test.md` - test artifact\n\n"
        "## Suggestions for Refinement\n"
        "1. Tighten scope.\n"
        "2. Strengthen evidence.\n"
        "3. Clarify risks.\n\n"
        "## Your Options\n"
        "1. Use suggestion 1\n"
        "2. Use suggestion 2\n"
        "3. Use suggestion 3\n"
        "4. Refine with your own feedback\n"
        "5. Approve and continue\n"
        "6. Abort\n"
    )


def _collect_tree_paths(node) -> list[str]:
    paths = [node.rel_path]
    for child in node.children:
        paths.extend(_collect_tree_paths(child))
    return paths


if __name__ == "__main__":
    unittest.main()
