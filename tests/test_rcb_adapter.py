from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

import rcb_agent
from src.utils import DEFAULT_STAGE_GRAPH
from src.rcb import (
    MIN_REPORT_CHARS,
    infer_task_id,
    write_run_meta,
    RCB_WORKSPACE_DIRS,
    ReportSynthesizer,
    build_benchmark_goal,
    build_fallback_report,
    collect_figures,
    emit_event,
    ensure_workspace_layout,
    export_run,
    latest_run_root,
    mirror_tree,
    resolve_instructions,
    runs_dir_for,
)
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    extract_fenced_task,
    goal_excerpt,
    read_text,
    validate_stage_artifacts,
    validate_stage_markdown,
    write_text,
)


PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "0557bfabd40000000049454e44ae426082"
)


def _long_report(marker: str) -> str:
    return f"# {marker}\n\n" + ("Substantive analysis text. " * 120)


class WorkspaceLayoutTest(unittest.TestCase):
    def test_layout_matches_the_harness_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            ensure_workspace_layout(workspace)
            for name in RCB_WORKSPACE_DIRS:
                self.assertTrue((workspace / name).is_dir(), name)


class BenchmarkGoalTest(unittest.TestCase):
    def test_goal_states_the_scored_deliverable_and_keeps_the_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            goal = build_benchmark_goal(workspace, "Estimate the glacier mass balance trend.")

            self.assertIn("Estimate the glacier mass balance trend.", goal)
            self.assertIn(f"{workspace}/report/report.md", goal)
            self.assertIn(f"{workspace}/report/images/", goal)
            self.assertIn(f"{workspace}/code/", goal)
            self.assertIn(f"{workspace}/outputs/", goal)
            self.assertIn("no human", goal.lower())
            self.assertIn("read-only", goal.lower())

    def test_a_prefix_reader_sees_the_task_and_not_only_the_contract(self) -> None:
        """The question survives every budget the goal is excerpted at.

        Four readers take a prefix of ``user_input.txt`` — the router at 2,500
        characters, the deliberation panel and the validity reviewer at 3,000, the
        report synthesizer at 8,000. While the task sat *after* the grading contract,
        and the contract grew past 7,600 characters, the first three saw none of the
        research question and the fourth saw 331 characters of it. This pins the
        ordering rather than any one call site, because the next section added to the
        contract is what would break it again.
        """
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp).resolve()
            question = "Recover the latent charges from energies and forces alone."
            task = f"## Role\n\nYou are a researcher.\n\n## Research Task\n\n{question}\n" + (
                "\n<!-- padding -->" * 400
            )
            goal = build_benchmark_goal(workspace, task)

            self.assertGreater(len(goal), 8000, "the contract is no longer long enough to test this")
            for budget in (2500, 3000, 8000):
                self.assertIn(question, goal_excerpt(goal, budget), f"lost at {budget} chars")

    def test_the_fenced_task_round_trips_out_of_the_goal(self) -> None:
        """The fence carries the research task, not the whole instruction sheet.

        This used to assert the sheet round-tripped whole, which is what handed the
        coverage gate `## Role` as a deliverable. Over the 40 shipped tasks that was
        58% of every run's requirement list.
        """
        with tempfile.TemporaryDirectory() as tmp:
            task = "## Role\n\nAnalyst.\n\n## Research Task\n\nFit the exclusion curve."
            goal = build_benchmark_goal(Path(tmp).resolve(), task)
            self.assertEqual(extract_fenced_task(goal), "Fit the exclusion curve.")
            # The agent still reads the part that is not fenced.
            self.assertIn("Analyst.", goal)

    def test_a_sheet_with_no_research_task_heading_round_trips_whole(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            task = "Fit the exclusion curve and report the bound."
            goal = build_benchmark_goal(Path(tmp).resolve(), task)
            self.assertEqual(extract_fenced_task(goal), task)

    def test_a_goal_nobody_fenced_is_returned_whole(self) -> None:
        plain = "Estimate the glacier mass balance trend."
        self.assertIsNone(extract_fenced_task(plain))
        self.assertEqual(goal_excerpt(plain, 2500), plain)


class ResolveInstructionsTest(unittest.TestCase):
    def test_literal_prompt_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "INSTRUCTIONS.md").write_text("from file", encoding="utf-8")
            self.assertEqual(
                resolve_instructions(prompt="from flag", prompt_file=None, workspace=workspace),
                "from flag",
            )

    def test_workspace_instructions_are_the_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / "INSTRUCTIONS.md").write_text("task text", encoding="utf-8")
            self.assertEqual(
                resolve_instructions(prompt=None, prompt_file=None, workspace=workspace),
                "task text",
            )

    def test_missing_instructions_are_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                resolve_instructions(prompt="   ", prompt_file=None, workspace=Path(tmp))


class ExportTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        ensure_workspace_layout(self.workspace)
        self.run_root = runs_dir_for(self.workspace) / "run_0001"
        self.paths = build_run_paths(self.run_root)
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "benchmark goal")
        write_text(self.paths.memory, "# Memory\n\n## Approved Stage Summaries\n\nStage 01 done.\n")


class MirrorAndFigureTest(ExportTestBase):
    def test_mirror_preserves_nested_layout_and_skips_caches(self) -> None:
        (self.paths.code_dir / "pkg" / "__pycache__").mkdir(parents=True)
        write_text(self.paths.code_dir / "analysis.py", "print(1)\n")
        write_text(self.paths.code_dir / "pkg" / "helper.py", "x = 1\n")
        (self.paths.code_dir / "pkg" / "__pycache__" / "helper.pyc").write_bytes(b"\x00")

        copied = mirror_tree(self.paths.code_dir, self.workspace / "code")

        self.assertEqual(copied, 2)
        self.assertTrue((self.workspace / "code" / "analysis.py").exists())
        self.assertTrue((self.workspace / "code" / "pkg" / "helper.py").exists())
        self.assertFalse((self.workspace / "code" / "pkg" / "__pycache__").exists())

    def test_a_file_that_is_already_its_own_target_does_not_end_the_run(self) -> None:
        """`export_run` is the last thing `rcb_agent.run` does, so this raised after the
        deliverable existed and turned a finished run into `status: failed`.

        Four workspaces on this box are in exactly that state -- all seven stages approved,
        a 43-46 KB report, and `exit_code 1` from `shutil.SameFileError` in here. Because
        `run_arm.py::_scoreable` requires `completed`, each became permanently unscoreable
        while its claim still blocked a retry.

        The agent's workspace reaches the run tree by symlink, and this filesystem has also
        handed two distinct directory entries the same `st_ino`, so `path.samefile(target)`
        answers True for files that are not the same file. Either way the copy is a no-op
        and must not be fatal.
        """
        write_text(self.paths.code_dir / "analysis.py", "print(1)\n")
        destination = self.workspace / "code"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "analysis.py").hardlink_to(self.paths.code_dir / "analysis.py")

        copied = mirror_tree(self.paths.code_dir, destination)

        self.assertEqual(copied, 1)
        self.assertEqual((destination / "analysis.py").read_text(), "print(1)\n")

    def test_a_symlinked_target_is_replaced_by_a_real_file(self) -> None:
        """Skipping instead of unlinking would archive a pointer into `.autor/`.

        The archive exists so the run's code survives the run tree; a symlink back into the
        tree it is archiving away from is worth nothing, and is the reason this unlinks
        rather than taking the cheaper `continue`.
        """
        write_text(self.paths.code_dir / "analysis.py", "print(1)\n")
        destination = self.workspace / "code"
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "analysis.py").symlink_to(self.paths.code_dir / "analysis.py")

        copied = mirror_tree(self.paths.code_dir, destination)

        self.assertEqual(copied, 1)
        self.assertFalse((destination / "analysis.py").is_symlink())
        self.assertEqual((destination / "analysis.py").read_text(), "print(1)\n")

    def test_figures_are_collected_as_report_relative_pngs(self) -> None:
        (self.paths.figures_dir / "main_result.png").write_bytes(PNG_BYTES)
        (self.paths.results_dir / "ignored.pdf").write_bytes(b"%PDF-1.4")

        figures = collect_figures(self.paths, self.workspace)

        self.assertEqual(figures, ["main_result.png"])
        self.assertTrue((self.workspace / "report" / "images" / "main_result.png").exists())
        self.assertFalse((self.workspace / "report" / "images" / "ignored.pdf").exists())

    def test_a_figure_already_in_the_report_is_not_duplicated(self) -> None:
        (self.workspace / "report" / "images" / "main_result.png").write_bytes(PNG_BYTES)
        (self.paths.figures_dir / "main_result.png").write_bytes(PNG_BYTES)

        figures = collect_figures(self.paths, self.workspace)

        self.assertEqual(figures, ["main_result.png"])

    def test_same_basename_in_two_source_dirs_is_qualified_not_clobbered(self) -> None:
        (self.paths.figures_dir / "fig1.png").write_bytes(PNG_BYTES)
        (self.paths.results_dir / "fig1.png").write_bytes(PNG_BYTES + b"\x00")

        figures = collect_figures(self.paths, self.workspace)

        self.assertEqual(len(figures), 2)
        self.assertIn("fig1.png", figures)
        self.assertIn("results_fig1.png", figures)


