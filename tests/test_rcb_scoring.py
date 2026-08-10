"""What reaches the ResearchClawBench judge, and what must not.

The scorer attaches at most five agent images per checklist item, found by an unsorted
``rglob`` over ``outputs/`` and then ``report/``. Image items carry roughly 61% of the
benchmark's total weight, so which five survive is most of the score — and filesystem order
means naming cannot influence it. These tests pin the only lever there is: publishing no more
than the budget, and letting the report's own references choose them.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.prereg_support import HYPOTHESIS_ID, write_report_plan, write_validity_chain
from src.rcb import (
    JUDGE_IMAGE_SUFFIXES,
    build_benchmark_goal,
    build_fallback_report,
    collect_figures,
    collect_reference_resources,
    export_run,
    mirror_tree,
    reference_papers,
)
from src.utils import (
    FIXED_STAGE_OPTIONS,
    MAX_REPORT_FIGURES,
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    resolve_stage,
    validate_stage_artifacts,
    write_text,
)
from src.writing_manifest import generate_report_review


STAGE_07 = next(stage for stage in STAGES if stage.slug == "07_writing")
_PARAGRAPH = (
    "The estimated effect size is 0.42 (95% CI 0.31-0.53, n=2000) against a published 0.40. "
)


def _judge_visible_images(workspace: Path) -> list[Path]:
    """Verbatim reimplementation of the scorer's `_find_generated_images` + `[:5]`."""
    images: list[Path] = []
    for search_dir in (workspace / "outputs", workspace / "report"):
        if search_dir.exists():
            for ext in JUDGE_IMAGE_SUFFIXES:
                images.extend(search_dir.rglob(f"*{ext}"))
    return images


