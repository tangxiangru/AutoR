"""Stage 07 in markdown mode: the deliverable is report/report.md, not a PDF.

The gates here are deliberately harsher than "a file exists". A benchmark judge reads the
report as text and is handed the image files separately, so a figure reference that does not
resolve costs the run twice: the prose promises evidence and the judge is shown none.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests.prereg_support import write_validity_chain
from src.experiment_manifest import write_experiment_manifest
from src.rcb import export_run
from src.diagram_gen import inject_diagram_into_markdown
from src.utils import (
    read_text,
    DEFAULT_OUTPUT_FORMAT,
    DEFAULT_VENUE,
    OUTPUT_FORMAT_CHOICES,
    OUTPUT_FORMAT_CLI_CHOICES,
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    extract_markdown_image_targets,
    load_prompt_template,
    load_run_config,
    resolve_output_format,
    selected_output_format,
    validate_markdown_report,
    validate_stage_artifacts,
    write_text,
)
from src.writing_manifest import (
    build_writing_manifest,
    format_manifest_for_prompt,
    generate_report_review,
    validate_report_review,
)


STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")
REPO_ROOT = Path(__file__).resolve().parent.parent

_PARAGRAPH = (
    "We evaluate the proposed estimator on the held-out split and report an accuracy of "
    "0.873 against a 0.812 logistic-regression baseline over 2,000 samples with five-fold "
    "cross-validation. "
)


def _report_body(figure_line: str = "![Held-out accuracy by fold.](images/accuracy.png)") -> str:
    return (
        "# Recovering the Published Effect\n\n"
        "## Abstract\n\n"
        f"{_PARAGRAPH}\n\n"
        "## Methodology\n\n"
        f"{_PARAGRAPH * 5}\n\n"
        "## Results\n\n"
        f"{_PARAGRAPH * 5}\n\n"
        f"{figure_line}\n\n"
        "## Discussion\n\n"
        f"{_PARAGRAPH * 5}\n\n"
        "## Limitations\n\n"
        f"{_PARAGRAPH}\n"
    )


class OutputFormatResolutionTests(unittest.TestCase):
    def test_markdown_is_the_default(self) -> None:
        self.assertEqual(DEFAULT_OUTPUT_FORMAT, "markdown")
        self.assertEqual(resolve_output_format(None), "markdown")
        self.assertEqual(resolve_output_format(""), "markdown")

    def test_aliases_resolve_to_canonical_keys(self) -> None:
        for value in ("md", "markdown", "MARKDOWN", " Md "):
            self.assertEqual(resolve_output_format(value), "markdown", value)
        for value in ("latex", "tex", "pdf", "LaTeX"):
            self.assertEqual(resolve_output_format(value), "latex", value)

    def test_unknown_value_falls_back_rather_than_raising(self) -> None:
        self.assertEqual(resolve_output_format("docx"), "markdown")

    def test_every_cli_choice_resolves(self) -> None:
        # The CLIs advertise a short list; it must stay a subset of what the resolver knows,
        # or --help would accept a value that silently becomes the default.
        for choice in OUTPUT_FORMAT_CLI_CHOICES:
            self.assertIn(resolve_output_format(choice), OUTPUT_FORMAT_CHOICES, choice)
        self.assertIn("markdown", OUTPUT_FORMAT_CLI_CHOICES)
        self.assertIn("latex", OUTPUT_FORMAT_CLI_CHOICES)


class RunConfigOutputFormatTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        return paths

    def test_new_run_defaults_to_markdown(self) -> None:
        paths = self._paths()
        config = ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE)
        self.assertEqual(config["output_format"], "markdown")
        self.assertEqual(selected_output_format(paths), "markdown")

    def test_selected_format_survives_a_reload(self) -> None:
        paths = self._paths()
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="latex")
        self.assertEqual(load_run_config(paths)["output_format"], "latex")
        self.assertEqual(selected_output_format(paths), "latex")

    def test_resume_without_an_override_preserves_the_stored_format(self) -> None:
        paths = self._paths()
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="latex")
        # A resume passes output_format=None, which must not silently reset the run to the default.
        config = ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format=None)
        self.assertEqual(config["output_format"], "latex")

    def test_a_config_written_before_this_field_existed_still_loads(self) -> None:
        paths = self._paths()
        write_text(paths.run_config, json.dumps({"model": "sonnet", "venue": DEFAULT_VENUE}))
        self.assertEqual(selected_output_format(paths), "markdown")

    def test_workspace_layout_creates_the_report_tree(self) -> None:
        paths = self._paths()
        self.assertTrue(paths.report_dir.is_dir())
        self.assertTrue(paths.report_images_dir.is_dir())
        self.assertEqual(paths.report_file.name, "report.md")
        self.assertEqual(
            paths.report_file.relative_to(paths.workspace_root).as_posix(), "report/report.md"
        )


class PromptTemplateSelectionTests(unittest.TestCase):
    def test_markdown_stage07_loads_the_markdown_variant(self) -> None:
        template = load_prompt_template(REPO_ROOT / "src" / "prompts", STAGE_07, output_format="markdown")
        self.assertIn("{{WORKSPACE_REPORT_FILE}}", template)
        self.assertIn("Do not write LaTeX", template)

    def test_latex_stage07_loads_the_original_template(self) -> None:
        template = load_prompt_template(REPO_ROOT / "src" / "prompts", STAGE_07, output_format="latex")
        self.assertIn("main.tex", template)
        self.assertNotIn("{{WORKSPACE_REPORT_FILE}}", template)

    def test_omitting_the_format_keeps_the_historical_latex_template(self) -> None:
        # load_prompt_template's own default must not silently switch a caller's stage prompt.
        self.assertEqual(
            load_prompt_template(REPO_ROOT / "src" / "prompts", STAGE_07),
            load_prompt_template(REPO_ROOT / "src" / "prompts", STAGE_07, output_format="latex"),
        )

    def test_stages_without_a_variant_fall_back_to_the_single_template(self) -> None:
        stage_06 = next(stage for stage in STAGES if stage.slug == "06_analysis")
        markdown = load_prompt_template(REPO_ROOT / "src" / "prompts", stage_06, output_format="markdown")
        latex = load_prompt_template(REPO_ROOT / "src" / "prompts", stage_06, output_format="latex")
        self.assertEqual(markdown, latex)


class MarkdownImageExtractionTests(unittest.TestCase):
    def test_extracts_markdown_and_html_images_in_document_order(self) -> None:
        text = (
            "![one](images/a.png)\n"
            '<img src="images/b.png" width="400">\n'
            '![three](images/c.png "A title")\n'
            "![four](<images/d e.png>)\n"
        )
        self.assertEqual(
            extract_markdown_image_targets(text),
            ["images/a.png", "images/b.png", "images/c.png", "images/d e.png"],
        )

    def test_a_plain_link_is_not_an_image(self) -> None:
        self.assertEqual(extract_markdown_image_targets("[not an image](images/a.png)"), [])


class MarkdownStage07GateTests(unittest.TestCase):
    def _build_paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Reproduce the published effect")
        write_text(paths.memory, "# Approved Run Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        write_text(paths.data_dir / "design.json", '{"task":"test"}')
        write_text(paths.results_dir / "metrics.json", '{"accuracy": 0.873}')
        write_validity_chain(paths, evidence="results/metrics.json")
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")
        write_experiment_manifest(paths)
        return paths

    def _populate_valid_outputs(self, paths, figure_line: str | None = None) -> None:
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")
        write_text(paths.report_file, _report_body() if figure_line is None else _report_body(figure_line))
        write_text(
            paths.artifacts_dir / "citation_verification.json",
            json.dumps(
                {
                    "overall_status": "pass",
                    "total_citations": 1,
                    "verified_citations": 1,
                    "unresolved_citations": 0,
                    "claim_coverage": [{"claim": "Headline accuracy", "citation_keys": ["ref2024"]}],
                }
            ),
        )
        write_text(
            paths.artifacts_dir / "self_review.json",
            json.dumps({"overall_score": 8.5, "final_verdict": "ready", "rounds": 1}),
        )

        from src.deliverables import COVERAGE_FILENAME, demanding_sentences

        _statement = read_text(paths.user_input)
        write_text(
            paths.artifacts_dir / COVERAGE_FILENAME,
            json.dumps({"deliverables": [
                {"task_quote": s, "addressed": False, "reason": "fixture does no research."}
                for s in demanding_sentences(_statement)
            ] or [{"task_quote": " ".join(_statement.split())[:120] or "goal",
                   "addressed": False, "reason": "fixture does no research."}]}),
        )
        generate_report_review(paths)

    def test_a_complete_markdown_package_passes(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_latex_artifacts_are_not_required_in_markdown_mode(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        problems = " ".join(validate_stage_artifacts(STAGE_07, paths))
        for latex_only in ("main.tex", "compiled PDF", "build_log.txt", ".bib", "layout_review.json"):
            self.assertNotIn(latex_only, problems)

    def test_a_missing_report_fails(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        paths.report_file.unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("report/report.md" in problem for problem in problems), problems)

    def test_a_stub_report_fails(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        write_text(paths.report_file, "# Report\n\n![a](images/accuracy.png)\n")
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("characters" in problem for problem in problems), problems)

    def test_a_report_with_no_figures_fails(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        write_text(paths.report_file, _report_body(figure_line="No figure here."))
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("references no figures" in problem for problem in problems), problems)

    def test_a_figure_reference_that_does_not_resolve_fails(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths, figure_line="![Missing](images/nope.png)")
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("no such file exists" in problem for problem in problems), problems)

    def test_an_absolute_figure_path_fails(self) -> None:
        paths = self._build_paths()
        absolute = (paths.report_images_dir / "accuracy.png").resolve()
        self._populate_valid_outputs(paths, figure_line=f"![Absolute]({absolute})")
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("not a report-relative path" in problem for problem in problems), problems)

    def test_a_figure_the_viewer_cannot_render_fails(self) -> None:
        paths = self._build_paths()
        (paths.report_images_dir / "accuracy.pdf").write_bytes(b"%PDF-1.4 not an image")
        self._populate_valid_outputs(paths, figure_line="![Vector](images/accuracy.pdf)")
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("cannot be rendered" in problem for problem in problems), problems)

    def test_a_report_with_placeholder_text_fails(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        write_text(paths.report_file, _report_body() + "\n\n## Conclusion\n\n[TODO: write this]\n")
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("placeholder" in problem for problem in problems), problems)

    def test_the_review_artifact_is_required(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        (paths.artifacts_dir / "report_review.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("report_review.json" in problem for problem in problems), problems)

    def test_the_citation_ledger_is_still_required(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        (paths.artifacts_dir / "citation_verification.json").unlink()
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("citation_verification.json" in problem for problem in problems), problems)

    def test_stage_08_still_enforces_the_stage_07_report(self) -> None:
        paths = self._build_paths()
        self._populate_valid_outputs(paths)
        paths.report_file.unlink()
        stage_08 = next(stage for stage in STAGES if stage.slug == "08_dissemination")
        problems = validate_stage_artifacts(stage_08, paths)
        self.assertTrue(any("report/report.md" in problem for problem in problems), problems)


class ReportReviewTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Reproduce the published effect")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        return paths

    def test_a_clean_report_reviews_clean(self) -> None:
        paths = self._paths()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())
        review = generate_report_review(paths)
        self.assertEqual(review["overall_status"], "clean")
        self.assertTrue(review["report_available"])
        self.assertEqual(review["referenced_image_count"], 1)
        self.assertEqual(review["issue_counts"]["total"], 0)
        self.assertEqual(validate_report_review(paths.artifacts_dir / "report_review.json"), [])

    def test_a_broken_link_is_reported_as_critical_with_evidence(self) -> None:
        paths = self._paths()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body(figure_line="![Gone](images/gone.png)"))
        review = generate_report_review(paths)
        self.assertEqual(review["overall_status"], "needs_attention")
        self.assertEqual(review["issue_counts"]["broken_image_links"], 1)
        broken = next(issue for issue in review["issues"] if issue["category"] == "broken_image_link")
        self.assertEqual(broken["severity"], "critical")
        self.assertEqual(broken["evidence"], ["images/gone.png"])

    def test_an_image_nobody_references_is_flagged_but_not_critical(self) -> None:
        paths = self._paths()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        (paths.report_images_dir / "orphan.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())
        review = generate_report_review(paths)
        self.assertEqual(review["issue_counts"]["unreferenced_images"], 1)
        orphan = next(issue for issue in review["issues"] if issue["category"] == "unreferenced_image")
        self.assertEqual(orphan["severity"], "minor")
        self.assertEqual(orphan["evidence"], ["orphan.png"])

    def test_a_missing_report_is_recorded_rather_than_crashing(self) -> None:
        paths = self._paths()
        review = generate_report_review(paths)
        self.assertFalse(review["report_available"])
        self.assertEqual(review["overall_status"], "needs_attention")
        self.assertEqual(validate_report_review(paths.artifacts_dir / "report_review.json"), [])

    def test_priority_fixes_are_never_empty(self) -> None:
        paths = self._paths()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())
        review = generate_report_review(paths)
        self.assertTrue(review["priority_fixes"])
        self.assertTrue(all(isinstance(fix, str) and fix.strip() for fix in review["priority_fixes"]))

    def test_the_writing_manifest_carries_the_report_review_in_markdown_mode(self) -> None:
        paths = self._paths()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body(figure_line="![Gone](images/gone.png)"))
        generate_report_review(paths)
        manifest = build_writing_manifest(paths)
        self.assertIn("report_review", manifest)
        self.assertNotIn("layout_review", manifest)
        prompt_text = format_manifest_for_prompt(manifest)
        self.assertIn("Report Review", prompt_text)
        self.assertIn("needs_attention", prompt_text)

    def test_validate_report_review_rejects_a_malformed_artifact(self) -> None:
        paths = self._paths()
        write_text(paths.artifacts_dir / "report_review.json", json.dumps({"overall_status": ""}))
        problems = validate_report_review(paths.artifacts_dir / "report_review.json")
        self.assertTrue(any("overall_status" in problem for problem in problems))
        self.assertTrue(any("report_available" in problem for problem in problems))


class MarkdownDiagramInjectionTests(unittest.TestCase):
    def _report(self, body: str) -> Path:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "report.md"
        path.write_text(body, encoding="utf-8")
        return path

    def test_an_explicit_placeholder_wins(self) -> None:
        path = self._report(
            "# Title\n\n## Methodology\n\n<!-- METHOD_DIAGRAM_PLACEHOLDER -->\n\nProse.\n"
        )
        self.assertTrue(inject_diagram_into_markdown(path, "images/method_overview.png", "Overview"))
        text = path.read_text(encoding="utf-8")
        self.assertIn("![Overview](images/method_overview.png)", text)
        self.assertNotIn("METHOD_DIAGRAM_PLACEHOLDER", text)

    def test_without_a_placeholder_it_lands_under_the_method_heading(self) -> None:
        path = self._report("# Title\n\n## Introduction\n\nA.\n\n## Methodology\n\nB.\n\n## Results\n\nC.\n")
        self.assertTrue(inject_diagram_into_markdown(path, "images/method_overview.png", "Overview"))
        lines = path.read_text(encoding="utf-8").splitlines()
        heading = lines.index("## Methodology")
        figure = next(i for i, line in enumerate(lines) if line.startswith("![Overview]"))
        results = lines.index("## Results")
        self.assertLess(heading, figure)
        self.assertLess(figure, results)

    def test_a_report_with_no_method_heading_gets_the_figure_appended(self) -> None:
        path = self._report("# Title\n\n## Results\n\nC.\n")
        self.assertTrue(inject_diagram_into_markdown(path, "images/method_overview.png", "Overview"))
        self.assertTrue(path.read_text(encoding="utf-8").rstrip().endswith("![Overview](images/method_overview.png)"))

    def test_injection_is_idempotent(self) -> None:
        path = self._report("# Title\n\n## Method\n\nB.\n")
        self.assertTrue(inject_diagram_into_markdown(path, "images/method_overview.png", "Overview"))
        first = path.read_text(encoding="utf-8")
        self.assertFalse(inject_diagram_into_markdown(path, "images/method_overview.png", "Overview"))
        self.assertEqual(path.read_text(encoding="utf-8"), first)

    def test_a_missing_report_is_a_no_op(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        missing = Path(tmp_dir.name) / "absent.md"
        self.assertFalse(inject_diagram_into_markdown(missing, "images/x.png", "Overview"))
        self.assertFalse(missing.exists())


class BenchmarkExportTests(unittest.TestCase):
    """The run tree's markdown report must reach the benchmark workspace unaltered."""

    def _run_and_workspace(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        root = Path(tmp_dir.name)
        workspace = root / "workspace"
        workspace.mkdir()
        paths = build_run_paths(root / ".autor" / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Benchmark task")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        return paths, workspace

    def test_a_stage_written_report_is_promoted_verbatim(self) -> None:
        paths, workspace = self._run_and_workspace()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "stage")
        exported = (workspace / "report" / "report.md").read_text(encoding="utf-8")
        self.assertIn("![Held-out accuracy by fold.](images/accuracy.png)", exported)
        self.assertIn("accuracy.png", result.figures)
        # The reference resolves on the benchmark side too, which is the whole point.
        self.assertTrue((workspace / "report" / "images" / "accuracy.png").exists())

    def test_a_report_already_at_the_benchmark_path_still_wins(self) -> None:
        paths, workspace = self._run_and_workspace()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())
        (workspace / "report").mkdir(parents=True, exist_ok=True)
        write_text(workspace / "report" / "report.md", _report_body() + "\nWritten by the agent itself.\n")

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "agent")
        self.assertIn(
            "Written by the agent itself.",
            (workspace / "report" / "report.md").read_text(encoding="utf-8"),
        )

    def test_a_re_export_replaces_autors_own_earlier_fallback(self) -> None:
        paths, workspace = self._run_and_workspace()
        write_text(paths.stages_dir / "01_literature_survey.md", "# Stage 01\n\n" + ("Survey. " * 300))

        # First pass: nothing to promote, so AutoR assembles a fallback at the benchmark path.
        first = export_run(paths=paths, workspace=workspace, pipeline_completed=False)
        self.assertEqual(first.report_source, "fallback")

        # Stage 07 then finishes and writes the real deliverable into the run tree.
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())

        second = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        # AutoR's own earlier fallback must not masquerade as an agent-written report.
        self.assertEqual(second.report_source, "stage")
        self.assertIn(
            "Recovering the Published Effect",
            (workspace / "report" / "report.md").read_text(encoding="utf-8"),
        )

    def test_an_agent_edit_to_an_exported_report_is_preserved(self) -> None:
        paths, workspace = self._run_and_workspace()
        write_text(paths.stages_dir / "01_literature_survey.md", "# Stage 01\n\n" + ("Survey. " * 300))
        export_run(paths=paths, workspace=workspace, pipeline_completed=False)

        # Any change to the exported file breaks the digest, so it is treated as the agent's.
        report_path = workspace / "report" / "report.md"
        write_text(report_path, report_path.read_text(encoding="utf-8") + "\nHand-written addition.\n")
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "agent")
        self.assertIn("Hand-written addition.", report_path.read_text(encoding="utf-8"))

    def test_the_export_marker_stays_out_of_the_scored_directory(self) -> None:
        paths, workspace = self._run_and_workspace()
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body())

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        # The judge globs report/ for markdown and images; the marker must not land there.
        self.assertTrue((workspace / ".autor_export.json").exists())
        self.assertEqual(
            sorted(p.name for p in (workspace / "report").iterdir()),
            ["images", "report.md"],
        )

    def test_a_stub_run_tree_report_falls_through_to_the_deterministic_assembly(self) -> None:
        paths, workspace = self._run_and_workspace()
        write_text(paths.report_file, "# Report\n\nToo short to ship.\n")
        write_text(paths.stages_dir / "01_literature_survey.md", "# Stage 01\n\nApproved survey content.\n")

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=False)

        self.assertEqual(result.report_source, "fallback")
        self.assertIn("Approved survey content.", (workspace / "report" / "report.md").read_text(encoding="utf-8"))

    def test_run_tree_figures_keep_their_names_so_references_resolve(self) -> None:
        paths, workspace = self._run_and_workspace()
        # Same basename in two places: the one the report references must not be renamed.
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG report copy")
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG stage copy")
        write_text(paths.report_file, _report_body())

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        exported = workspace / "report" / "images" / "accuracy.png"
        self.assertEqual(exported.read_bytes(), b"\x89PNG report copy")


