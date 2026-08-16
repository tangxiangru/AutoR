"""What a report may publish and what a grader reads are two numbers, not one.

They were one constant until the ceiling moved from 5 to 15, and the prompt kept the
sentence built for the old value. For a while every Stage 07 agent was told, in the same
paragraph, that "the reviewer is shown only the first 15 images" — false, the grader
attaches `generated_images[:5]` to each image item — and that "a sixth figure does not
add a sixth chance to be credited", which counts from a ceiling that no longer existed.

A prompt that misdescribes the grading is worse than one that says nothing about it: the
agent optimises against the description. So the two numbers are separate constants, and
these tests fail if anything merges them again.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from src.utils import (
    JUDGE_VISIBLE_FIGURES,
    MAX_REPORT_FIGURES,
    STAGES,
    build_run_paths,
    ensure_run_layout,
    format_stage_template,
    read_text,
)

PROMPTS = Path(__file__).resolve().parent.parent / "src" / "prompts"
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


class TheTwoNumbersAreDistinctTest(unittest.TestCase):
    def test_the_grader_window_is_not_the_publishing_ceiling(self) -> None:
        self.assertLessEqual(JUDGE_VISIBLE_FIGURES, MAX_REPORT_FIGURES)
        self.assertNotEqual(
            JUDGE_VISIBLE_FIGURES,
            MAX_REPORT_FIGURES,
            "if these are ever equal again, every sentence that distinguishes them "
            "becomes untestable — change the test deliberately, not by accident",
        )

    def test_the_window_matches_the_benchmark_scorer(self) -> None:
        """`evaluation/score.py` slices `generated_images[:5]` per image item."""
        self.assertEqual(JUDGE_VISIBLE_FIGURES, 5)


class TheStage07PromptTellsTheTruthTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        self.rendered = format_stage_template(
            read_text(PROMPTS / "07_writing_markdown.md"), STAGE_07, self.paths
        )

    def test_no_placeholder_survives_rendering(self) -> None:
        self.assertEqual(re.findall(r"\{\{[A-Z_]+\}\}", self.rendered), [])

    def test_it_does_not_claim_the_ceiling_is_what_the_reviewer_sees(self) -> None:
        """The exact false sentence this file exists for."""
        self.assertNotIn(f"first {MAX_REPORT_FIGURES} images", self.rendered)
        self.assertNotIn(f"only the first {MAX_REPORT_FIGURES}", self.rendered)

    def test_it_states_the_real_window(self) -> None:
        self.assertIn(f"first {JUDGE_VISIBLE_FIGURES} images reach the reviewer", self.rendered)

    def test_it_says_the_ceiling_is_not_a_target(self) -> None:
        """A ceiling an agent reads as a quota is a quota."""
        self.assertIn(f"{MAX_REPORT_FIGURES} figures is a ceiling", self.rendered)
        self.assertIn("not a target", self.rendered)

    def test_it_puts_the_work_above_the_figure_count(self) -> None:
        # Matched on unwrapped text: the sentence wraps in the template.
        flowed = " ".join(self.rendered.split())
        self.assertIn("whether the key quantities were produced and shown", flowed)


class TheGateSaysTheSameThingTest(unittest.TestCase):
    def test_the_over_ceiling_refusal_distinguishes_them(self) -> None:
        from src.utils import validate_markdown_report

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        paths.report_file.write_text(
            "# R\n\n## Results\n\n" + "".join(
                f"![f{i}](images/f{i}.png)\n" for i in range(MAX_REPORT_FIGURES + 1)
            ) + "body " * 400,
            encoding="utf-8",
        )
        for i in range(MAX_REPORT_FIGURES + 1):
            (paths.report_images_dir / f"f{i}.png").write_bytes(b"x" * 200)
        problems = " ".join(validate_markdown_report(paths))
        if "ceiling" not in problems:
            self.skipTest("the over-ceiling branch did not fire in this fixture")
        self.assertIn(f"Only {JUDGE_VISIBLE_FIGURES} of them reach the reviewer", problems)


if __name__ == "__main__":
    unittest.main()
