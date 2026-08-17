"""The FrontierScience driver: the lock, the state, and whole trials without spending one.

The policy is a pure function and is tested in :mod:`tests.test_fs_trial`. What is left
here is the machinery that touches processes and files, and it is tested by *running*
it -- on a fabricated operator and a fabricated judge, with the real lock, real
``Popen(start_new_session=True)`` children, real atomic state writes, the real stall
watchdog, the real metadata builder, the real transcript witness, the real admission
gate, the real scorer's pure half and the real report. Only the two things that cost
money are fake.

That is not a mock of the driver, and the difference matters here more than it does for
the sibling. This driver runs several children at once and reaps them itself, and the
states it has to survive -- a live child from a previous driver, a child whose pid is
gone, two arms of one task launched inside the same second -- are all states that only
exist once real processes are involved.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "fs_trial.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("fs_trial_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def make_worktree(root: Path, name: str = "treatment") -> tuple[Path, str]:
    """A real git checkout, because ``producer_matches_arm`` reads a real ``rev-parse``.

    It carries an ``fs_agent.py`` because the non-fake branch launches exactly that file,
    so a test that wants to see the argv the driver would really build has to have
    something there.
    """
    path = root / name
    path.mkdir()
    (path / "fs_agent.py").write_text("# placeholder\n", encoding="utf-8")
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-q", "-m", name)
    return path, run("rev-parse", "HEAD").stdout.strip()


class DryRunCase(unittest.TestCase):
    """A whole trial, with the hours and the judge's bill taken out."""

    def setUp(self) -> None:
        self.tool = load_tool()
        # The loop's poll interval is a wall-clock choice for a trial whose runs take
        # hours; a test that honoured it would spend a second per idle iteration doing
        # nothing. The constant is what the shipped driver uses and this is the one place
        # it is overridden.
        self.tool.POLL_SECONDS = 0.02
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # The preflight refusal is a property of the box, not of the trial: this machine
        # has been observed running three AutoR processes at once, and these tests are
        # not about them.
        self.tool.foreign_runs = lambda: []
        self.worktree, self.sha = make_worktree(self.root)

    def _plan(self, *, tasks=("fs:000", "fs:001"), **overrides) -> Path:
        self.treatment_arm = f"{self.sha[:7]}-autor-ideate"
        self.control_arm = "direct-opus"
        payload = {
            "capability": "fs_ideate_vs_direct_opus",
            "cost_note": "Dry run. The pipeline arm's real cost is UNMEASURED.",
            "dataset": str(self.root / "research_test.jsonl"),
            "dataset_sha256": "96c0434a",
            "tasks": list(tasks),
            "control": {
                "label": self.control_arm, "kind": "direct", "model": "opus",
                "answer_guidance": "minimal",
            },
            "treatment": {
                "label": self.treatment_arm, "kind": "autor", "model": "opus",
                "answer_guidance": "minimal", "worktree": str(self.worktree),
                "sha": self.sha[:7], "review_model": "opus", "profile": "ideate",
            },
            "judge_kind": "fake",
            "judge_model": "gpt-5.1",
            "state_dir": str(self.root / "state"),
            "operator": "fake",
            "concurrency": 4,
            "fake_quality": 1.5,
        }
        payload.update(overrides)
        path = self.root / "plan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def drive(self, *argv: str) -> int:
        """Run a subcommand with its stdout swallowed.

        The driver prints the whole report on exit, by design -- an operator watching a
        multi-day trial should not have to open a file to see how it came out. Thirty of
        those inside one test module would bury the failure that matters. Stderr goes the
        same way because one test drives the preflight refusal on purpose, and its two
        paragraphs of shouting are the expected output rather than a symptom.
        """
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return self.tool.main(list(argv))

    def _states(self) -> list[dict]:
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((self.root / "state" / "runs").glob("*.json"))
        ]


