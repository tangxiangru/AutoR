"""The census around a reviewer episode, and the one thing it is allowed to do about it.

The invariant tests are the ones to read first. A mechanism that can convert a verdict is
one edit away from converting it the other way, and :mod:`src.supervisor` states the rule
this module inherits: it may never make a gate pass.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.approval_agent import AutomatedReviewer, ReviewDecision
from src.review_custody import (
    CUSTODY_REASON_PREFIX,
    CustodyWatch,
    census,
    churn_files,
    compare,
    demote,
    ledger_path,
)
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, initialize_memory, write_text


STAGE_01 = STAGES[0]


class CensusTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        initialize_memory(self.paths, "goal")
        self.excluded = churn_files(self.paths)

    def _census(self):
        return census(self.paths.run_root, excluded=self.excluded)

    def _diff(self, before):
        return compare(before, self._census(), stage_slug=STAGE_01.slug, label="review")


class WhatTheCensusSeesTests(CensusTestBase):
    def test_a_new_file_is_an_addition(self) -> None:
        before = self._census()
        write_text(self.paths.results_dir / "new.json", "{}")
        breach = self._diff(before)
        self.assertTrue(breach.mutated)
        self.assertIn("workspace/results/new.json", breach.added)

    def test_changed_bytes_are_a_change(self) -> None:
        target = self.paths.results_dir / "r.json"
        write_text(target, '{"n": 1}')
        before = self._census()
        write_text(target, '{"n": 2}')
        breach = self._diff(before)
        self.assertEqual(breach.changed, ("workspace/results/r.json",))

    def test_a_deletion_is_a_breach(self) -> None:
        target = self.paths.results_dir / "r.json"
        write_text(target, "{}")
        before = self._census()
        target.unlink()
        breach = self._diff(before)
        self.assertEqual(breach.deleted, ("workspace/results/r.json",))

    def test_the_same_bytes_written_again_are_touched_not_changed(self) -> None:
        """The measured case, and the reason this census is over content and not mtime.

        Every fire an mtime replay found over 138 archived reviewer episodes was a
        reviewer re-running the doer's producer to check it reproduces. Charging that
        would make the gate fire hardest on the most rigorous reviewer.
        """
        target = self.paths.results_dir / "r.json"
        write_text(target, '{"n": 1}')
        before = self._census()
        import os

        stat = target.stat()
        write_text(target, '{"n": 1}')
        os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10_000_000_000))

        breach = self._diff(before)
        self.assertFalse(breach.mutated)
        self.assertEqual(breach.touched, ("workspace/results/r.json",))

    def test_the_two_log_files_the_harness_writes_are_excluded(self) -> None:
        before = self._census()
        write_text(self.paths.logs, "a line the harness wrote while the reviewer ran")
        write_text(self.paths.logs_raw, '{"_meta": {}}')
        self.assertFalse(self._diff(before).mutated)

    def test_a_pyc_left_by_importing_the_doers_module_is_not_a_breach(self) -> None:
        """Two of the archive fires were of this kind. The `__pycache__` did not exist
        before the reviewer ran, which is what makes the directory entry the trap."""
        before = self._census()
        write_text(self.paths.code_dir / "__pycache__" / "producer.cpython-313.pyc", "bytecode")
        self.assertFalse(self._diff(before).mutated)

    def test_a_git_index_refreshed_by_running_git_status_is_not_a_breach(self) -> None:
        """The other two, in a repository the doer had already cloned."""
        index = self.paths.workspace_root / "literature" / "repo" / ".git" / "index"
        write_text(index, "before")
        before = self._census()
        write_text(index, "after")
        self.assertFalse(self._diff(before).mutated)

    def test_an_absent_run_root_is_not_a_breach(self) -> None:
        """Fail open on absence: a precondition no real run can meet is not a gate."""
        breach = compare(census(Path("/nonexistent/run")), self._census())
        self.assertFalse(breach.mutated)

    def test_the_scan_can_fail(self) -> None:
        """Control: a census that saw nothing would pass every test above."""
        before = self._census()
        self.assertGreater(len(before.entries), 0)


class TheLedgerTests(CensusTestBase):
    def test_one_line_per_episode_even_when_nothing_moved(self) -> None:
        """Only-on-breach would make 'never ran' and 'found nothing' the same record."""
        watch = CustodyWatch(self.paths, mode="record")
        for _ in range(3):
            watch.open()
            watch.close(stage_slug=STAGE_01.slug, label="review")
        lines = ledger_path(self.paths).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual([json.loads(line)["mutated"] for line in lines], [False, False, False])

    def test_a_breach_names_the_paths_and_is_readable_back(self) -> None:
        watch = CustodyWatch(self.paths, mode="record")
        watch.open()
        write_text(self.paths.results_dir / "written_by_the_reviewer.json", "{}")
        watch.close(stage_slug=STAGE_01.slug, label="review")
        line = json.loads(ledger_path(self.paths).read_text(encoding="utf-8").splitlines()[0])
        self.assertTrue(line["mutated"])
        self.assertEqual(line["added"], ["workspace/results/written_by_the_reviewer.json"])
        self.assertEqual(line["stage"], STAGE_01.slug)

    def test_off_takes_no_census_and_writes_no_ledger(self) -> None:
        watch = CustodyWatch(self.paths, mode="off")
        watch.open()
        write_text(self.paths.results_dir / "r.json", "{}")
        self.assertFalse(watch.close(stage_slug=STAGE_01.slug, label="review").mutated)
        self.assertFalse(ledger_path(self.paths).exists())

    def test_record_does_not_arm_the_demotion(self) -> None:
        self.assertFalse(CustodyWatch(self.paths, mode="record").arms_a_demotion)
        self.assertTrue(CustodyWatch(self.paths, mode="demote").arms_a_demotion)

    def test_an_unknown_mode_falls_back_to_the_default_rather_than_arming(self) -> None:
        self.assertFalse(CustodyWatch(self.paths, mode="DEMOTE!").arms_a_demotion)

    def test_the_rollup_is_the_whole_room(self) -> None:
        watch = CustodyWatch(self.paths, mode="demote")
        watch.open()
        write_text(self.paths.results_dir / "seat_one.json", "{}")
        watch.close(stage_slug=STAGE_01.slug, label="panel_pi_r1")
        watch.open()
        write_text(self.paths.results_dir / "seat_two.json", "{}")
        watch.close(stage_slug=STAGE_01.slug, label="panel_skeptic_r1")
        rollup = watch.rollup()
        self.assertEqual(len(rollup.added), 2)
        self.assertIn("panel_pi_r1", rollup.label)
        self.assertIn("panel_skeptic_r1", rollup.label)


class TheDemotionMayNeverMakeAGatePassTests(CensusTestBase):
    """The invariant, tested over the whole menu rather than on the one interesting digit."""

    def _breach(self):
        watch = CustodyWatch(self.paths, mode="demote")
        watch.open()
        write_text(self.paths.results_dir / "r.json", "{}")
        watch.close(stage_slug=STAGE_01.slug, label="review")
        return watch.rollup()

    def test_only_an_approval_moves_and_it_moves_to_a_send_back(self) -> None:
        breach = self._breach()
        moved = {}
        for choice in ("1", "2", "3", "4", "5", "6"):
            before = ReviewDecision(choice=choice, decision_token="t")
            after = demote(before, breach)
            if after.choice != choice:
                moved[choice] = after.choice
        self.assertEqual(moved, {"5": "4"})

    def test_an_abort_is_left_alone(self) -> None:
        """Turning a `6` into a revise would make a stopped run continue."""
        decision = ReviewDecision(choice="6", decision_token="abort", reason="stop")
        self.assertEqual(demote(decision, self._breach()), decision)

    def test_a_clean_episode_changes_nothing(self) -> None:
        decision = ReviewDecision(choice="5", decision_token="approve")
        watch = CustodyWatch(self.paths, mode="demote")
        watch.open()
        watch.close(stage_slug=STAGE_01.slug, label="review")
        self.assertIs(demote(decision, watch.rollup()), decision)

    def test_it_clears_what_could_only_make_a_later_gate_easier(self) -> None:
        decision = ReviewDecision(
            choice="5",
            decision_token="approve",
            raw_response="the reviewer's own words",
            carry_forward=[{"obligation": "owe a power analysis"}],
            discharged=["O001"],
            comments=[{"quote": "a span"}],
        )
        after = demote(decision, self._breach())
        self.assertEqual(after.discharged, [], "closing an inherited debt is a gate passing")
        self.assertEqual(after.comments, [], "an anchored comment makes a refusal local")
        self.assertEqual(after.carry_forward, decision.carry_forward, "a debt can only add burden")
        self.assertEqual(after.raw_response, decision.raw_response, "or the demotion is unfalsifiable")

    def test_the_reason_says_which_mechanism_refused(self) -> None:
        after = demote(ReviewDecision(choice="5", decision_token="approve"), self._breach())
        self.assertTrue(after.reason.startswith(CUSTODY_REASON_PREFIX))
        self.assertIn("workspace/results/r.json", after.feedback)


class AReviewerThatWroteTests(CensusTestBase):
    """End to end through `AutomatedReviewer.review_stage`, with the subprocess stubbed."""

    def _reviewer(self, mode: str) -> AutomatedReviewer:
        return AutomatedReviewer(
            "claude",
            model="opus",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            custody_mode=mode,
        )

    def _run(self, mode: str, *, write: bool) -> ReviewDecision:
        reviewer = self._reviewer(mode)

        def fake_stream(*args, **kwargs):
            if write:
                write_text(self.paths.results_dir / "the_reviewer_wrote_this.json", "{}")
            return (
                0,
                json.dumps({"decision": "approve", "reason": "every criterion is met"}),
                "",
                "session",
                {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0},
            )

        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            reviewer._operator, "_run_streaming_command", side_effect=fake_stream
        ):
            return reviewer.review_stage(
                paths=self.paths,
                stage=STAGE_01,
                attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey\n",
                suggestions=["tighten the scope", "add a baseline", "state the limitation"],
            )

    def test_an_armed_run_demotes_the_approval(self) -> None:
        decision = self._run("demote", write=True)
        self.assertEqual(decision.choice, "4")
        self.assertIn("the_reviewer_wrote_this.json", decision.feedback)

    def test_recording_alone_leaves_the_verdict_where_the_reviewer_put_it(self) -> None:
        decision = self._run("record", write=True)
        self.assertEqual(decision.choice, "5")
        self.assertTrue(
            any(json.loads(line)["mutated"] for line in ledger_path(self.paths).read_text().splitlines())
        )

    def test_a_reviewer_that_wrote_nothing_is_approved_even_when_armed(self) -> None:
        """The control. A gate that fires on an honest review is worse than no gate."""
        self.assertEqual(self._run("demote", write=False).choice, "5")

    def test_the_prompt_file_and_the_call_record_are_outside_the_window(self) -> None:
        """Both are harness writes, and neither needs an exclusion — the boundary does it."""
        self._run("demote", write=False)
        line = json.loads(ledger_path(self.paths).read_text().splitlines()[0])
        self.assertEqual(line["added"], [])
        self.assertEqual(line["changed"], [])


if __name__ == "__main__":
    unittest.main()
