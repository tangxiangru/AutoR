"""The control arm ran on half the pipeline arm's clock, and it cost the control its best answers.

`stage_timeout_seconds` reached the pipeline arm as a per-stage allowance. The driver passed
nothing to the control, so it ran on `fs_agent.py`'s 1,800 s default -- for the whole run, not
per stage. The pipeline arm therefore had 3,600 s per stage and the control had 1,800 s total.

That is not a slower control, it is a truncated one. Measured on the sixty-task trial of
2026-08-19, three of sixty control runs stopped at **exactly 1,800 s** and all three were
refused; the trial before it lost four of sixty the same way, and its own results page named
them "its longest and probably strongest answers" and said any future comparison should raise
the cap first. Length correlates with score on this rubric, so the runs the cap deleted are
drawn from the top of the arm's distribution.

The fix is a plan field rather than a raised default, for two reasons. A default that changed
under an existing plan would silently re-measure it, so the default stays 1,800 and replay is
exact. And a trial whose two arms are on different clocks is making a choice that belongs in
the frozen plan where a reader can see it, not in a constant two files away.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for path in (str(REPO), str(REPO / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.fs_trial import FsArmSpec, FsTrialPlan  # noqa: E402
from tools.fs_trial import agent_argv  # noqa: E402

DIRECT = FsArmSpec(label="direct-opus", kind="direct", model="opus", answer_guidance="minimal")
PIPELINE = FsArmSpec(
    label="abc1234-autor-ideate", kind="autor", model="opus", answer_guidance="minimal",
    worktree="/tmp/wt", sha="abc1234", review_model="opus", profile="ideate",
)


def a_plan(**overrides) -> FsTrialPlan:
    kwargs = dict(
        capability="cap", dataset="/tmp/d.jsonl", dataset_sha256="0" * 64,
        tasks=("fs:000",), control=DIRECT, treatment=PIPELINE, cost_note="n/a",
        state_dir="/tmp/state",
    )
    kwargs.update(overrides)
    return FsTrialPlan(**kwargs)


def flag(argv: list[str], name: str) -> str | None:
    return argv[argv.index(name) + 1] if name in argv else None


class TheClockReachesTheRunTests(unittest.TestCase):
    def argv_for(self, arm: str, **plan_kwargs) -> list[str]:
        plan = a_plan(**plan_kwargs)
        return agent_argv(plan, "fs:000", arm, Path("/tmp/ws"), 1)

    def test_the_control_is_told_its_own_timeout(self) -> None:
        """The defect: before this, `--answer-timeout` was absent and the default bound."""
        argv = self.argv_for("direct-opus", answer_timeout_seconds=3600)
        self.assertEqual(flag(argv, "--answer-timeout"), "3600")

    def test_the_plan_value_is_what_arrives_and_not_the_front_end_default(self) -> None:
        """A mutation that hardcodes 1800 here would pass every other test in this file."""
        for seconds in (900, 1800, 3600, 7200):
            argv = self.argv_for("direct-opus", answer_timeout_seconds=seconds)
            self.assertEqual(flag(argv, "--answer-timeout"), str(seconds), seconds)

    def test_the_two_clocks_are_separate_knobs(self) -> None:
        """Setting one must not move the other; the whole finding is that they differed."""
        argv = self.argv_for(
            "direct-opus", answer_timeout_seconds=3600, stage_timeout_seconds=1200
        )
        self.assertEqual(flag(argv, "--answer-timeout"), "3600")
        self.assertEqual(flag(argv, "--stage-timeout"), "1200")

    def test_the_pipeline_arm_carries_it_too(self) -> None:
        """It binds nothing there -- `fs_agent.py` reads the stage timeout for `ideate`.

        Sent anyway so the clock lives in one place in the plan. The assertion is that the
        argv is uniform, which is what makes the two arms diffable.
        """
        argv = self.argv_for("abc1234-autor-ideate", answer_timeout_seconds=3600)
        self.assertEqual(flag(argv, "--answer-timeout"), "3600")

    def test_it_is_passed_once(self) -> None:
        argv = self.argv_for("direct-opus", answer_timeout_seconds=3600)
        self.assertEqual(argv.count("--answer-timeout"), 1)

    def test_the_flag_is_one_the_front_end_accepts(self) -> None:
        """Spelled against the parser, not against memory. A flag the front end does not
        define is not ignored -- argparse exits 2 and the run is a refusal with no answer.
        """
        import fs_agent

        parser = fs_agent.build_parser() if hasattr(fs_agent, "build_parser") else None
        if parser is None:  # the module builds its parser inline
            self.assertIn("--answer-timeout", Path(REPO / "fs_agent.py").read_text())
            return
        known = {action.option_strings[0] for action in parser._actions if action.option_strings}
        self.assertIn("--answer-timeout", known)


class WhatAnOldPlanReplaysTests(unittest.TestCase):
    def test_the_default_is_the_front_ends_old_default(self) -> None:
        """1,800, so a plan written before this field reproduces what it measured.

        This is the control on the change. Raising the default instead would have been the
        obvious fix and would have silently re-measured every plan on disk -- including the
        two sixty-task trials whose refusals are the evidence for this field existing.
        """
        self.assertEqual(a_plan().answer_timeout_seconds, 1800)
        self.assertEqual(flag(agent_argv(a_plan(), "fs:000", "direct-opus", Path("/tmp/ws"), 1),
                              "--answer-timeout"), "1800")

    def test_a_plan_may_put_the_arms_on_one_clock(self) -> None:
        plan = a_plan(answer_timeout_seconds=3600, stage_timeout_seconds=3600)
        self.assertEqual(plan.answer_timeout_seconds, plan.stage_timeout_seconds)


if __name__ == "__main__":
    unittest.main()