class AWholeTrialTests(DryRunCase):
    def test_a_whole_trial_freezes_runs_grades_and_reports(self) -> None:
        path = self._plan()
        self.assertEqual(self.drive("plan", "--plan", str(path)), 0)
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)

        states = self._states()
        self.assertEqual(len(states), 4)
        for state in states:
            self.assertEqual(state["phase"], "finished")
            self.assertEqual(state["classification"], "ok")
            self.assertEqual(state["meta_status"], "completed")
            self.assertIs(state["meta_pipeline_completed"], True)
            # The witness is read back off a real transcript the fake wrote, so the
            # no-browsing clause is answered by a reading rather than by a constant.
            self.assertEqual(state["browsing_tool_calls"], 0)
            self.assertIs(state["truncated"], False)
            self.assertGreater(state["backend_calls"], 0)

        scores = sorted((self.root / "state" / "scores").glob("*.json"))
        self.assertEqual(len(scores), 4)

        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("pairs: **2**", report)
        self.assertIn("FrontierScience rubric points (0-10)", report)
        self.assertIn("gpt-5.1", report)
        self.assertIn("not comparable to the paper's table", report)
        # The fake operator hands the treatment arm a better answer, so the apparatus
        # must show a signed, non-zero, correctly-directed difference. Two identical
        # columns would let a broken seam pass.
        self.assertIn("won 2, lost 0", report)

    def test_the_two_arms_walk_the_shapes_their_kinds_allow(self) -> None:
        """The ideate arm approves one stage and the direct arm approves none.

        Asserted on the artifacts rather than on the clause, because the clause reading
        the two apart is only worth anything if the two producers really differ here.
        """
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        by_arm = {state["arm"]: state for state in self._states()}
        self.assertEqual(by_arm[self.control_arm]["meta_stages_approved"], [])
        self.assertEqual(
            by_arm[self.treatment_arm]["meta_stages_approved"], ["02_hypothesis_generation"]
        )

    def test_the_report_is_a_pure_function_of_the_state_directory(self) -> None:
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        first = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        (self.root / "state" / "report.md").unlink()
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        self.assertEqual(
            (self.root / "state" / "report.md").read_text(encoding="utf-8"), first
        )

    def test_a_second_run_of_a_finished_trial_launches_nothing(self) -> None:
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        before = sorted(p.name for p in (self.root / "state" / "workspaces").iterdir())
        self.drive("run", "--plan", str(path))
        after = sorted(p.name for p in (self.root / "state" / "workspaces").iterdir())
        self.assertEqual(before, after)

    def test_a_workspace_is_never_reused_between_arms_or_attempts(self) -> None:
        """Two arms in one directory overwrite each other's answer and make the paired
        difference identically zero, which is what the sibling driver did."""
        path = self._plan(tasks=("fs:000", "fs:001", "fs:002"))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        workspaces = list((self.root / "state" / "workspaces").iterdir())
        self.assertEqual(len(workspaces), 6)
        self.assertEqual(len({p.name for p in workspaces}), 6)
        for workspace in workspaces:
            self.assertTrue((workspace / "answer.md").is_file())

    def test_two_arms_of_one_task_launched_together_get_two_directories(self) -> None:
        """Directly, without waiting for the loop, because the collision the sibling hit
        needed both creations inside one second and a loop can hide that."""
        path = self._plan()
        plan = self.tool.load_plan(path)
        first = self.tool.make_workspace(plan, "fs:000", self.control_arm)
        second = self.tool.make_workspace(plan, "fs:000", self.treatment_arm)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir() and second.is_dir())

    def test_editing_a_frozen_plan_is_refused(self) -> None:
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["tasks"] = ["fs:000", "fs:001", "fs:002"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.drive("run", "--plan", str(path))
        self.assertIn("frozen", str(caught.exception))

    def test_running_without_freezing_first_is_refused(self) -> None:
        path = self._plan()
        with self.assertRaises(SystemExit) as caught:
            self.drive("run", "--plan", str(path))
        self.assertIn("freeze the plan first", str(caught.exception))

    def test_a_foreign_autor_process_stops_the_driver_starting(self) -> None:
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        self.tool.foreign_runs = lambda: ["4242 python fs_agent.py --workspace /x"]
        self.assertEqual(self.drive("run", "--plan", str(path)), 2)

    def test_this_driver_s_own_recorded_children_are_not_intruders(self) -> None:
        """The control, and the difference from the serial sibling.

        This driver runs several agents at once, so pids it wrote down itself are the
        ordinary state after a restart. Counting them as intruders would make every
        resume refuse to start.
        """
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        mine = self._states()[0]["child_pid"]
        self.tool.foreign_runs = lambda: [f"{mine} python fs_agent.py --workspace /x"]
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)