class ExportRunTest(ExportTestBase):
    def test_an_agent_written_report_is_kept_verbatim(self) -> None:
        report = self.workspace / "report" / "report.md"
        write_text(report, _long_report("Agent Report"))

        result = export_run(paths=self.paths, workspace=self.workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "agent")
        self.assertIn("Agent Report", read_text(report))

    def test_a_stub_report_is_replaced_by_the_fallback(self) -> None:
        write_text(self.workspace / "report" / "report.md", "# TODO\n")
        write_text(self.paths.stages_dir / "06_analysis.md", "# Stage 06\n\nThe trend is -0.42 m w.e./yr.\n")

        result = export_run(paths=self.paths, workspace=self.workspace, pipeline_completed=True)

        self.assertEqual(result.report_source, "fallback")
        self.assertIn("-0.42 m w.e./yr", read_text(result.report_path))

    def test_synthesis_is_used_when_it_returns_real_content(self) -> None:
        def synthesize(*, paths, workspace, figures):
            return _long_report("Synthesized Report")

        result = export_run(
            paths=self.paths,
            workspace=self.workspace,
            pipeline_completed=True,
            synthesize=synthesize,
        )

        self.assertEqual(result.report_source, "synthesized")
        self.assertIn("Synthesized Report", read_text(result.report_path))

    def test_a_thin_synthesis_falls_back_rather_than_shipping(self) -> None:
        def synthesize(*, paths, workspace, figures):
            return "# Report\n\nnot much here\n"

        write_text(self.paths.stages_dir / "06_analysis.md", "# Stage 06\n\nReal analysis content.\n")
        result = export_run(
            paths=self.paths,
            workspace=self.workspace,
            pipeline_completed=True,
            synthesize=synthesize,
        )

        self.assertEqual(result.report_source, "fallback")
        self.assertIn("Real analysis content.", read_text(result.report_path))

    def test_a_failed_pipeline_still_produces_every_deliverable(self) -> None:
        write_text(self.paths.code_dir / "analysis.py", "print(1)\n")
        write_text(self.paths.results_dir / "metrics.json", '{"rmse": 0.13}\n')
        (self.paths.figures_dir / "trend.png").write_bytes(PNG_BYTES)

        result = export_run(
            paths=self.paths,
            workspace=self.workspace,
            pipeline_completed=False,
            auto_skipped_stages=["05_experimentation"],
        )

        self.assertTrue(result.report_path.exists())
        self.assertEqual(result.code_files, 1)
        self.assertGreaterEqual(result.output_files, 1)
        self.assertEqual(result.figures, ["trend.png"])

        body = read_text(result.report_path)
        self.assertIn("Incomplete run", body)
        self.assertIn("05_experimentation", body)
        self.assertIn("![trend](images/trend.png)", body)


class FallbackReportTest(ExportTestBase):
    def test_figures_use_report_relative_paths_only(self) -> None:
        body = build_fallback_report(
            paths=self.paths,
            figures=["a.png", "b.png"],
            pipeline_completed=True,
            auto_skipped_stages=[],
        )
        self.assertIn("![a](images/a.png)", body)
        self.assertIn("![b](images/b.png)", body)
        self.assertNotIn(str(self.workspace), body)

    def test_draft_stage_files_are_excluded(self) -> None:
        write_text(self.paths.stages_dir / "01_literature_survey.md", "APPROVED CONTENT")
        write_text(self.paths.stages_dir / "01_literature_survey.tmp.md", "DRAFT CONTENT")

        body = build_fallback_report(
            paths=self.paths, figures=[], pipeline_completed=True, auto_skipped_stages=[]
        )

        self.assertIn("APPROVED CONTENT", body)
        self.assertNotIn("DRAFT CONTENT", body)

    def test_a_run_with_no_stages_still_yields_a_report(self) -> None:
        body = build_fallback_report(
            paths=self.paths, figures=[], pipeline_completed=False, auto_skipped_stages=[]
        )
        self.assertTrue(body.strip())
        self.assertIn("Incomplete run", body)


