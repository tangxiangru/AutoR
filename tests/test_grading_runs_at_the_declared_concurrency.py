"""`judge_concurrency` was a plan field that reached nothing, and the pass it should have
governed was serial for a reason that inverts on inspection.

The old docstring said one continuous serial pass is the only arrangement under which the
first task's total and the last task's were produced by the same instrument. A pass that takes
ten hours straddles *more* of whatever drift a hosted judge has than one that takes forty
minutes, so serialising widens the window it was meant to close. Measured on the trial of
2026-08-19: ninety-five answers at one draw each, one at a time, was still running six hours
after the last agent finished. At three draws it would have been the larger half of the trial.

Meanwhile `judge_concurrency` was in the plan, in the freeze, in the printed summary and in
the fake scorer's metadata -- and the real path never read it. That is a field recorded and
never used, which is the exact shape this module's own arm validation refuses a plan for.

The tests below hold the three things the change must not cost:

1. the default is still 1, so an existing plan replays what it measured, one call at a time;
2. every draw is still attempted, retried and reported, so a pool cannot silently drop one;
3. a lost draw is still named in `final_pass.json`, because a draw that failed quietly is an
   arm published as replicated when it was not.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
for path in (str(REPO), str(REPO / "tools")):
    if path not in sys.path:
        sys.path.insert(0, path)

from src.fs_trial import FsArmSpec, FsTrialPlan  # noqa: E402
from tools import fs_trial  # noqa: E402

DIRECT = FsArmSpec(label="direct-opus", kind="direct", model="opus", answer_guidance="minimal")
PIPELINE = FsArmSpec(
    label="abc1234-autor-ideate", kind="autor", model="opus", answer_guidance="minimal",
    worktree="/tmp/wt", sha="abc1234", review_model="opus", profile="ideate",
)


class FinalPassTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.state_dir = Path(self.tmp.name)
        (self.state_dir / "scores").mkdir()
        self.addCleanup(self.tmp.cleanup)

    def a_plan(self, **overrides) -> FsTrialPlan:
        kwargs = dict(
            capability="cap", dataset="/tmp/d.jsonl", dataset_sha256="0" * 64,
            tasks=tuple(f"fs:{i:03d}" for i in range(6)),
            control=DIRECT, treatment=PIPELINE, cost_note="UNMEASURED",
            state_dir=str(self.state_dir),
        )
        kwargs.update(overrides)
        return FsTrialPlan(**kwargs)

    def states(self, n: int) -> list[dict]:
        return [
            {"task_key": f"fs:{i:03d}", "arm": "direct-opus", "attempt": 1,
             "phase": "finished", "classification": "ok", "workspace": f"/tmp/ws{i}"}
            for i in range(n)
        ]

    def run_pass(self, plan: FsTrialPlan, states: list[dict], scorer) -> None:
        with mock.patch.object(fs_trial, "all_states", return_value=states), \
             mock.patch.object(fs_trial, "score_once", side_effect=scorer), \
             mock.patch.object(fs_trial, "read_json", return_value={"total_score": 7.0}):
            fs_trial.final_pass(plan)

    def final_pass_json(self) -> dict:
        return json.loads((self.state_dir / "final_pass.json").read_text())

    # -- what the pool must still do -------------------------------------------------

    def test_every_state_and_draw_is_attempted_exactly_once(self) -> None:
        seen: list[str] = []
        lock = threading.Lock()

        def scorer(plan, state, out):
            with lock:
                seen.append(out.name)
            out.write_text("{}")
            return True

        self.run_pass(self.a_plan(judge_replicates=3, judge_concurrency=4), self.states(6), scorer)
        self.assertEqual(len(seen), 18)
        self.assertEqual(len(set(seen)), 18)
        self.assertEqual(sorted(set(name.split(".")[-1] for name in seen)),
                         ["json"])
        self.assertEqual(sorted({name.split(".")[-2] for name in seen}), ["r0", "r1", "r2"])

    def test_a_draw_already_on_disk_is_not_rejudged(self) -> None:
        """Resume has to stay free. Re-judging a scored draw spends money and changes it."""
        existing = fs_trial.score_path(
            self.a_plan(), "fs:000", "direct-opus", 1, 0
        )
        existing.write_text("{}")
        calls: list[str] = []

        def scorer(plan, state, out):
            calls.append(out.name)
            out.write_text("{}")
            return True

        self.run_pass(self.a_plan(judge_replicates=1, judge_concurrency=4), self.states(3), scorer)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(existing.name, calls)

    def test_a_lost_draw_is_named_rather_than_dropped(self) -> None:
        def scorer(plan, state, out):
            return "fs:002" not in str(state["task_key"])

        self.run_pass(self.a_plan(judge_replicates=2, judge_concurrency=4), self.states(4), scorer)
        lost = self.final_pass_json()["unscored_draws"]
        self.assertEqual(len(lost), 2)
        self.assertTrue(all("fs002" in name for name in lost), lost)
        self.assertEqual(lost, sorted(lost))

    def test_a_lost_draw_is_retried_before_it_is_lost(self) -> None:
        attempts: list[str] = []
        lock = threading.Lock()

        def scorer(plan, state, out):
            with lock:
                attempts.append(out.name)
            return False

        self.run_pass(self.a_plan(judge_replicates=1, judge_concurrency=2), self.states(1), scorer)
        self.assertEqual(len(attempts), fs_trial.JUDGE_TRIES)

    def test_the_done_marker_is_written(self) -> None:
        self.run_pass(
            self.a_plan(judge_replicates=1, judge_concurrency=3), self.states(2),
            lambda plan, state, out: (out.write_text("{}"), True)[1],
        )
        self.assertIs(self.final_pass_json()["done"], True)

    # -- that the concurrency is the declared one ------------------------------------

    def test_the_pass_actually_overlaps_at_the_declared_width(self) -> None:
        """The load-bearing one. Without it the pool could be a one-worker pool.

        Counts how many scorers are inside the call at once. Asserting `> 1` rather than
        `== 4` because a thread pool is not obliged to have all its workers resident, but
        one is a serial pass wearing a pool.
        """
        live = 0
        peak = 0
        lock = threading.Lock()

        def scorer(plan, state, out):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.05)
            with lock:
                live -= 1
            out.write_text("{}")
            return True

        self.run_pass(self.a_plan(judge_replicates=2, judge_concurrency=4), self.states(6), scorer)
        self.assertGreater(peak, 1, "the pass ran one call at a time")
        self.assertLessEqual(peak, 4, "the pass exceeded the concurrency the plan declared")

    def test_the_default_plan_is_still_one_at_a_time(self) -> None:
        """Replay fidelity, and the control on the change.

        Every plan already on disk omits this field. If the default moved, those plans
        would be re-scored under an arrangement they did not declare.
        """
        self.assertEqual(self.a_plan().judge_concurrency, 1)
        live = 0
        peak = 0
        lock = threading.Lock()

        def scorer(plan, state, out):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            time.sleep(0.02)
            with lock:
                live -= 1
            out.write_text("{}")
            return True

        self.run_pass(self.a_plan(judge_replicates=2), self.states(5), scorer)
        self.assertEqual(peak, 1)


if __name__ == "__main__":
    unittest.main()