class TheDuplicateRowsFoldEndToEndTests(DryRunCase):
    def test_the_byte_identical_rows_become_one_pair(self) -> None:
        """Rows 6 and 11 of the real split are the same question; the fake reproduces it."""
        path = self._plan(tasks=("fs:006", "fs:011", "fs:025"))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("pairs: **2**", report)
        self.assertIn("`fs:006` <- `fs:006`, `fs:011`", report)
        self.assertIn("not over the paper's sixty-row population", report)
        # And no interim banner: the fold is a design decision, not attrition.
        self.assertNotIn("INTERIM", report)

    def test_switching_the_fold_off_gives_the_paper_s_population(self) -> None:
        """The control: without it, the pair count above could come from anywhere."""
        path = self._plan(tasks=("fs:006", "fs:011", "fs:025"), dedupe_pairs=False)
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("pairs: **3**", report)
        self.assertIn("Duplicate rows were not folded", report)


class ARunThatIsNotAMeasurementTests(DryRunCase):
    def test_a_run_with_no_transcript_refuses_the_pair_and_withholds_the_difference(self) -> None:
        """A null witness is not a clean run, end to end rather than in a dictionary."""
        path = self._plan(tasks=("fs:000", "fs:001"), fake_faults=["no-transcript"])
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `no_browsing` | 2 |", report)
        self.assertIn("The difference is not published", report)
        self.assertNotIn("mean difference:", report)

    def test_a_run_that_browsed_is_refused_by_the_protocol_clause(self) -> None:
        path = self._plan(tasks=("fs:000", "fs:001"), fake_faults=["browse"])
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        states = {s["arm"]: s for s in self._states()}
        self.assertEqual(states[self.treatment_arm]["browsing_tool_calls"], 1)
        self.assertEqual(states[self.control_arm]["browsing_tool_calls"], 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `no_browsing` | 2 |", report)

    def test_a_truncated_answer_is_refused(self) -> None:
        path = self._plan(tasks=("fs:000", "fs:001"), fake_faults=["truncate"])
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `answer_not_truncated` | 2 |", report)

    def test_a_clean_dry_run_refuses_nothing(self) -> None:
        """The control for the three above: the faults are what make those clauses fire."""
        path = self._plan(tasks=("fs:000", "fs:001"))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("- no run was refused.", report)


class CrashSurvivalTests(DryRunCase):
    def test_a_launched_run_whose_pid_is_gone_is_abandoned_into_a_fresh_workspace(self) -> None:
        """The kill-and-restart case, staged deterministically rather than by racing.

        A real ``kill -9`` leaves exactly this on disk: a state file that says
        ``launched`` and a pid the operating system has already reclaimed. Writing it by
        hand is what makes the assertion about *what the driver does next* rather than
        about how fast the test can send a signal.
        """
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        plan = self.tool.load_plan(path)
        stale = self.root / "state" / "workspaces" / "fs000_direct-opus_stale"
        stale.mkdir(parents=True)
        self.tool.write_json(
            self.tool.state_path(plan, "fs:000", self.control_arm, 1),
            {
                "task_key": "fs:000", "arm": self.control_arm, "attempt": 1,
                "phase": "launched", "child_pid": 999_999, "workspace": str(stale),
            },
        )
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)

        by_attempt = {state["attempt"]: state for state in self._states() if state["arm"] == self.control_arm}
        self.assertEqual(by_attempt[1]["phase"], "abandoned")
        self.assertEqual(by_attempt[2]["phase"], "finished")
        self.assertNotEqual(by_attempt[2]["workspace"], str(stale))
        # Never resumed: the abandoned workspace is left alone rather than answered into.
        self.assertFalse((stale / "answer.md").exists())

    def test_a_live_child_is_counted_against_the_budget_and_not_aborted(self) -> None:
        """A live ``launched`` run from a previous driver is the ordinary restart state.

        The serial sibling aborts here, and is right to: one child at a time means a
        second one is proof of two drivers. This driver asks for several at once, and the
        lock has already refused a second live driver, so the only correct reading is
        "one of mine is still going".
        """
        path = self._plan(tasks=("fs:000",), concurrency=1)
        plan = self.tool.load_plan(path)
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "fs_agent.py"]
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        states = [{
            "task_key": "fs:000", "arm": self.control_arm, "attempt": 1,
            "phase": "launched", "child_pid": holder.pid,
        }]
        actions = self.tool.next_actions(
            plan, states, now=time.time(),
            live_pids=self.tool.autor_pids(markers=self.tool.OUR_RUN_MARKERS),
        )
        self.assertEqual([action.kind for action in actions], ["wait"])

    def test_the_same_state_directory_twice_gives_the_same_actions(self) -> None:
        path = self._plan(tasks=("fs:000", "fs:001"))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        plan = self.tool.load_plan(path)
        first = self.tool.next_actions(
            plan, self.tool.all_states(plan), now=time.time(), final_pass_done=True
        )
        second = self.tool.next_actions(
            plan, self.tool.all_states(plan), now=time.time(), final_pass_done=True
        )
        self.assertEqual(first, second)
        self.assertEqual([action.kind for action in first], ["done"])