class ReportSynthesizerTest(ExportTestBase):
    def test_an_operator_without_the_invocation_seam_is_unsupported(self) -> None:
        self.assertFalse(ReportSynthesizer(object()).supported())

    def test_prompt_names_the_target_path_and_forbids_invention(self) -> None:
        prompt = ReportSynthesizer(object()).build_prompt(
            paths=self.paths, workspace=self.workspace, figures=["x.png"]
        )
        self.assertIn(str((self.workspace / "report" / "report.md").resolve()), prompt)
        self.assertIn("images/x.png", prompt)
        self.assertIn("Never invent", prompt)

    def test_an_operator_that_raises_yields_no_report(self) -> None:
        class ExplodingOperator:
            def _prepare_invocation(self, *args, **kwargs):
                raise RuntimeError("backend unavailable")

            def _run_streaming_command(self, **kwargs):  # pragma: no cover - never reached
                raise AssertionError("should not run")

        synthesizer = ReportSynthesizer(ExplodingOperator())
        self.assertTrue(synthesizer.supported())
        self.assertIsNone(synthesizer(paths=self.paths, workspace=self.workspace, figures=[]))

    def test_a_nonzero_exit_yields_no_report(self) -> None:
        class FailingOperator:
            def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
                return (["true"], paths.run_root, None)

            def _run_streaming_command(self, **kwargs):
                return (1, "", "boom", None, {})

        self.assertIsNone(
            ReportSynthesizer(FailingOperator())(
                paths=self.paths, workspace=self.workspace, figures=[]
            )
        )

    def test_a_successful_call_returns_what_the_operator_wrote(self) -> None:
        report_path = self.workspace / "report" / "report.md"

        class WritingOperator:
            def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
                return (["true"], paths.run_root, None)

            def _run_streaming_command(self, **kwargs):
                write_text(report_path, _long_report("Operator Report"))
                return (0, "", "", None, {})

        body = ReportSynthesizer(WritingOperator())(
            paths=self.paths, workspace=self.workspace, figures=[]
        )
        self.assertIsNotNone(body)
        self.assertIn("Operator Report", body)
        self.assertGreaterEqual(len(body), MIN_REPORT_CHARS)


class EventStreamTest(unittest.TestCase):
    def test_events_are_one_json_object_per_line(self) -> None:
        stream = io.StringIO()
        emit_event({"type": "system", "model": "sonnet"}, stream=stream)
        emit_event({"type": "result", "status": "completed"}, stream=stream)

        lines = stream.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["model"], "sonnet")
        self.assertEqual(json.loads(lines[1])["status"], "completed")


class LatestRunRootTest(unittest.TestCase):
    def test_no_runs_yields_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(latest_run_root(Path(tmp) / "missing"))

    def test_the_newest_run_directory_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runs = Path(tmp)
            for name in ("run_0001", "run_0002", "run_0003"):
                (runs / name).mkdir()
            self.assertEqual(latest_run_root(runs).name, "run_0003")


