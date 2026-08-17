"""A fresh run can be told where to start, and only one thing may tell it.

``resume_run`` has always taken a ``start_stage`` and ``run`` has not, so the only way to
begin a *new* run above Stage 01 was ``--project-root``: a bootstrap scan whose output is
a recommended entry stage. That is the wrong instrument for a caller who already knows
where it wants to start, and it costs an operator invocation to be told something the
caller could have said.

The caller that needs it is a written-examination benchmark run under a no-browsing
protocol. Stage 01 is the literature survey; its evidence ledger is satisfied by
citations and never checks that one exists, so a run that cannot search can only pass it
by inventing them -- and the grading rubric awards points for specific values from the
literature, where an invented one displaces a real one. Not running the stage is honest.

The refusal is the other half. ``start_stage`` and ``project_root`` are two answers to
one question, and before the guard the resolution was whichever assignment came last in
the method body: the bootstrap's recommendation would have silently overwritten the
caller's stage with no line anywhere saying so.

The tests below also walk a real fake-operator run from Stage 02, because the interesting
question is not whether the walk starts in the right place but whether everything hanging
off it survives stages that never ran: the manifest keeps them pending rather than
inventing a status, the graph census is written from a path that begins mid-graph, and
the figure-plan stamp -- which fires on Stage 03's approval and again from Stage 06
onward -- does nothing rather than stamping a plan that does not exist.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.approval_agent import AutomatedReviewer
from src.manager import ResearchManager
from src.manifest import load_run_manifest
from src.operator import ClaudeOperator
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, read_text, resolve_stage


REPO_ROOT = Path(__file__).resolve().parent.parent

STAGE_02 = resolve_stage("02_hypothesis_generation")
STAGE_06 = resolve_stage("06_analysis")


def _manager(runs_dir: Path, *, stream: io.StringIO):
    ui = TerminalUI(output_stream=stream, interactive=False)
    operator = ClaudeOperator(
        model="sonnet", fake_mode=True, ui=ui, output_stream=stream, stage_timeout=60
    )
    reviewer = AutomatedReviewer(
        "claude", model="sonnet", fake_mode=True, ui=ui, stage_timeout=60, unattended=True
    )
    return ResearchManager(
        project_root=REPO_ROOT,
        runs_dir=runs_dir,
        operator=operator,
        ui=ui,
        output_stream=stream,
        reviewer=reviewer,
        approval_mode="agent",
        unattended=True,
        max_auto_skips=0,
    )


class TheStagePopulationStartsWhereItIsToldTest(unittest.TestCase):
    """``_select_stages_for_run`` is the one place both entry points converge."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.stream = io.StringIO()
        self.manager = _manager(Path(self._tmp.name) / "runs", stream=self.stream)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")

    def test_a_start_stage_drops_everything_before_it(self) -> None:
        selected = self.manager._select_stages_for_run(self.paths, STAGE_02)
        self.assertEqual(selected[0].slug, "02_hypothesis_generation")
        self.assertNotIn("01_literature_survey", [stage.slug for stage in selected])

    def test_it_still_stops_where_the_final_stage_says(self) -> None:
        self.manager._final_stage = STAGE_06
        selected = self.manager._select_stages_for_run(self.paths, STAGE_02)
        self.assertEqual(
            [stage.slug for stage in selected],
            [stage.slug for stage in STAGES if 2 <= stage.number <= 6],
        )

    def test_a_start_stage_equal_to_the_final_stage_selects_exactly_one(self) -> None:
        self.manager._final_stage = STAGE_02
        selected = self.manager._select_stages_for_run(self.paths, STAGE_02)
        self.assertEqual([stage.slug for stage in selected], ["02_hypothesis_generation"])

    def test_without_one_the_population_is_every_unsettled_stage(self) -> None:
        """Control. The three above are only meaningful if the default is different."""
        from src.utils import ensure_run_layout

        ensure_run_layout(self.paths)
        selected = self.manager._select_stages_for_run(self.paths, None)
        self.assertEqual(selected[0].slug, "01_literature_survey")
        self.assertEqual(len(selected), len(STAGES))


class TwoAnswersToOneQuestionAreRefusedTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_dir = Path(self._tmp.name) / "runs"
        self.stream = io.StringIO()
        self.manager = _manager(self.runs_dir, stream=self.stream)

    def test_passing_both_start_mechanisms_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self.manager.run(
                "goal",
                skip_intake=True,
                start_stage=STAGE_02,
                project_root=Path(self._tmp.name),
            )
        message = str(caught.exception)
        self.assertIn("start_stage", message)
        self.assertIn("project_root", message)
        self.assertIn("02_hypothesis_generation", message)

    def test_the_refusal_happens_before_anything_is_created(self) -> None:
        """A half-built run directory is worse than the refusal: the next reader finds a
        run with a manifest, no stages and no record of why."""
        with self.assertRaises(ValueError):
            self.manager.run(
                "goal",
                skip_intake=True,
                start_stage=STAGE_02,
                project_root=Path(self._tmp.name),
            )
        self.assertFalse(self.runs_dir.exists() and any(self.runs_dir.iterdir()))

    def test_either_one_alone_is_accepted(self) -> None:
        """Control: the refusal is about the pair, not about either argument.

        The walk is stubbed out because what is under test is the guard, and running two
        more fake pipelines to learn nothing about it is a minute of CI.
        """
        for kwargs in ({"start_stage": STAGE_02}, {"project_root": Path(self._tmp.name)}):
            with self.subTest(passed=sorted(kwargs)):
                manager = _manager(self.runs_dir, stream=self.stream)
                with patch.object(ResearchManager, "_run_from_paths", return_value=True), \
                     patch.object(
                         ResearchManager, "_run_project_bootstrap", return_value=STAGE_06
                     ):
                    self.assertTrue(manager.run("goal", skip_intake=True, **kwargs))

    def test_the_caller_and_the_bootstrap_reach_the_walk_the_same_way(self) -> None:
        """Both sources feed one argument, so neither can grow its own walk semantics."""
        seen: list[object] = []

        def _capture(self, paths, start_stage=None):  # noqa: ANN001
            seen.append(start_stage)
            return True

        with patch.object(ResearchManager, "_run_from_paths", _capture), \
             patch.object(ResearchManager, "_run_project_bootstrap", return_value=STAGE_06):
            _manager(self.runs_dir, stream=self.stream).run(
                "goal", skip_intake=True, start_stage=STAGE_02
            )
            _manager(self.runs_dir, stream=self.stream).run(
                "goal", skip_intake=True, project_root=Path(self._tmp.name)
            )
            _manager(self.runs_dir, stream=self.stream).run("goal", skip_intake=True)
        self.assertEqual(seen, [STAGE_02, STAGE_06, None])