class FigureBudgetTests(unittest.TestCase):
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
        ensure_run_config(paths, model="sonnet", venue="neurips_2025", output_format="markdown")
        return paths, workspace

    def _report(self, *figures: str) -> str:
        body = "# Report\n\n## Results\n\n" + (_PARAGRAPH * 40) + "\n\n"
        for name in figures:
            body += f"![{name}](images/{name})\n\n"
        return body

    def test_images_in_results_never_reach_outputs(self) -> None:
        paths, workspace = self._run_and_workspace()
        (paths.results_dir / "metrics.json").write_text('{"acc": 0.87}')
        write_validity_chain(paths, evidence="results/metrics.json")
        (paths.results_dir / "loss_curve.png").write_bytes(b"\x89PNG junk")
        (paths.results_dir / "diagram.svg").write_bytes(b"<svg/>")
        (paths.report_images_dir / "main.png").write_bytes(b"\x89PNG main")
        write_text(paths.report_file, self._report("main.png"))

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        exported = sorted(p.name for p in (workspace / "outputs").rglob("*") if p.is_file())
        # The adjudication records travel with the results: a judge that can see
        # the numbers should also be able to see which hypothesis they settle.
        self.assertEqual(
            exported,
            [
                "experimental_protocol.json",
                "hypothesis_manifest.json",
                "hypothesis_outcomes.json",
                "metrics.json",
                "preregistration.json",
                "report_plan.json",
                "research_rounds.json",
            ],
        )
        # outputs/ is swept before report/, so an image there would take a judge slot.
        self.assertEqual(
            [p for p in _judge_visible_images(workspace) if p.parent.name == "outputs"], []
        )

    def test_a_png_a_stage_wrote_to_the_benchmark_outputs_takes_no_judge_slot(self) -> None:
        paths, workspace = self._run_and_workspace()
        # Withholding images from the outputs/ *mirror* is only half the defence: the goal
        # contract points every stage at <workspace>/outputs/ for derived data, so a stage
        # can write a plot there directly. The scorer drains outputs/ before report/, so
        # six of them take all five slots and the one figure the report argues with is
        # never seen — the planned figure set buys nothing without this prune.
        outputs = workspace / "outputs"
        (outputs / "diagnostics").mkdir(parents=True)
        for index in range(MAX_REPORT_FIGURES + 1):
            (outputs / f"diag_{index}.png").write_bytes(b"\x89PNG diag" + str(index).encode())
        (outputs / "diagnostics" / "nested.svg").write_bytes(b"<svg/>")
        (outputs / "table.json").write_text('{"rows": 3}')
        (paths.report_images_dir / "main.png").write_bytes(b"\x89PNG main")
        write_text(paths.report_file, self._report("main.png"))

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        # The scorer's own sweep order, and the five it would actually attach.
        visible = [p.name for p in _judge_visible_images(workspace)]
        self.assertIn("main.png", visible[:MAX_REPORT_FIGURES])
        self.assertEqual(visible, ["main.png"])
        # Derived data is what outputs/ is for. Only the images are pruned, including the
        # nested one: the prune has to reach everywhere the scorer's rglob does.
        self.assertTrue((outputs / "table.json").exists())

    def test_an_image_loose_or_nested_under_report_takes_no_judge_slot(self) -> None:
        """``report/images/`` is not the only place the scorer looks under ``report/``.

        The sweep is ``rglob`` over the whole ``report/`` tree, so a plot saved beside
        ``report.md`` or one directory deeper inside ``images/`` competes for the same five
        slots as a published figure — and both sort ahead of ``report/images/main.png`` in
        the walk. A prune that only reads ``images_dir.iterdir()`` leaves exactly those
        files, which is the same defect as leaving them in ``outputs/`` one directory over.
        """
        paths, workspace = self._run_and_workspace()
        for index in range(MAX_REPORT_FIGURES + 1):
            (workspace / "report" / f"loose_{index}.png").parent.mkdir(
                parents=True, exist_ok=True
            )
            (workspace / "report" / f"loose_{index}.png").write_bytes(
                b"\x89PNG loose" + str(index).encode()
            )
        nested = workspace / "report" / "images" / "panels"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / "panel.png").write_bytes(b"\x89PNG panel")
        (paths.report_images_dir / "main.png").write_bytes(b"\x89PNG main")
        write_text(paths.report_file, self._report("main.png"))

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual([p.name for p in _judge_visible_images(workspace)], ["main.png"])
        # report.md is not an image and is never touched by the prune.
        self.assertTrue((workspace / "report" / "report.md").is_file())

    def test_a_live_link_to_a_loose_report_image_is_not_pruned(self) -> None:
        """Breaking a live link is worse than overshooting, here as everywhere else.

        An agent that wrote its report at the benchmark path and linked
        ``![](figure1.png)`` beside it has a figure the judge can both read about and see.
        Deleting it would leave the prose promising a figure and the judge shown nothing —
        the most expensive defect in this deliverable.
        """
        paths, workspace = self._run_and_workspace()
        (workspace / "report").mkdir(parents=True, exist_ok=True)
        (workspace / "report" / "figure1.png").write_bytes(b"\x89PNG f1")
        (workspace / "report" / "orphan.png").write_bytes(b"\x89PNG orphan")
        (workspace / "report" / "report.md").write_text(
            "# Agent Report\n\n" + (_PARAGRAPH * 40) + "\n\n![Result](figure1.png)\n",
            encoding="utf-8",
        )

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "agent")
        self.assertEqual(
            sorted(p.name for p in _judge_visible_images(workspace)), ["figure1.png"]
        )

    def test_the_reports_own_figures_are_the_ones_the_judge_sees(self) -> None:
        paths, workspace = self._run_and_workspace()
        for name in ("stage6_a.png", "stage6_b.png", "stage6_c.png", "stage6_d.png"):
            (paths.figures_dir / name).write_bytes(b"\x89PNG " + name.encode())
        for name in ("fig1.png", "fig2.png", "fig3.png"):
            (paths.report_images_dir / name).write_bytes(b"\x89PNG " + name.encode())
        write_text(paths.report_file, self._report("fig1.png", "fig2.png", "fig3.png"))

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual(result.figures, ["fig1.png", "fig2.png", "fig3.png"])
        visible = {p.name for p in _judge_visible_images(workspace)}
        self.assertEqual(visible, {"fig1.png", "fig2.png", "fig3.png"})

    def test_nothing_is_truncated_by_the_judges_five_image_cap(self) -> None:
        paths, workspace = self._run_and_workspace()
        for index in range(12):
            (paths.figures_dir / f"plot_{index}.png").write_bytes(b"\x89PNG " + str(index).encode())
        (paths.report_images_dir / "summary.png").write_bytes(b"\x89PNG summary")
        write_text(paths.report_file, self._report("summary.png"))

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        found = _judge_visible_images(workspace)
        self.assertLessEqual(len(found), MAX_REPORT_FIGURES)
        self.assertEqual([p.name for p in found[:MAX_REPORT_FIGURES]], ["summary.png"])

    def test_a_stale_figure_at_the_benchmark_path_is_pruned(self) -> None:
        paths, workspace = self._run_and_workspace()
        stale = workspace / "report" / "images"
        stale.mkdir(parents=True, exist_ok=True)
        for index in range(7):
            (stale / f"old_{index}.png").write_bytes(b"\x89PNG old" + str(index).encode())
        (paths.report_images_dir / "current.png").write_bytes(b"\x89PNG current")
        write_text(paths.report_file, self._report("current.png"))

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        # Enforcing the budget on a list but not on disk would leave the scorer sweeping the
        # stale files anyway.
        self.assertEqual(sorted(p.name for p in stale.iterdir()), ["current.png"])

    def test_a_referenced_figure_is_never_pruned_even_over_budget(self) -> None:
        paths, workspace = self._run_and_workspace()
        names = [f"panel_{index}.png" for index in range(MAX_REPORT_FIGURES + 2)]
        for name in names:
            (paths.report_images_dir / name).write_bytes(b"\x89PNG " + name.encode())
        write_text(paths.report_file, self._report(*names))

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        # Breaking a live link is worse than overshooting; Stage 07's gate is what prevents
        # a markdown run from arriving here over budget in the first place.
        self.assertEqual(sorted(result.figures), sorted(names))

    def test_a_report_referencing_nothing_still_gets_figures(self) -> None:
        paths, workspace = self._run_and_workspace()
        for index in range(8):
            (paths.figures_dir / f"plot_{index}.png").write_bytes(b"\x89PNG " + str(index).encode())
        write_text(paths.stages_dir / "06_analysis.md", "# Stage 06\n\n## Key Results\n\n" + _PARAGRAPH * 40)

        result = export_run(paths=paths, workspace=workspace, pipeline_completed=False)

        self.assertEqual(result.report_source, "fallback")
        self.assertEqual(len(result.figures), MAX_REPORT_FIGURES)

    def test_mirror_tree_without_a_skip_list_still_copies_everything(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        src, dst = Path(tmp_dir.name) / "s", Path(tmp_dir.name) / "d"
        src.mkdir()
        (src / "a.png").write_bytes(b"x")
        (src / "b.json").write_text("{}")
        self.assertEqual(mirror_tree(src, dst), 2)


class FigureBudgetGateTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "task")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025", output_format="markdown")
        write_text(paths.data_dir / "d.json", "{}")
        write_text(paths.results_dir / "r.json", "{}")
        (paths.figures_dir / "f.png").write_bytes(b"\x89PNG")
        from src.experiment_manifest import write_experiment_manifest

        write_experiment_manifest(paths)
        return paths

    def _populate(self, paths, figure_count: int):
        import json

        names = [f"fig_{index}.png" for index in range(figure_count)]
        for name in names:
            (paths.report_images_dir / name).write_bytes(b"\x89PNG " + name.encode())
        body = "# Report\n\n## Results\n\n" + (_PARAGRAPH * 40) + "\n\n"
        for name in names:
            body += f"![{name}](images/{name})\n\n"
        write_text(paths.report_file, body)
        write_text(
            paths.artifacts_dir / "citation_verification.json",
            json.dumps(
                {
                    "overall_status": "pass",
                    "total_citations": 1,
                    "verified_citations": 1,
                    "unresolved_citations": 0,
                    "claim_coverage": [{"claim": "c", "citation_keys": ["k"]}],
                }
            ),
        )
        write_text(paths.artifacts_dir / "self_review.json", json.dumps({"overall_score": 8}))
        write_validity_chain(paths, evidence="results/metrics.json")
        # One planned slot, pointing at the first figure this fixture publishes, so the
        # Stage 07 coverage check sees a plan that was kept. Deliberately not one entry per
        # published figure: the budget tests here are about the ceiling, and an unplanned
        # published figure is a report_review issue rather than a refusal.
        write_report_plan(
            paths,
            figures=[
                {
                    "slot": 1,
                    "filename": names[0],
                    "supports": [HYPOTHESIS_ID],
                    "shows": (
                        "Held-out accuracy (%) against training steps for the treatment "
                        "and the baseline, five seeds, band = stderr."
                    ),
                    "if_supported": "the treatment's curve stays above the baseline's band",
                    "if_refuted": "the two curves overlap within their bands throughout",
                    "source_artifact": "results/r.json",
                    "dropped_because": "",
                }
            ],
        )
        generate_report_review(paths)

    def test_a_run_within_budget_passes(self) -> None:
        paths = self._paths()
        self._populate(paths, MAX_REPORT_FIGURES)
        self.assertEqual(validate_stage_artifacts(STAGE_07, paths), [])

    def test_one_figure_over_budget_fails_the_stage(self) -> None:
        paths = self._paths()
        self._populate(paths, MAX_REPORT_FIGURES + 1)
        problems = validate_stage_artifacts(STAGE_07, paths)
        self.assertTrue(any("only 5 reach the reviewer" in problem for problem in problems), problems)

    def test_the_review_artifact_names_the_overshoot(self) -> None:
        paths = self._paths()
        self._populate(paths, MAX_REPORT_FIGURES + 3)
        review = generate_report_review(paths)
        self.assertEqual(review["figure_budget"], MAX_REPORT_FIGURES)
        self.assertEqual(review["issue_counts"]["figures_over_budget"], 3)
        issue = next(i for i in review["issues"] if i["category"] == "figures_over_budget")
        self.assertEqual(issue["severity"], "critical")
        self.assertTrue(any("Cut 3 figure" in fix for fix in review["priority_fixes"]))