class TheLockIsTheKernelSTests(DryRunCase):
    def test_the_driver_names_itself_when_it_takes_the_lock(self) -> None:
        """A driver that let the marker default reads its own live lock as stale.

        ``lock_is_live`` looks for the *holder's* marker, so a driver called
        ``fs_trial.py`` that asked whether an ``rcb_trial.py`` held the lock would be told
        no and would take over a lock a live sibling is holding.
        """
        source = TOOL.read_text(encoding="utf-8")
        self.assertIn('acquire_lock(Path(plan.state_dir), marker="fs_trial.py")', source)

    def test_a_second_driver_is_refused_while_the_first_is_alive(self) -> None:
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "tools/fs_trial.py"]
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        state = self.root / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "driver.lock").write_text(
            json.dumps(
                {"pid": holder.pid, "boot_id": self.tool.boot_id(), "marker": "fs_trial.py"}
            ),
            encoding="utf-8",
        )
        path = self._plan()
        self.drive("plan", "--plan", str(path))
        with self.assertRaises(SystemExit) as caught:
            self.drive("run", "--plan", str(path))
        self.assertIn(str(holder.pid), str(caught.exception))

    def test_a_stale_lock_is_taken_over(self) -> None:
        """The control: a lock whose holder is gone must not stop the next driver."""
        state = self.root / "state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "driver.lock").write_text(
            json.dumps({"pid": 999_999, "boot_id": self.tool.boot_id(), "marker": "fs_trial.py"}),
            encoding="utf-8",
        )
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)

    def test_the_lock_is_released_by_its_owner(self) -> None:
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        self.assertFalse((self.root / "state" / "driver.lock").exists())