class AWalkThatBeginsAtStageTwoTest(unittest.TestCase):
    """A real fake-operator run, because the question is what the run *records*."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        runs_dir = Path(cls._tmp.name) / "runs"
        cls.stream = io.StringIO()
        manager = _manager(runs_dir, stream=cls.stream)
        cls.completed = manager.run(
            "A written examination question with no dataset and nothing to search.",
            skip_intake=True,
            output_format="markdown",
            start_stage=STAGE_02,
            final_stage=STAGE_02,
        )
        cls.auto_skipped = list(manager.auto_skipped_stages)
        roots = sorted(path for path in runs_dir.iterdir() if path.is_dir())
        assert len(roots) == 1, roots
        cls.paths = build_run_paths(roots[0])
        manifest = load_run_manifest(cls.paths.run_manifest)
        assert manifest is not None
        cls.manifest = manifest
        cls.log_text = read_text(cls.paths.logs)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_run_completes(self) -> None:
        self.assertTrue(self.completed, msg=self.stream.getvalue()[-3000:])

    def test_stage_two_ran_and_was_approved(self) -> None:
        entry = next(e for e in self.manifest.stages if e.slug == "02_hypothesis_generation")
        self.assertTrue(entry.settled)
        self.assertEqual(entry.status, "approved")

    def test_stage_one_never_ran(self) -> None:
        entry = next(e for e in self.manifest.stages if e.slug == "01_literature_survey")
        self.assertFalse(entry.settled)
        self.assertEqual(entry.status, "pending")

    def test_the_skipped_stage_is_pending_rather_than_auto_skipped(self) -> None:
        """`auto_skipped_stages` is the run's record of gates it gave up on. A stage the
        caller chose not to run is not one of those, and putting it there would make a
        deliberate entry point indistinguishable from an exhausted retry budget."""
        self.assertEqual(self.auto_skipped, [])

    def test_the_graph_census_was_written_from_a_path_that_starts_mid_graph(self) -> None:
        """`_record_block_census` returns early on an empty path, which is how a walk
        that never entered a node looks. This one entered one."""
        self.assertIn("route_census", self.log_text)

    def test_the_figure_plan_was_not_stamped(self) -> None:
        """Stage 03 declares the plan and Stage 03 never ran. The stamp hook fires on
        Stage 03's approval and again while preparing every stage from 06 onward, and on
        a run with no plan on disk it has to do nothing rather than declare an empty
        one -- a `report_plan declared` line here would be a claim about a document that
        does not exist."""
        self.assertNotIn("report_plan declared", self.log_text)
        self.assertNotIn("report_plan amended", self.log_text)

    def test_the_operator_was_told_the_run_starts_here(self) -> None:
        """A run with no literature survey because it was told not to and one with none
        because the stage failed look identical on disk."""
        self.assertIn("Starting at", self.stream.getvalue())

    def test_only_the_selected_stage_produced_a_stage_file(self) -> None:
        settled = [entry.slug for entry in self.manifest.stages if entry.settled]
        self.assertEqual(settled, ["02_hypothesis_generation"])


class TheDefaultPathIsUnchangedTest(unittest.TestCase):
    """Control for the class above: the same harness, with no start stage, runs Stage 01."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        runs_dir = Path(cls._tmp.name) / "runs"
        cls.stream = io.StringIO()
        manager = _manager(runs_dir, stream=cls.stream)
        cls.completed = manager.run(
            "A written examination question with no dataset and nothing to search.",
            skip_intake=True,
            output_format="markdown",
            final_stage=STAGE_02,
        )
        roots = sorted(path for path in runs_dir.iterdir() if path.is_dir())
        assert len(roots) == 1, roots
        manifest = load_run_manifest(build_run_paths(roots[0]).run_manifest)
        assert manifest is not None
        cls.manifest = manifest

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_the_run_completes(self) -> None:
        self.assertTrue(self.completed, msg=self.stream.getvalue()[-3000:])

    def test_stage_one_ran(self) -> None:
        entry = next(e for e in self.manifest.stages if e.slug == "01_literature_survey")
        self.assertTrue(entry.settled)
        self.assertEqual(entry.status, "approved")

    def test_nothing_announced_a_restart_point(self) -> None:
        self.assertNotIn("Starting at", self.stream.getvalue())


if __name__ == "__main__":
    unittest.main()
