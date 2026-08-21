from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import rcb_agent
from src.utils import (
    BENCHMARK_MIN_REPORT_FIGURES,
    MAX_REPORT_FIGURES,
    MIN_REPORT_FIGURES,
    build_run_paths,
    initialize_run_config,
    ensure_run_config,
    ensure_run_layout,
    load_run_config,
    resolve_min_report_figures,
    validate_markdown_report,
    write_text,
)


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6360000002000100ffff0300000600"
    "0557bfabd40000000049454e44ae426082"
)


class ResolveFloorTest(unittest.TestCase):
    """The floor must stay inside the range the judge can actually see."""

    def test_the_default_is_one_so_ordinary_runs_are_unchanged(self) -> None:
        self.assertEqual(MIN_REPORT_FIGURES, 1)
        self.assertEqual(resolve_min_report_figures(None), 1)

    def test_a_floor_above_the_cap_is_clamped(self) -> None:
        """Demanding figures the scorer never looks at is busywork, not rigour."""
        self.assertEqual(resolve_min_report_figures(99), MAX_REPORT_FIGURES)

    def test_a_floor_below_one_is_lifted(self) -> None:
        for value in (0, -5):
            self.assertEqual(resolve_min_report_figures(value), 1)

    def test_junk_falls_back_to_the_default(self) -> None:
        for value in ("three", "", [], {}):
            self.assertEqual(resolve_min_report_figures(value), MIN_REPORT_FIGURES)

    def test_a_numeric_string_is_accepted(self) -> None:
        self.assertEqual(resolve_min_report_figures("3"), 3)

    def test_the_benchmark_floor_is_within_the_visible_range(self) -> None:
        self.assertGreater(BENCHMARK_MIN_REPORT_FIGURES, MIN_REPORT_FIGURES)
        self.assertLessEqual(BENCHMARK_MIN_REPORT_FIGURES, MAX_REPORT_FIGURES)


class GateTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")

    def _report(self, figures: int) -> None:
        body = ["# Report", "", "## Results", ""]
        for index in range(figures):
            (self.paths.report_images_dir / f"fig{index}.png").write_bytes(PNG)
            body.append(f"![Figure {index}](images/fig{index}.png)")
        body.append("Substantive analysis. " * 120)
        write_text(self.paths.report_file, "\n".join(body))

    def _figure_problems(self) -> list[str]:
        return [p for p in validate_markdown_report(self.paths) if "rendered figure" in p]

    def _configure(self, floor: int) -> None:
        initialize_run_config(self.paths, model="m", venue=None, min_report_figures=floor)

    def test_one_figure_passes_an_ordinary_run(self) -> None:
        self._configure(MIN_REPORT_FIGURES)
        self._report(1)
        self.assertEqual(self._figure_problems(), [])

    def test_one_figure_fails_a_benchmark_run(self) -> None:
        """Earth_000 shipped exactly this and forfeited two image criteria."""
        self._configure(BENCHMARK_MIN_REPORT_FIGURES)
        self._report(1)
        problems = self._figure_problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("at least 3", problems[0])

    def test_meeting_the_benchmark_floor_passes(self) -> None:
        self._configure(BENCHMARK_MIN_REPORT_FIGURES)
        self._report(BENCHMARK_MIN_REPORT_FIGURES)
        self.assertEqual(self._figure_problems(), [])

    def test_no_figures_fails_at_every_floor(self) -> None:
        for floor in (MIN_REPORT_FIGURES, BENCHMARK_MIN_REPORT_FIGURES):
            self._configure(floor)
            self._report(0)
            self.assertEqual(len(self._figure_problems()), 1, floor)

    def test_the_message_asks_for_different_questions_not_more_views(self) -> None:
        """A floor that reads as 'add pictures' is a padding instruction."""
        self._configure(BENCHMARK_MIN_REPORT_FIGURES)
        self._report(1)
        message = self._figure_problems()[0]
        self.assertIn("different", message)
        self.assertNotIn("as many", message)

    def test_the_ceiling_still_bites_above_the_floor(self) -> None:
        self._configure(BENCHMARK_MIN_REPORT_FIGURES)
        self._report(MAX_REPORT_FIGURES + 2)
        problems = " ".join(validate_markdown_report(self.paths))
        self.assertIn(f"above the ceiling of {MAX_REPORT_FIGURES}", problems)
        # The grader's window is a different number from the ceiling, and the refusal has
        # to name the one the agent can act on without misstating the other.
        self.assertIn("reach the reviewer", problems)


class ConfigPersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def test_the_floor_is_written_and_read_back(self) -> None:
        initialize_run_config(self.paths, model="m", venue=None, min_report_figures=3)
        self.assertEqual(load_run_config(self.paths)["min_report_figures"], 3)

    def test_it_survives_a_resume_like_every_other_setting(self) -> None:
        initialize_run_config(self.paths, model="m", venue=None, min_report_figures=3)
        self.assertEqual(ensure_run_config(self.paths)["min_report_figures"], 3)

    def test_an_explicit_value_overrides_the_recorded_one(self) -> None:
        initialize_run_config(self.paths, model="m", venue=None, min_report_figures=3)
        self.assertEqual(ensure_run_config(self.paths, min_report_figures=2)["min_report_figures"], 2)

    def test_a_config_predating_the_field_reads_as_the_default(self) -> None:
        initialize_run_config(self.paths, model="m", venue=None)
        import json

        payload = json.loads(self.paths.run_config.read_text(encoding="utf-8"))
        payload.pop("min_report_figures", None)
        self.paths.run_config.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(load_run_config(self.paths)["min_report_figures"], MIN_REPORT_FIGURES)


class BenchmarkAdapterTest(unittest.TestCase):
    """The adapter raises the floor above AutoR's ordinary one, and still can.

    This asserted the literal source text `min_report_figures=BENCHMARK_MIN_REPORT_FIGURES`
    until the floor became an argument. The invariant it was protecting is behavioural --
    *a benchmark run that was not told otherwise gets the benchmark floor, not the ordinary
    one* -- so it is now tested as behaviour, which also lets the argument exist.
    """

    def test_a_run_that_asks_for_nothing_gets_the_benchmark_floor(self) -> None:
        self.assertEqual(rcb_agent.benchmark_figure_floor(None), BENCHMARK_MIN_REPORT_FIGURES)
        self.assertGreater(BENCHMARK_MIN_REPORT_FIGURES, MIN_REPORT_FIGURES)

    def test_a_caller_can_raise_it(self) -> None:
        self.assertEqual(rcb_agent.benchmark_figure_floor(15), 15)

    def test_a_caller_can_lower_it_and_the_clamp_still_holds(self) -> None:
        """Lowering is allowed here and clamped downstream; the gate must not vanish."""
        self.assertEqual(resolve_min_report_figures(rcb_agent.benchmark_figure_floor(0)), 1)


if __name__ == "__main__":
    unittest.main()


class TheFigureFloorMustBeSettableTest(unittest.TestCase):
    """The floor existed, was read as a hard gate, and could not be moved.

    `min_report_figures` is written into `run_config.json`, clamped by
    `resolve_min_report_figures`, and read back by `validate_markdown_report` as a hard
    gate on the count of distinct figures in `report/images/`. `rcb_agent.py` pinned it at
    `BENCHMARK_MIN_REPORT_FIGURES` = 3 with no way to say otherwise, and the README said so
    outright: *"a `run_config.json` field with no CLI flag"*.

    Three is far below where runs actually land. Measured over 541 scored runs with task and
    arm fixed effects, a published figure is worth about +0.79 benchmark points, and 423 of
    those runs published fewer than the `MAX_REPORT_FIGURES` the judge is handed — median
    twelve. The gate at 3 has never fired against a real run. Making it an argument is what
    turns that observation into an experiment somebody can run.
    """

    def test_the_flag_exists_and_defaults_to_the_benchmark_floor(self) -> None:
        args = rcb_agent.parse_args(["--workspace", "/tmp/x", "--prompt", "/tmp/p"])
        self.assertIsNone(args.min_report_figures)

    def test_the_flag_parses_an_integer(self) -> None:
        args = rcb_agent.parse_args(
            ["--workspace", "/tmp/x", "--prompt", "/tmp/p", "--min-report-figures", "15"]
        )
        self.assertEqual(args.min_report_figures, 15)

    def test_the_clamp_admits_the_whole_window_the_judge_sees(self) -> None:
        """A floor of 15 has to survive the clamp, or the arm cannot be run at all.

        `resolve_min_report_figures` clamps to `[1, MAX_REPORT_FIGURES]`. The README and
        `docs/run-artifacts.md` both described that ceiling as 5, which was true when
        `MAX_REPORT_FIGURES` was 5 and has been wrong since it became 15 — a stale bound is
        how an arm gets configured to something it cannot reach.
        """
        self.assertEqual(MAX_REPORT_FIGURES, 15)
        self.assertEqual(resolve_min_report_figures(MAX_REPORT_FIGURES), MAX_REPORT_FIGURES)
        self.assertEqual(resolve_min_report_figures(MAX_REPORT_FIGURES + 1), MAX_REPORT_FIGURES)

    def test_a_floor_of_zero_or_nonsense_still_falls_back_rather_than_failing(self) -> None:
        for value in (0, -3, "", "three", None):
            with self.subTest(value=value):
                self.assertGreaterEqual(resolve_min_report_figures(value), 1)