class ArtifactIndexReportFigureTests(unittest.TestCase):
    def test_report_images_are_indexed_as_figures(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        (paths.report_images_dir / "main_result.png").write_bytes(b"\x89PNG fake")
        (paths.figures_dir / "stage_plot.png").write_bytes(b"\x89PNG fake")

        manifest = build_writing_manifest(paths)
        rel_paths = {figure["rel_path"] for figure in manifest["figures"]}

        # Without this the Stage 07 prompt shows an empty inventory for the figures the
        # markdown report is required to embed.
        self.assertIn("report/images/main_result.png", rel_paths)
        self.assertIn("figures/stage_plot.png", rel_paths)


class MarkdownReportValidatorTests(unittest.TestCase):
    def test_validator_reports_every_broken_reference_not_just_the_first(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        (paths.report_images_dir / "ok.png").write_bytes(b"\x89PNG fake")
        (paths.report_images_dir / "accuracy.png").write_bytes(b"\x89PNG fake")
        write_text(
            paths.report_file,
            _report_body()
            + "\n![Gone one](images/one.png)\n\n![Gone two](images/two.png)\n\n![Fine](images/ok.png)\n",
        )
        problems = validate_markdown_report(paths)
        self.assertEqual(sum("no such file exists" in problem for problem in problems), 2)

    def test_a_reference_that_climbs_out_of_the_report_directory_is_rejected(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        (paths.report_images_dir / "ok.png").write_bytes(b"\x89PNG fake")
        # This file exists in the run tree, so a naive relative-path check would pass it —
        # but only report/ is exported, so the link is dead wherever the report is read.
        (paths.figures_dir / "stage_plot.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body(figure_line="![Escaped](../figures/stage_plot.png)"))

        problems = validate_markdown_report(paths)

        self.assertTrue(any("not a report-relative path" in problem for problem in problems), problems)

    def test_a_remote_image_url_is_rejected(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        ensure_run_config(paths, model="sonnet", venue=DEFAULT_VENUE, output_format="markdown")
        (paths.report_images_dir / "ok.png").write_bytes(b"\x89PNG fake")
        write_text(paths.report_file, _report_body(figure_line="![Remote](https://example.com/a.png)"))
        problems = validate_markdown_report(paths)
        self.assertTrue(any("not a report-relative path" in problem for problem in problems), problems)


if __name__ == "__main__":
    unittest.main()
