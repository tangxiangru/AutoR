from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        self.assertTrue(any("only" in p and "reach the reviewer" in p
                            for p in validate_markdown_report(self.paths)))


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
    def test_the_adapter_raises_the_floor(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "rcb_agent.py").read_text(encoding="utf-8")
        self.assertIn("min_report_figures=BENCHMARK_MIN_REPORT_FIGURES", source)


if __name__ == "__main__":
    unittest.main()
