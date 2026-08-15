"""The approval gate has to be able to read the task it is judging against.

The reviewer's job is deciding whether a stage did its job, and the only statement of what
that job is comes from the goal block. It read the first 3,000 characters, head-truncated,
and on a benchmark run the goal opens with AutoR's own header and workspace contract.

Measured over the 40 ResearchClawBench tasks: the gate had never once seen a whole task --
0 of 39 complete, median 50% visible, longest task 8,540 characters. What falls off the end
is the task's own list of required outputs and data files, so "materially complete for its
current milestone" was judged against half a question.

`goal_excerpt` already fixes this and three other readers already use it: the router, the
deliberation panel and the adversarial validity reviewer were all moved onto it. The
approval gate -- the one reader whose entire job is deciding whether the task was done --
was left behind.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.approval_agent import GOAL_EXCERPT_CHARS, AutomatedReviewer
from src.deliverables import COVERAGE_FILENAME
from src.utils import (
    TASK_BEGIN_MARKER,
    TASK_END_MARKER,
    StageSpec,
    build_run_paths,
    ensure_run_layout,
    write_text,
)


STAGE = StageSpec(1, "01_literature_survey", "Literature Survey")

#: The shape of a benchmark goal: AutoR's own preamble, the fenced task, then more of
#: AutoR's own contract after it.
PREAMBLE = "# Benchmark Run: ResearchClawBench\n\n" + ("AutoR preamble prose. " * 40)
TRAILER = "\n\n## Benchmark Workspace Contract\n\n" + ("AutoR contract prose. " * 400)


def build_goal(task: str) -> str:
    return f"{PREAMBLE}\n\n## Research Task\n{TASK_BEGIN_MARKER}\n{task}\n{TASK_END_MARKER}{TRAILER}"


class ReviewerGoalBlockTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.memory, "# Memory\n")
        self.reviewer = AutomatedReviewer("claude", model="opus", unattended=True)

    def _prompt(self, task: str) -> str:
        write_text(self.paths.user_input, build_goal(task))
        return self.reviewer._build_review_prompt(  # noqa: SLF001
            paths=self.paths, stage=STAGE, attempt_no=1,
            stage_markdown="# Stage 01\n\n## Key Results\n\nSomething.",
            suggestions=["a", "b", "c"],
        )

    def test_the_whole_task_reaches_the_reviewer(self) -> None:
        """A 5,400-character task is the median; it used to be cut in half."""
        task = ("### Task Description\n" + ("Body sentence. " * 300)
                + "\n\nOutput: correctly derived Hartree-Fock Hamiltonians.\n")
        self.assertGreater(len(task), 3000)
        self.assertIn("Output: correctly derived Hartree-Fock Hamiltonians.", self._prompt(task))

    def test_the_longest_real_task_fits(self) -> None:
        """The longest of the 40 benchmark tasks is 8,540 characters."""
        task = ("x" * 8540) + "\nOutput: the deliverable.\n"
        self.assertIn("Output: the deliverable.", self._prompt(task))

    def test_autors_own_preamble_does_not_spend_the_budget(self) -> None:
        """The goal opens with AutoR's header; a head-truncation reads that first."""
        prompt = self._prompt("### Task Description\n" + ("Body sentence. " * 300))
        self.assertNotIn("AutoR preamble prose.", prompt)
        self.assertNotIn("AutoR contract prose.", prompt)

    def test_an_overlong_task_loses_its_tail_not_its_subject(self) -> None:
        task = "SUBJECT: reproduce the study.\n" + ("filler. " * 4000) + "\nCLOSING NOTE\n"
        self.assertGreater(len(task), GOAL_EXCERPT_CHARS)
        prompt = self._prompt(task)
        self.assertIn("SUBJECT: reproduce the study.", prompt)
        self.assertNotIn("CLOSING NOTE", prompt)

    def test_an_unfenced_goal_still_works(self) -> None:
        """An ordinary interactive run has no fence and must be unaffected."""
        write_text(self.paths.user_input, "Study whether X causes Y.")
        prompt = self.reviewer._build_review_prompt(  # noqa: SLF001
            paths=self.paths, stage=STAGE, attempt_no=1,
            stage_markdown="# Stage 01\n", suggestions=["a", "b", "c"],
        )
        self.assertIn("Study whether X causes Y.", prompt)

    def test_the_budget_covers_every_benchmark_task(self) -> None:
        """Stated rather than assumed: 10,000 against a measured maximum of 8,540."""
        self.assertGreaterEqual(GOAL_EXCERPT_CHARS, 8540)


class ReviewerSeesTheCoverageRecordTest(unittest.TestCase):
    """The substitution check was run without the artifact that reports the substitution.

    `deliverables_coverage.json` is the one machine-readable file in which a stage states,
    item by item, which of the task's demands it met and which it did not. On the run an
    external judge scored 0.0, it marked the task's first named output addressed with four
    PNG filenames as its evidence, and marked the only named data file unmet with a
    reason. The reviewer running "did this stage do the task, or an adjacent cheaper one?"
    was shown the run manifest, the artifact index, the experiment manifest and a log
    tail — and none of that.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.memory, "# Memory\n")
        write_text(self.paths.user_input, "Derive the Hartree-Fock Hamiltonian.")
        self.reviewer = AutomatedReviewer("claude", model="opus", unattended=True)

    def _prompt(self) -> str:
        return self.reviewer._build_review_prompt(  # noqa: SLF001
            paths=self.paths, stage=STAGE, attempt_no=1,
            stage_markdown="# Stage 01\n\n## Key Results\n\nSomething.",
            suggestions=["a", "b", "c"],
        )

    def test_the_record_reaches_the_reviewer(self) -> None:
        write_text(
            self.paths.artifacts_dir / COVERAGE_FILENAME,
            '{"deliverables": [{"task_quote": "Derive the Hartree-Fock Hamiltonian.", '
            '"addressed": true, "where": "images/derived_hamiltonians.png"}]}',
        )
        prompt = self._prompt()
        self.assertIn("images/derived_hamiltonians.png", prompt)
        self.assertIn("Task Coverage Record", prompt)

    def test_it_is_framed_as_a_claim_rather_than_as_evidence(self) -> None:
        """A self-report read as evidence would make the check circular."""
        write_text(self.paths.artifacts_dir / COVERAGE_FILENAME, '{"deliverables": []}')
        prompt = self._prompt()
        self.assertIn("It is not evidence; it is the claim", prompt)
        self.assertIn("runnable from what is in this workspace", prompt)

    def test_a_stage_that_has_not_written_one_yet_still_gets_a_review(self) -> None:
        self.assertIn("Task Coverage Record", self._prompt())


class PanelSeatsSeeItTooTest(unittest.TestCase):
    """A seat cannot judge whether a stage did the task on half the task either."""

    def test_the_panel_uses_the_same_reader(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "src" / "review_panel.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("goal_excerpt(read_text(paths.user_input)", source)
        self.assertNotIn("excerpt(paths.user_input, 3000)", source)


if __name__ == "__main__":
    unittest.main()
