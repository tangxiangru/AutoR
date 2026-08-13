"""The approval gate has to ask whether the stage did the task, not just whether it worked.

Two ResearchClawBench runs scored 18.9 and 4.7 while AutoR's own rubric gave them 1.00 on
all eight criteria at every late stage. The judge's words: "the report explicitly states
that no ECAT model was assembled, no LHS design was drawn, and no mechanism simulations
were run". The other characterised a corpus instead of performing the Hartree-Fock
derivations the task named.

Neither is a quality failure and no completeness signal catches them. A substituted task
produces real artifacts, real numbers, numbers that trace to real files, and no hedging --
so `commitment`, `quantification`, `artifact_breadth` and `numeric_fidelity` are all
satisfied by an audit. Four mechanical proxies were measured against the twelve scored runs
and all four failed: a plan cross-check fired on 1 of 12 and it was the best run; an
artifact-citation ratio correlated +0.01; a self-declared-skip gate fired on 11 of 12
including the two highest scorers; and a data-reachability ratio collapsed to no variance
once measured fairly. The distinction is semantic, so it is asked of the reviewer, which
since the goal-excerpt fix can finally see the whole task.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.approval_agent import AutomatedReviewer
from src.utils import StageSpec, build_run_paths, ensure_run_layout, write_text


STAGE = StageSpec(5, "05_experimentation", "Experimentation")


class SubstitutionCheckTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Train a machine-learning potential on the supplied data.")
        write_text(self.paths.memory, "# Memory\n")
        self.prompt = AutomatedReviewer("claude", model="opus", unattended=True)._build_review_prompt(
            paths=self.paths, stage=STAGE, attempt_no=1,
            stage_markdown="# Stage 05\n\n## Key Results\n\nAudited the data.",
            suggestions=["a", "b", "c"],
        )

    def test_the_policy_line_ties_completeness_to_the_task(self) -> None:
        """"Materially complete for its milestone" is satisfied by a substituted task."""
        self.assertIn("the work it completed is the work the task asked for", self.prompt)

    def test_the_failure_mode_is_named_rather_than_left_open(self) -> None:
        """This repo already records that an open-ended critique returns prose quality."""
        self.assertIn("substitution", self.prompt.lower())
        for shape in ("audit the input data", "characterise the corpus", "one arm"):
            self.assertIn(shape, self.prompt)

    def test_it_says_why_the_completeness_signals_do_not_catch_it(self) -> None:
        self.assertIn("Every completeness signal is satisfied", self.prompt)

    def test_absent_inputs_are_explicitly_not_substitution(self) -> None:
        """Physics_000 declared sixteen unmet items and scored 36.9 -- the second highest.

        A gate that treats "the workspace does not contain this" as slacking demands the
        impossible, and the run that says so honestly is the one it punishes.
        """
        self.assertIn("is not substitution", self.prompt)
        self.assertIn("learns to stop being honest", self.prompt)

    def test_it_asks_the_discriminating_question(self) -> None:
        """Runnable-but-skipped is the whole distinction; a guard cannot make it."""
        self.assertIn("could the named work have been done with what is in this workspace",
                      self.prompt.lower())

    def test_it_demands_an_actionable_objection(self) -> None:
        self.assertIn("which named output was skipped", self.prompt)
        self.assertIn("not actionable", self.prompt)

    def test_the_check_sits_before_the_verdict_contract(self) -> None:
        """The closing instruction must stay the literal last thing the reviewer reads."""
        self.assertLess(self.prompt.index("substitution check"),
                        self.prompt.index("# Your Final Message"))

    def test_the_reviewer_can_see_the_task_it_is_asked_about(self) -> None:
        """Asking the question is useless if the goal block was truncated away."""
        self.assertIn("Train a machine-learning potential on the supplied data.", self.prompt)


if __name__ == "__main__":
    unittest.main()
