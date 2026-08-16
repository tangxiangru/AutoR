"""What a report may publish and what a grader reads are two numbers that keep moving.

`MAX_REPORT_FIGURES` is ours: how many figures a report may publish. `JUDGE_VISIBLE_FIGURES`
is not ours: `evaluation/score.py` slices `generated_images[:N]` for every image item, and
ResearchClawBench chooses N. It was 5, and upstream raised it to 15 in `bfffc48` on
2026-08-14.

Both mistakes this file exists to prevent have already been made here, a day apart and in
opposite directions. First the ceiling moved to 15 while the prompt kept the sentence built
for 5, so every Stage 07 agent read "the reviewer is shown only the first 15 images" next to
"a sixth figure does not add a sixth chance to be credited". Then that was "corrected" to 5
— off a bench checkout last pulled three weeks earlier, a day after upstream had moved to
15 — which shipped a prompt asserting the opposite of the truth.

A prompt that misdescribes the grading is worse than one that says nothing about it, because
the agent optimises against the description. So the constant is checked against the bench's
own source, not against anyone's memory of it.
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


#: Where a ResearchClawBench checkout may be, if this machine has one. The check that
#: matters skips rather than guesses when it is absent, because a test that invents the
#: number it is verifying is the failure it is meant to catch.
_BENCH_CANDIDATES = (
    Path.home() / "RCB",
    Path.home() / "ResearchClawBench",
    Path("/rmeng_data/robtang/RCB"),
)
_SLICE = re.compile(r"generated_images\[:(\d+)\]")


class TheWindowTracksTheBenchTest(unittest.TestCase):
    def test_the_window_matches_the_benchmark_source(self) -> None:
        """Read the number out of the grader rather than restating it from memory.

        This is the assertion that would have caught both directions of the mistake: the
        prompt describing a 15-figure window when the bench sliced 5, and the constant
        being set to 5 the day after the bench moved to 15.
        """
        for root in _BENCH_CANDIDATES:
            source = root / "evaluation" / "score.py"
            if not source.is_file():
                continue
            found = _SLICE.search(source.read_text(encoding="utf-8", errors="replace"))
            self.assertIsNotNone(found, f"{source} no longer slices generated_images")
            assert found is not None  # for type checkers
            self.assertEqual(
                int(found.group(1)),
                JUDGE_VISIBLE_FIGURES,
                f"{source} slices generated_images[:{found.group(1)}] and "
                f"JUDGE_VISIBLE_FIGURES is {JUDGE_VISIBLE_FIGURES}. Upstream moved; follow "
                "it, and re-read every sentence in the Stage 07 prompt that quotes either "
                "number before deciding which one is wrong.",
            )
            return
        self.skipTest("no ResearchClawBench checkout on this machine")

    def test_a_report_may_not_publish_more_than_the_grader_reads(self) -> None:
        """They are different ideas and happen to be equal; this is the relation that holds."""
        self.assertLessEqual(JUDGE_VISIBLE_FIGURES, MAX_REPORT_FIGURES)


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

    def test_it_states_the_window_the_bench_actually_uses(self) -> None:
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
