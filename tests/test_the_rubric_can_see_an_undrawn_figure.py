"""A result reported as a number is not the same result shown.

Physics_000 reproduced a packing theory to 110 of 111 published closed-form values and
scored 18.7 against a bare agent's 53.4. All three of its graded criteria were image
criteria — 20, 28 and 5 — and its own Stage 07 champion scored **0.9969**, with
`deliverable_coverage` at 1.000 and the observation *"4/4 of the task's demands are spoken
to, 4/4 by something on disk"*.

Every word of that was true. The run answered all four demands, in prose, with numbers
that traced to files. What no criterion in this module could see was that the source's
figures had never been drawn — that a demand answered as a number and the same demand
shown as the object it names score identically here and forty points apart outside.

`source_figure_coverage` reads the inventory `draw-the-source-figure-panel-for-panel` asks
Stage 01 to write, and scores how much of it reached a published, referenced figure. It is
inert without that file, on purpose: the three criteria added to this module before it were
each landed with a live gradient and each turned out to have a route that bought score
without doing the work.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.rubric import (
    CRITERIA_BY_KEY,
    SOURCE_FIGURES_FILENAME,
    _score_source_figure_coverage,
    score_stage,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text

STAGE_03 = next(stage for stage in STAGES if stage.number == 3)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


class SourceFigureCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Reproduce the published figures.")

    def _inventory(self, *rows: dict) -> None:
        write_text(
            self.paths.notes_dir / SOURCE_FIGURES_FILENAME,
            json.dumps({"figures": list(rows)}),
        )

    def _publish(self, *names: str) -> None:
        for name in names:
            write_text(self.paths.report_images_dir / name, "x" * 200)
        write_text(
            self.paths.report_file,
            "# R\n\n" + "".join(f"![p](images/{name})\n" for name in names),
        )

    def test_no_inventory_scores_one_and_says_so(self) -> None:
        """Inert by construction. A run that predates the skill is not punished by it."""
        score = _score_source_figure_coverage(self.paths)
        self.assertEqual(score.score, 1.0)
        self.assertIn(SOURCE_FIGURES_FILENAME, score.observed)
        self.assertEqual(score.shortfall, "")

    def test_a_panel_nobody_drew_costs_its_share(self) -> None:
        self._inventory(
            {"figure": "Fig 1a", "drawn_as": "lattice_paths.png"},
            {"figure": "Fig 1b", "drawn_as": "magic_numbers.png"},
            {"figure": "Fig 2", "drawn_as": "growth.png"},
        )
        self._publish("lattice_paths.png")
        score = _score_source_figure_coverage(self.paths)
        self.assertAlmostEqual(score.score, 1 / 3)
        self.assertIn("Fig 1b", score.shortfall)
        self.assertIn("Fig 2", score.shortfall)

    def test_drawing_all_of_them_scores_one(self) -> None:
        self._inventory(
            {"figure": "Fig 1", "drawn_as": "one.png"},
            {"figure": "Fig 2", "drawn_as": "two.png"},
        )
        self._publish("one.png", "two.png")
        self.assertEqual(_score_source_figure_coverage(self.paths).score, 1.0)

    def test_a_file_on_disk_the_report_never_references_does_not_count(self) -> None:
        """The grader reads the report. An image nothing points at is not shown."""
        self._inventory({"figure": "Fig 1", "drawn_as": "one.png"})
        write_text(self.paths.report_images_dir / "one.png", "x" * 200)
        write_text(self.paths.report_file, "# R\n\nNo figure here.\n")
        self.assertEqual(_score_source_figure_coverage(self.paths).score, 0.0)

    def test_a_row_that_names_no_file_is_a_panel_nobody_drew(self) -> None:
        self._inventory({"figure": "Fig 1", "x": "mismatch", "y": "energy"})
        self.assertEqual(_score_source_figure_coverage(self.paths).score, 0.0)

    def test_a_path_is_reduced_to_its_filename(self) -> None:
        self._inventory({"figure": "Fig 1", "drawn_as": "report/images/One.PNG"})
        self._publish("one.png")
        self.assertEqual(_score_source_figure_coverage(self.paths).score, 1.0)


class WhereItAppliesTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Reproduce the published figures.")

    def _draft(self) -> str:
        return (
            "# S\n\n## Objective\n\nx\n\n## What I Did\n\ny\n\n## Key Results\n\nz\n\n"
            "## Files Produced\n\n- none\n\n## Decision Ledger\n\n- Open Questions: a\n"
            "- Locked Decisions: b\n- Assumptions: c\n- Rejected Alternatives: d\n\n"
            "## Suggestions for Refinement\n\n1. x\n"
        )

    def test_it_starts_at_the_stage_that_draws_figures(self) -> None:
        """Before Stage 06 there is nothing to have failed to draw."""
        early = score_stage(paths=self.paths, stage=STAGE_03, markdown=self._draft()).by_key
        self.assertNotIn("source_figure_coverage", early)
        late = score_stage(paths=self.paths, stage=STAGE_06, markdown=self._draft()).by_key
        self.assertIn("source_figure_coverage", late)

    def test_it_never_reads_a_verdict(self) -> None:
        """The property the whole module rests on, asserted for the new criterion too."""
        import inspect

        from src import rubric

        source = inspect.getsource(rubric._score_source_figure_coverage)
        for forbidden in ("hypothesis_outcomes", "verdict", "conclusion"):
            self.assertNotIn(forbidden, source)

    def test_its_weight_is_recorded(self) -> None:
        self.assertEqual(CRITERIA_BY_KEY["source_figure_coverage"].weight, 2.0)
        self.assertEqual(CRITERIA_BY_KEY["source_figure_coverage"].min_stage, 6)


if __name__ == "__main__":
    unittest.main()