class CliContractTest(unittest.TestCase):
    def test_workspace_defaults_to_cwd_and_synthesis_is_on(self) -> None:
        args = rcb_agent.parse_args([])
        self.assertEqual(args.workspace, ".")
        self.assertFalse(args.no_synthesis)
        self.assertFalse(args.intake)
        self.assertEqual(args.operator, "claude")

    def test_harness_style_invocation_parses(self) -> None:
        args = rcb_agent.parse_args(
            ["--workspace", "/tmp/ws", "--prompt", "do the research", "--model", "opus"]
        )
        self.assertEqual(args.workspace, "/tmp/ws")
        self.assertEqual(args.prompt, "do the research")
        self.assertEqual(args.model, "opus")

    def test_a_missing_workspace_fails_before_any_backend_call(self) -> None:
        exit_code = rcb_agent.main(["--workspace", "/nonexistent/rcb/workspace"])
        self.assertEqual(exit_code, 1)

    def test_export_only_reexports_an_existing_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            ensure_workspace_layout(workspace)
            paths = build_run_paths(runs_dir_for(workspace) / "run_0001")
            ensure_run_layout(paths)
            write_text(paths.user_input, "goal")
            write_text(paths.memory, "# Memory\n")
            write_text(paths.stages_dir / "06_analysis.md", _long_report("Recovered analysis"))

            exit_code = rcb_agent.main(
                ["--workspace", str(workspace), "--export-only", "--no-synthesis"]
            )

            self.assertEqual(exit_code, 0)
            self.assertIn("Substantive analysis text.", read_text(workspace / "report" / "report.md"))

    def test_a_run_that_produced_nothing_exits_non_zero(self) -> None:
        """Eight benchmark runs reported `exit_code: 0, status: completed` over a stub.

        `BenchmarkResult.exit_code` tested `report_path.exists()`, and a 197-byte
        "No completed stage output was produced" report exists. So the batch log, the
        run metadata and the harness all recorded eight successes, and nothing surfaced
        the loss until the scoring pass thirteen hours later.
        """
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            ensure_workspace_layout(workspace)
            paths = build_run_paths(runs_dir_for(workspace) / "run_0001")
            ensure_run_layout(paths)
            write_text(paths.user_input, "goal")
            write_text(paths.memory, "# Memory\n")

            exit_code = rcb_agent.main(
                ["--workspace", str(workspace), "--export-only", "--no-synthesis"]
            )

            report = read_text(workspace / "report" / "report.md")
            self.assertIn("No completed stage output was produced", report)
            self.assertEqual(exit_code, 1)


class SkippedStageNamesTest(unittest.TestCase):
    def test_stage_slugs_used_in_reports_are_real_stages(self) -> None:
        slugs = {stage.slug for stage in STAGES}
        self.assertIn("05_experimentation", slugs)
        self.assertIn("07_writing", slugs)


if __name__ == "__main__":
    unittest.main()


class RunMetaTest(ExportTestBase):
    """`_meta.json` is what makes a directly-launched run scoreable and submittable."""

    def test_meta_has_every_field_the_leaderboard_importer_requires(self) -> None:
        # Mirrors import_leaderboard_only_runs.py's validation.
        path = write_run_meta(
            self.workspace,
            task_id="Physics_003",
            run_id="20260806_033337",
            status="completed",
            duration_seconds=1234,
            model="opus",
        )
        meta = json.loads(path.read_text(encoding="utf-8"))
        for key in ("task_id", "run_id", "timestamp", "status", "duration_seconds", "model", "agent_name"):
            self.assertIn(key, meta, key)
        self.assertEqual(meta["status"], "completed")
        self.assertEqual(meta["task_id"], "Physics_003")
        self.assertEqual(meta["duration_seconds"], 1234)
        self.assertEqual(meta["agent_name"], "AutoR")

    def test_existing_harness_fields_survive_an_update(self) -> None:
        (self.workspace / "_meta.json").write_text(
            json.dumps({"agent_cmd": "python3 rcb_agent.py", "agent_name": "AutoR", "status": "running"}),
            encoding="utf-8",
        )
        path = write_run_meta(
            self.workspace, task_id="Physics_003", run_id="r1",
            status="completed", duration_seconds=10, model="opus",
        )
        meta = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["agent_cmd"], "python3 rcb_agent.py")
        self.assertEqual(meta["status"], "completed")

    def test_corrupt_existing_meta_does_not_break_the_write(self) -> None:
        (self.workspace / "_meta.json").write_text("not json at all", encoding="utf-8")
        path = write_run_meta(
            self.workspace, task_id="T_000", run_id="r1",
            status="completed", duration_seconds=1, model="opus",
        )
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["task_id"], "T_000")

    def test_task_id_is_inferred_from_the_workspace_name(self) -> None:
        self.assertEqual(infer_task_id(Path("/x/Physics_003_20260806_033337")), "Physics_003")
        self.assertEqual(infer_task_id(Path("/x/Astronomy_000_20260319_184609")), "Astronomy_000")

    def test_a_workspace_not_named_by_the_harness_yields_no_task_id(self) -> None:
        self.assertIsNone(infer_task_id(Path("/x/my-scratch-dir")))
        self.assertIsNone(infer_task_id(Path("/x/Physics_003")))

    def test_a_run_with_no_report_is_recorded_as_failed(self) -> None:
        path = write_run_meta(
            self.workspace, task_id="T_000", run_id="r1",
            status="failed", duration_seconds=5, model="opus",
        )
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["status"], "failed")