class TheFakeJudgeIsTheRealScorerSPureHalfTests(DryRunCase):
    def test_three_draws_are_three_different_readings_of_one_answer(self) -> None:
        """A fake judge that repeated an identical draw would report a spread of exactly
        0.00 over three of them -- a stochastic judge that resolved every answer
        perfectly, which is the reading this apparatus exists to keep off the page."""
        path = self._plan(tasks=("fs:000",), judge_replicates=3)
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        scores = sorted((self.root / "state" / "scores").glob(f"fs000.{self.control_arm}.*.json"))
        self.assertEqual(len(scores), 3)
        totals = {json.loads(p.read_text(encoding="utf-8"))["total_score"] for p in scores}
        self.assertGreater(len(totals), 1)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("largest observed spread", report)

    def test_one_draw_states_an_unmeasured_spread_and_never_zero(self) -> None:
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("judge sampling noise: **unmeasured (1 draw)**", report)

    def test_the_fake_verdict_goes_through_the_real_grammar(self) -> None:
        """The dry run's totals come out of `draw_record` and `build_result`, so the
        verdict pattern, the draw-failure rules and the aggregation are exercised."""
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        payload = json.loads(
            sorted((self.root / "state" / "scores").glob("*.json"))[0].read_text(encoding="utf-8")
        )
        self.assertEqual(payload["schema"], "fs_score/1")
        self.assertFalse(payload["refused"])
        self.assertEqual(payload["draws"][0]["failures"], [])
        self.assertEqual(payload["draws"][0]["verdict_matches"], 1)
        self.assertIsNone(payload["total_spread"])
        self.assertIn("unmeasured (1 draw)", payload["spread_text"])


class TheRealScorerIsToldWhatThePlanDeclaredTests(DryRunCase):
    def test_the_argv_carries_the_judge_the_plan_names(self) -> None:
        """The knob that did not arrive, on the sibling: a plan declared three replicates
        and the driver built a command line with no ``--draws`` on it, so every score file
        it ever wrote said one."""
        path = self._plan(judge_kind="responses", judge_endpoint="https://example/v1")
        plan = self.tool.load_plan(path)
        seen = {}

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 1, "", "")

        # `patch.object`, not an assignment. `self.tool.subprocess` *is* the stdlib
        # module, so rebinding its `run` and restoring it by hand leaks: the restore
        # argument is evaluated after the rebind, so the cleanup puts the stub back and
        # every later test in the suite that shells out silently receives
        # `returncode == 1`. Measured: twenty-two errors in modules that have nothing to
        # do with this one.
        with mock.patch.object(self.tool.subprocess, "run", fake_run):
            ok = self.tool.score_once(
                plan,
                {"task_key": "fs:000", "workspace": str(self.root), "arm": self.control_arm},
                self.root / "out.json",
            )
        self.assertFalse(ok, "a scorer that writes nothing is not a score")
        argv = seen["argv"]
        self.assertIn("--draws", argv)
        self.assertEqual(argv[argv.index("--draws") + 1], "1")
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-5.1")
        self.assertEqual(argv[argv.index("--reasoning-effort") + 1], "high")
        self.assertEqual(argv[argv.index("--endpoint") + 1], "https://example/v1")
        self.assertIn("score_fs_run.py", " ".join(argv))

    def test_the_agent_is_launched_with_the_reviewer_model_too(self) -> None:
        """`--model` alone leaves the review panels on the backend default, where they
        die without ever being classified as anything."""
        path = self._plan(operator="claude")
        plan = self.tool.load_plan(path)
        argv = self.tool.agent_argv(plan, "fs:000", self.treatment_arm, self.root, 1)
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertEqual(argv[argv.index("--review-model") + 1], "opus")
        self.assertEqual(argv[argv.index("--profile") + 1], "ideate")
        self.assertEqual(argv[argv.index("--answer-guidance") + 1], "minimal")
        self.assertIn(str(self.worktree / "fs_agent.py"), argv)
        # Both arms carry the same denied-tool list, and it is in the digest.
        for arm in (self.control_arm, self.treatment_arm):
            with self.subTest(arm=arm):
                built = self.tool.agent_argv(plan, "fs:000", arm, self.root, 1)
                index = built.index("--disallowed-tools")
                self.assertEqual(built[index + 1: index + 3], ["WebSearch", "WebFetch"])