class ReferencePaperTests(unittest.TestCase):
    def _workspace(self, papers: list[str]):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        workspace = Path(tmp_dir.name) / "workspace"
        (workspace / "related_work").mkdir(parents=True)
        for name in papers:
            (workspace / "related_work" / name).write_bytes(b"%PDF-1.4 stub")
        return workspace

    def test_reference_papers_are_registered_as_literature_resources(self) -> None:
        workspace = self._workspace(["paper_000.pdf", "paper_001.pdf"])
        entries = collect_reference_resources(workspace)
        self.assertEqual(len(entries), 2)
        self.assertEqual({e.resource_type for e in entries}, {"pdf"})
        # PDFs must land in workspace/literature/, which is where Stage 01 looks.
        self.assertEqual({e.dest_dir for e in entries}, {"literature"})

    def test_a_workspace_without_reference_papers_is_not_an_error(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.assertEqual(collect_reference_resources(Path(tmp_dir.name)), [])
        self.assertEqual(reference_papers(Path(tmp_dir.name)), [])

    def test_the_goal_contract_names_each_reference_paper(self) -> None:
        workspace = self._workspace(["paper_000.pdf", "paper_001.pdf"])
        goal = build_benchmark_goal(workspace, "Reproduce the study.")
        self.assertIn("Reference Papers Supplied With This Task", goal)
        self.assertIn("related_work/paper_000.pdf", goal)
        self.assertIn("related_work/paper_001.pdf", goal)
        self.assertIn("Read them before searching the web", goal)

    def test_the_contract_says_so_plainly_when_there_are_none(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        goal = build_benchmark_goal(Path(tmp_dir.name), "Reproduce the study.")
        self.assertIn("No reference papers were supplied", goal)


class FinalStageTests(unittest.TestCase):
    def test_resolve_stage_accepts_slug_number_and_padded_number(self) -> None:
        for value in ("07_writing", "7", "07"):
            self.assertEqual(resolve_stage(value), STAGE_07, value)
        self.assertIsNone(resolve_stage(None))
        self.assertIsNone(resolve_stage("  "))
        with self.assertRaises(ValueError):
            resolve_stage("99_nope")

    def test_the_benchmark_adapter_stops_after_writing_by_default(self) -> None:
        import rcb_agent

        args = rcb_agent.parse_args(["--workspace", "."])
        self.assertEqual(resolve_stage(args.final_stage), STAGE_07)


class FallbackReportShapeTests(unittest.TestCase):
    def _paths_with_stage(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.memory, "# Approved Run Memory\n")
        write_text(
            paths.stages_dir / "06_analysis.md",
            "\n".join(
                [
                    "# Stage 06: Analysis",
                    "",
                    "## Objective",
                    "Quantify the anisotropy.",
                    "",
                    "## Previously Approved Stage Summaries",
                    "Stage 05 produced metrics.json.",
                    "",
                    "## Key Results",
                    "Amplitude A = 0.012 +/- 0.001 (n=7).",
                    "",
                    "## Decision Ledger",
                    "- **Locked Decisions**: least squares",
                    "",
                    "## Suggestions for Refinement",
                    "1. Add bootstrap CIs",
                    "",
                    "## Your Options",
                ]
                + FIXED_STAGE_OPTIONS
            ),
        )
        return paths

    def test_workflow_scaffolding_never_reaches_the_judge(self) -> None:
        paths = self._paths_with_stage()
        report = build_fallback_report(
            paths=paths, figures=[], pipeline_completed=False, auto_skipped_stages=["07_writing"]
        )
        for leak in (
            "Your Options",
            "Use suggestion 1",
            "Approve and continue",
            "Abort",
            "Previously Approved Stage Summaries",
            "Decision Ledger",
            "Suggestions for Refinement",
        ):
            self.assertNotIn(leak, report, leak)

    def test_the_research_content_survives_under_a_research_heading(self) -> None:
        paths = self._paths_with_stage()
        report = build_fallback_report(
            paths=paths, figures=[], pipeline_completed=True, auto_skipped_stages=[]
        )
        self.assertIn("## Analysis", report)
        self.assertIn("### Key Results", report)
        self.assertIn("Amplitude A = 0.012 +/- 0.001 (n=7).", report)
        self.assertNotIn("# Stage 06: Analysis", report)

    def test_an_incomplete_run_is_still_declared(self) -> None:
        paths = self._paths_with_stage()
        report = build_fallback_report(
            paths=paths, figures=[], pipeline_completed=False, auto_skipped_stages=["07_writing"]
        )
        self.assertIn("Incomplete run", report)
        self.assertIn("07_writing", report)

    def test_an_empty_run_still_produces_a_report(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.memory, "# Approved Run Memory\n")
        report = build_fallback_report(
            paths=paths, figures=["a.png"], pipeline_completed=False, auto_skipped_stages=[]
        )
        self.assertIn("# Research Report", report)
        self.assertIn("![a](images/a.png)", report)


class CollectFiguresUnitTests(unittest.TestCase):
    def test_reference_order_decides_which_figures_are_published(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        root = Path(tmp_dir.name)
        workspace = root / "workspace"
        workspace.mkdir()
        paths = build_run_paths(root / ".autor" / "run")
        ensure_run_layout(paths)
        for name in ("a.png", "b.png", "c.png", "d.png", "e.png", "f.png", "g.png"):
            (paths.figures_dir / name).write_bytes(b"\x89PNG " + name.encode())

        published = collect_figures(
            paths, workspace, report_text="![g](images/g.png)\n\n![b](images/b.png)\n"
        )

        self.assertEqual(published, ["b.png", "g.png"])


class OutputsPruneIsNotADataLossTest(unittest.TestCase):
    """The prune deletes; so it has to offer a slot before it deletes.

    Draining ``outputs/`` is right when there is a chosen figure to protect — a
    stray plot there is a slot stolen, not a slot added. It is wrong when there
    is nothing else: a run that wrote its only plots to the benchmark's
    ``outputs/``, following the goal contract's own instruction to keep that
    directory up to date, would reach the judge with an empty workspace, and an
    image the judge cannot see scores exactly what no research scores. So
    ``outputs/`` ranks last among the candidate sources rather than being
    excluded from them.
    """

    def _workspace(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        root = Path(tmp_dir.name)
        workspace = root / "workspace"
        workspace.mkdir()
        paths = build_run_paths(root / ".autor" / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Benchmark task")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025", output_format="markdown")
        (workspace / "outputs").mkdir()
        return paths, workspace

    def test_a_run_whose_only_images_are_in_outputs_still_reaches_the_judge(self) -> None:
        paths, workspace = self._workspace()
        for name in ("main_result.png", "ablation.png"):
            (workspace / "outputs" / name).write_bytes(b"\x89PNG " + name.encode())

        export_run(paths=paths, workspace=workspace, pipeline_completed=False)

        visible = sorted(p.name for p in _judge_visible_images(workspace))
        self.assertEqual(visible, ["ablation.png", "main_result.png"])

    def test_the_promotion_never_exceeds_the_budget(self) -> None:
        paths, workspace = self._workspace()
        for index in range(MAX_REPORT_FIGURES + 3):
            (workspace / "outputs" / f"p{index}.png").write_bytes(b"\x89PNG " + str(index).encode())

        export_run(paths=paths, workspace=workspace, pipeline_completed=False)

        self.assertEqual(len(_judge_visible_images(workspace)), MAX_REPORT_FIGURES)

    def test_an_outputs_plot_never_outranks_a_figure_the_report_argues_with(self) -> None:
        """The property the prune exists for, unchanged by ranking outputs last."""
        paths, workspace = self._workspace()
        for index in range(MAX_REPORT_FIGURES + 1):
            (workspace / "outputs" / f"diag_{index}.png").write_bytes(b"\x89PNG d" + str(index).encode())
        (paths.report_images_dir / "main.png").write_bytes(b"\x89PNG main")
        body = "# Report\n\n## Results\n\n" + (_PARAGRAPH * 40) + "\n\n![main](images/main.png)\n"
        write_text(paths.report_file, body)

        export_run(paths=paths, workspace=workspace, pipeline_completed=True)

        self.assertEqual([p.name for p in _judge_visible_images(workspace)], ["main.png"])


if __name__ == "__main__":
    unittest.main()