class BenchmarkArtifactRootTest(unittest.TestCase):
    """A stage that writes where the benchmark contract told it to must still validate.

    The contract points stages at `<workspace>/outputs/` and `<workspace>/report/images/`,
    which live outside the run tree. Before extra roots existed, a compliant stage failed
    `Files Produced` validation and burned its whole retry budget on every task.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "Physics_003_20260806_034828"
        self.workspace.mkdir()
        ensure_workspace_layout(self.workspace)
        self.paths = build_run_paths(runs_dir_for(self.workspace) / "20260806_034835")
        ensure_run_layout(self.paths)

    def _markdown(self, listed: str) -> str:
        return (
            "# Stage 01: Literature Survey\n\n"
            "## Objective\no\n\n## Previously Approved Stage Summaries\nn\n\n"
            "## What I Did\nw\n\n## Key Results\nk\n\n"
            f"## Files Produced\n- `{listed}`\n\n"
            "## Decision Ledger\nOpen Questions: -\nLocked Decisions: -\n"
            "Assumptions: -\nRejected Alternatives: -\n\n"
            "## Suggestions for Refinement\n1. a\n2. b\n3. c\n\n"
            "## Your Options\n1. a\n2. b\n3. c\n4. d\n5. e\n6. f\n"
        )

    def _missing_file_problems(self, markdown, roots):
        return [
            p for p in validate_stage_markdown(
                markdown, stage=STAGES[0], paths=self.paths, artifact_roots=roots
            )
            if "references missing file" in p
        ]

    def test_a_benchmark_workspace_file_validates_when_the_root_is_supplied(self) -> None:
        (self.workspace / "outputs" / "metrics.csv").write_text("a,b\n", encoding="utf-8")
        markdown = self._markdown("outputs/metrics.csv")
        self.assertEqual(self._missing_file_problems(markdown, [self.workspace]), [])

    def test_the_same_file_fails_without_the_extra_root(self) -> None:
        """Proves the extra root is what fixes it, not something else in the fixture."""
        (self.workspace / "outputs" / "metrics.csv").write_text("a,b\n", encoding="utf-8")
        markdown = self._markdown("outputs/metrics.csv")
        self.assertEqual(len(self._missing_file_problems(markdown, None)), 1)

    def test_a_genuinely_missing_file_still_fails_with_the_root_supplied(self) -> None:
        """The extra root must not turn the gate off."""
        markdown = self._markdown("outputs/never_written.csv")
        self.assertEqual(len(self._missing_file_problems(markdown, [self.workspace])), 1)

    def test_run_tree_paths_still_validate(self) -> None:
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        markdown = self._markdown("workspace/code/run.py")
        self.assertEqual(self._missing_file_problems(markdown, [self.workspace]), [])

    def test_a_report_image_at_the_benchmark_path_validates(self) -> None:
        (self.workspace / "report" / "images" / "fig1.png").write_bytes(PNG_BYTES)
        markdown = self._markdown("report/images/fig1.png")
        self.assertEqual(self._missing_file_problems(markdown, [self.workspace]), [])


class BenchmarkArtifactDirTest(unittest.TestCase):
    """Stage gates must see artifacts written to the benchmark's output paths.

    Same root cause as the `Files Produced` bug: the benchmark contract points stages at
    `<workspace>/outputs/` and `<workspace>/report/images/`, outside the run tree. Without
    the extra directories a compliant stage looks like it produced nothing, and stages 03,
    05 and 06 burn their whole retry budget.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "Physics_003_20260806_043103"
        self.workspace.mkdir()
        ensure_workspace_layout(self.workspace)
        self.paths = build_run_paths(runs_dir_for(self.workspace) / "20260806_043110")
        ensure_run_layout(self.paths)
        self.dirs = {
            "data": [self.workspace / "outputs"],
            "results": [self.workspace / "outputs"],
            "figures": [self.workspace / "report" / "images"],
        }

    def _problems(self, stage_number: int, dirs):
        stage = next(s for s in STAGES if s.number == stage_number)
        return validate_stage_artifacts(stage, self.paths, dirs)

    def _has(self, problems, needle):
        return any(needle in p for p in problems)

    def test_stage_03_accepts_data_written_to_the_benchmark_outputs(self) -> None:
        (self.workspace / "outputs" / "profile.json").write_text('{"n": 1}', encoding="utf-8")
        self.assertFalse(self._has(self._problems(3, self.dirs), "machine-readable data artifacts"))

    def test_the_same_file_fails_without_the_extra_dirs(self) -> None:
        (self.workspace / "outputs" / "profile.json").write_text('{"n": 1}', encoding="utf-8")
        self.assertTrue(self._has(self._problems(3, None), "machine-readable data artifacts"))

    def test_stage_03_still_fails_when_nothing_was_produced(self) -> None:
        self.assertTrue(self._has(self._problems(3, self.dirs), "machine-readable data artifacts"))

    def test_stage_06_accepts_figures_at_the_benchmark_path(self) -> None:
        (self.workspace / "report" / "images" / "fig1.png").write_bytes(PNG_BYTES)
        self.assertFalse(self._has(self._problems(6, self.dirs), "figure artifacts"))

    def test_stage_06_still_fails_with_no_figures_anywhere(self) -> None:
        self.assertTrue(self._has(self._problems(6, self.dirs), "figure artifacts"))

    def test_the_benchmark_input_data_is_not_counted(self) -> None:
        """The gate proves the stage did work; read-only inputs must not satisfy it."""
        (self.workspace / "data").mkdir(exist_ok=True)
        (self.workspace / "data" / "given.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        self.assertTrue(self._has(self._problems(3, self.dirs), "machine-readable data artifacts"))

    def test_run_tree_artifacts_still_satisfy_the_gate(self) -> None:
        write_text(self.paths.data_dir / "derived.csv", "a,b\n1,2\n")
        self.assertFalse(self._has(self._problems(3, self.dirs), "machine-readable data artifacts"))


class ManagerArtifactDirWiringTest(unittest.TestCase):
    def test_the_manager_maps_roots_to_the_benchmark_output_paths(self) -> None:
        from src.manager import ResearchManager

        ws = Path("/tmp/ws")
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=Path("/tmp/runs"),
            operator=type("Op", (), {"model": "m", "backend_name": "claude"})(),
            artifact_roots=[ws],
        )
        self.assertEqual(manager.artifact_dirs["data"], [ws / "outputs"])
        self.assertEqual(manager.artifact_dirs["figures"], [ws / "report" / "images"])
        # The read-only benchmark input must never appear.
        self.assertNotIn(ws / "data", manager.artifact_dirs["data"])