class TheDriverReadsWhatTheGateAsksAboutTests(DryRunCase):
    def test_harvest_reads_every_fact_a_clause_consults(self) -> None:
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        workspace = Path(self._states()[0]["workspace"])
        facts = self.tool.harvest(workspace, task_key="fs:000")
        for name in (
            "meta_status", "meta_pipeline_completed", "meta_stages_approved",
            "meta_auto_skipped_stages", "meta_answer_source",
            "answer_first_line_is_fallback", "answer_chars", "answer_refusals",
            "operator", "truncated", "browsing_tool_calls", "meta_model",
        ):
            with self.subTest(fact=name):
                self.assertIn(name, facts)
        self.assertTrue(facts["meta_present"])

    def test_a_workspace_with_nothing_in_it_is_a_crash_and_not_a_clean_run(self) -> None:
        """The control for `meta_present`: a truthiness check cannot tell a run that
        wrote nothing from a run that wrote that it failed, and their policies differ."""
        empty = self.root / "empty"
        empty.mkdir()
        facts = self.tool.harvest(empty, task_key="fs:000")
        self.assertFalse(facts["meta_present"])
        self.assertIsNone(facts["answer_first_line_is_fallback"])
        self.assertEqual(self.tool.classify_fs_run(facts), "crashed")

    def test_a_fallback_marker_on_the_first_line_is_seen(self) -> None:
        workspace = self.root / "fallback"
        workspace.mkdir()
        (workspace / "answer.md").write_text(
            f"{self.tool.FS_FALLBACK_MARKER}\n\nnothing\n", encoding="utf-8"
        )
        facts = self.tool.harvest(workspace, task_key="fs:000")
        self.assertTrue(facts["answer_first_line_is_fallback"])


class TheDriverNamesItsOwnChildrenTests(unittest.TestCase):
    def test_the_markers_are_this_driver_s_two_and_not_the_shared_table(self) -> None:
        """A driver that counted another benchmark's agent as one of its own live children
        would read a dead run as running and wait for ever."""
        tool = load_tool()
        self.assertEqual(tool.OUR_RUN_MARKERS, ("fs_agent.py", "fs_trial.py fake-run"))
        from src.trial_driver import AGENT_SCRIPT_NAMES

        self.assertNotEqual(set(tool.OUR_RUN_MARKERS), set(AGENT_SCRIPT_NAMES))

    def test_the_shared_census_knows_this_benchmark_s_front_end(self) -> None:
        """The other direction: a census that has never heard of ``fs_agent.py`` reports
        a clean box beside six live ones and starts a seventh."""
        from src.trial_driver import is_backed_run

        self.assertTrue(is_backed_run(["/usr/bin/python3", "fs_agent.py", "--task", "fs:000"]))
        self.assertFalse(
            is_backed_run(["/usr/bin/python3", "fs_agent.py", "--fake-operator"])
        )
        self.assertFalse(is_backed_run(["/bin/grep", "-rn", "fs_agent.py", "."]))


class EveryDeclaredFlagIsReadTests(unittest.TestCase):
    """The same rule ``tests/test_cli_flags_are_read.py`` applies to the front ends.

    A flag that parses and is then dropped on the floor is silent: it appears in
    ``--help``, the run accepts it, and nothing happens. The driver's ``fake-run``
    subcommand is where that is easiest to do, because every one of its flags exists only
    to make one clause reachable.
    """

    def test_no_flag_of_this_driver_is_parsed_and_never_read(self) -> None:
        import re

        source = TOOL.read_text(encoding="utf-8")
        flags = re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)
        self.assertGreater(len(flags), 10, "the scan found no flags to check")
        unread = [
            flag
            for flag in flags
            if not re.search(rf"\bargs\.{flag[2:].replace('-', '_')}\b", source)
        ]
        self.assertEqual(unread, [])

    def test_the_scan_would_notice_a_dropped_flag(self) -> None:
        """Guards the regex, not the tree: matching too loosely is how this rots green."""
        import re

        fabricated = 'parser.add_argument(\n        "--a-flag-nobody-reads",\n    )'
        self.assertFalse(re.search(r"\bargs\.a_flag_nobody_reads\b", fabricated))


if __name__ == "__main__":
    unittest.main()