class TheControlArmHasAFlagNowTest(unittest.TestCase):
    """`docs/framework.md` §6.7 owes an ablation and calls it "one flag".

    The flag existed on `main.py` and not here, so the benchmark entry point could only
    ever run the default. All 398 archived benchmark run configs read `adaptive`, and none
    of them chose it -- which is why "the control arm has still never been passed" was true
    and could not have been otherwise.
    """

    def test_the_default_is_still_adaptive(self) -> None:
        """The control on the change: adding the flag must not move the default arm."""
        self.assertEqual(rcb_agent.parse_args([]).stage_graph, DEFAULT_STAGE_GRAPH)
        self.assertEqual(DEFAULT_STAGE_GRAPH, "adaptive")

    def test_linear_is_selectable(self) -> None:
        self.assertEqual(
            rcb_agent.parse_args(["--stage-graph", "linear"]).stage_graph, "linear"
        )

    def test_an_unknown_topology_is_refused_rather_than_defaulted(self) -> None:
        with self.assertRaises(SystemExit):
            rcb_agent.parse_args(["--stage-graph", "spiral"])

    def test_the_manager_is_given_the_topology_the_flag_names(self) -> None:
        """Through the manager, because a flag argparse accepts and nothing reads is the
        shape `tests/test_cli_flags_are_read.py` exists for."""
        from src.manager import ResearchManager
        from src.stage_graph import StageGraph

        for name in ("linear", "adaptive"):
            with self.subTest(name):
                manager = ResearchManager(
                    project_root=Path(__file__).resolve().parent.parent,
                    runs_dir=Path("/tmp/runs"),
                    operator=type("Op", (), {"model": "m", "backend_name": "claude"})(),
                    stage_graph=StageGraph.named(name),
                )
                self.assertEqual(manager.stage_graph.name, name)

    def test_the_two_topologies_are_not_the_same_object(self) -> None:
        """The control on the control: if `named` returned one graph the arm would be a
        label on an identical run, which is the confound this experiment exists to avoid."""
        from src.stage_graph import StageGraph

        linear = StageGraph.named("linear")
        adaptive = StageGraph.named("adaptive")
        self.assertNotEqual(len(linear.edges), len(adaptive.edges))
        self.assertEqual(
            [edge for edge in linear.edges if edge.kind == "revisit"], [],
            "a linear topology with a backward edge is not a linear topology",
        )


class ExportOnlyMetadataTest(unittest.TestCase):
    """A recovered run must be as scoreable as a normal one, or recovery is half done.

    `--export-only` exists for the case where a run was killed rather than returning —
    exactly the case where `_meta.json` was never written. Without this the recovered
    workspace still reads `status: running`, and both `evaluation.score` and the
    leaderboard importer refuse it.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "Physics_003_20260806_052405"
        self.workspace.mkdir()
        ensure_workspace_layout(self.workspace)
        self.paths = build_run_paths(runs_dir_for(self.workspace) / "20260806_052441")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")
        write_text(self.paths.stages_dir / "06_analysis.md", "# Stage 06\n\n" + ("Real analysis. " * 150))

    def _meta(self) -> dict:
        return json.loads((self.workspace / "_meta.json").read_text(encoding="utf-8"))

    def test_a_recovered_run_is_marked_completed_not_running(self) -> None:
        (self.workspace / "_meta.json").write_text(
            json.dumps({"task_id": "Physics_003", "status": "running"}), encoding="utf-8"
        )
        self.assertEqual(rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"]), 0)
        meta = self._meta()
        self.assertEqual(meta["status"], "completed")
        self.assertTrue(meta.get("recovered"))
        self.assertEqual(meta["task_id"], "Physics_003")

    def test_the_original_duration_survives_recovery(self) -> None:
        """The run took hours; the export took seconds. Cost is derived from this."""
        (self.workspace / "_meta.json").write_text(
            json.dumps({"task_id": "Physics_003", "status": "running", "duration_seconds": 4321}),
            encoding="utf-8",
        )
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        self.assertEqual(self._meta()["duration_seconds"], 4321)

    def test_a_run_with_no_prior_meta_still_gets_one(self) -> None:
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        meta = self._meta()
        self.assertEqual(meta["task_id"], "Physics_003")
        self.assertIsNotNone(meta["duration_seconds"])

    def test_the_recovered_workspace_satisfies_the_leaderboard_importer(self) -> None:
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        meta = self._meta()
        for key in ("task_id", "run_id", "timestamp", "status", "duration_seconds"):
            self.assertIn(key, meta, key)
        self.assertEqual(meta["status"], "completed")


class RecoveredDurationTest(unittest.TestCase):
    """A run killed by a signal never recorded its duration; zero is the wrong answer.

    The leaderboard derives cost per task from duration, so a multi-hour run recovered
    as `duration_seconds: 0` is published as having cost nothing.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "Physics_003_20260806_052405"
        self.workspace.mkdir()
        ensure_workspace_layout(self.workspace)
        self.paths = build_run_paths(runs_dir_for(self.workspace) / "20260806_052441")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")
        write_text(self.paths.stages_dir / "06_analysis.md", "# Stage 06\n\n" + ("Analysis. " * 200))

    def _age_run_tree(self, seconds: int) -> None:
        import os

        first = self.paths.user_input
        now = os.path.getmtime(first)
        os.utime(first, (now - seconds, now - seconds))

    def _meta(self) -> dict:
        return json.loads((self.workspace / "_meta.json").read_text(encoding="utf-8"))

    def test_duration_is_recovered_from_the_run_tree_span(self) -> None:
        self._age_run_tree(4000)
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        self.assertGreater(self._meta()["duration_seconds"], 3000)

    def test_a_recorded_duration_still_wins_over_the_estimate(self) -> None:
        self._age_run_tree(4000)
        (self.workspace / "_meta.json").write_text(
            json.dumps({"task_id": "Physics_003", "status": "running", "duration_seconds": 777}),
            encoding="utf-8",
        )
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        self.assertEqual(self._meta()["duration_seconds"], 777)

    def test_a_recovered_run_is_never_reported_as_free(self) -> None:
        self._age_run_tree(4000)
        rcb_agent.main(["--workspace", str(self.workspace), "--export-only", "--no-synthesis"])
        self.assertNotEqual(self._meta()["duration_seconds"], 0)
