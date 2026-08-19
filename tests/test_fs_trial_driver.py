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

    def test_a_second_workspace_of_the_same_name_is_loud_and_not_shared(self) -> None:
        """`exist_ok=False`, which the test above never reaches.

        `fs_workspace_name` carries microseconds *and* the arm label, so two arms of one
        task always get two names and the flag is never exercised -- flipping it to
        `exist_ok=True` left the suite green, on the sibling driver's worst scar: two arms
        in one directory, overwriting each other's deliverable, a paired difference of
        exactly zero manufactured by a filename. Pinning the name to a constant is the
        only way to reach the collision, and it pins the retry bound at the same time.
        """
        path = self._plan()
        plan = self.tool.load_plan(path)
        calls = []

        def one_name(task, arm):
            calls.append((task, arm))
            return "fs000_direct-opus_collide"

        with mock.patch.object(self.tool, "fs_workspace_name", one_name):
            first = self.tool.make_workspace(plan, "fs:000", self.control_arm)
            with self.assertRaises(SystemExit) as caught:
                self.tool.make_workspace(plan, "fs:000", self.control_arm)
        self.assertIn(str(first), str(caught.exception))
        self.assertIn(str(first.parent), str(caught.exception))
        self.assertIn("fs:000", str(caught.exception))
        self.assertIn(str(self.tool.WORKSPACE_NAME_TRIES), str(caught.exception))
        # Tried the bound and no more: one call for the first workspace, then five.
        self.assertEqual(len(calls), 1 + self.tool.WORKSPACE_NAME_TRIES)

    def test_a_free_name_is_taken_on_the_first_try(self) -> None:
        """The control for the retry bound: an unused name must not cost five attempts."""
        path = self._plan()
        plan = self.tool.load_plan(path)
        calls = []
        real = self.tool.fs_workspace_name

        def counted(task, arm):
            calls.append((task, arm))
            return real(task, arm)

        with mock.patch.object(self.tool, "fs_workspace_name", counted):
            made = self.tool.make_workspace(plan, "fs:000", self.control_arm)
        self.assertTrue(made.is_dir())
        self.assertEqual(len(calls), 1)

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

    def test_an_autor_arm_whose_worktree_is_absent_is_refused_by_name(self) -> None:
        """The shipped plan's failure mode, turned from a traceback into a sentence.

        `configs/fs_trial_001.json` points its treatment arm at
        `/home/robtang_google_com/AutoR-fs-treatment`, which does not exist. `run` used to
        take the lock, create the state directory, write a `launched` state and then die
        at `Popen` with a bare `FileNotFoundError` naming no arm and no path -- under
        `operator: "fake"` as much as under a real one, because the child's cwd is the
        arm's worktree and the revision the gate checks is read out of it with `git`.
        """
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        for item in sorted(self.worktree.rglob("*"), reverse=True):
            item.unlink() if item.is_file() or item.is_symlink() else item.rmdir()
        self.worktree.rmdir()
        with self.assertRaises(SystemExit) as caught:
            self.drive("run", "--plan", str(path))
        message = str(caught.exception)
        self.assertIn(str(self.worktree), message)
        self.assertIn(self.treatment_arm, message)
        self.assertIn("not a directory here", message)
        # And it refused before spending anything: no lock, no run states, no workspaces.
        self.assertFalse((self.root / "state" / "driver.lock").exists())
        self.assertFalse((self.root / "state" / "runs").exists())

    def test_a_present_worktree_is_not_refused(self) -> None:
        """The control. Without it the refusal above would hold for every dry run."""
        path = self._plan(tasks=("fs:000",))
        self.assertEqual(self.tool.missing_worktrees(self.tool.load_plan(path)), [])
        self.drive("plan", "--plan", str(path))
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)

    def test_a_direct_only_plan_needs_no_checkout_at_all(self) -> None:
        """The other control, and the shape of a dry run that really is dry: an arm with
        no worktree is not asked for one."""
        path = self._plan(
            tasks=("fs:000",),
            treatment={
                "label": "direct-sonnet", "kind": "direct", "model": "sonnet",
                "answer_guidance": "minimal",
            },
            control={
                "label": "direct-sonnet-b", "kind": "direct", "model": "sonnet",
                "answer_guidance": "minimal",
            },
            cost_note="Two direct arms; the judge is the only cost.",
        )
        self.assertEqual(self.tool.missing_worktrees(self.tool.load_plan(path)), [])
        self.drive("plan", "--plan", str(path))
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)

    def test_report_still_works_when_the_checkout_is_gone(self) -> None:
        """Why the check is at `run` and not at freeze: a plan is a value, and rebuilding
        an old report must not depend on a worktree somebody has since deleted."""
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        for item in sorted(self.worktree.rglob("*"), reverse=True):
            item.unlink() if item.is_file() or item.is_symlink() else item.rmdir()
        self.worktree.rmdir()
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        self.assertIn("pairs: **1**", (self.root / "state" / "report.md").read_text(encoding="utf-8"))

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


class TheDriverRefusalLedgerIsProducedAndNotOnlyRenderedTests(DryRunCase):
    """`driver_refusals` end to end, against state files the real driver wrote.

    The per-arm death count is the line the report tells a reader to judge the whole
    trial on, and it was produced by a function nothing exercised: the only assertion
    about it hand-constructed an `FsRefusal` and passed it *into* `collect_fs_pairs`, so
    it tested the rendering. Forcing the producer to return ``{}`` left the suite green.

    A dry run never reaches any of the four causes -- the fake operator does not crash,
    stall, fall back or lose a score file -- so each is staged by editing the state
    directory of a *finished* trial and rebuilding the report, which `build_report` is
    documented and separately tested to be a pure function of.
    """

    CAUSES = ("fallback", "stalled", "abandoned", "unscored")

    def _finished_trial(self):
        path = self._plan(tasks=("fs:000", "fs:001", "fs:002", "fs:003"))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        return path, self.tool.load_plan(path)

    def _state(self, plan, task: str, **changes) -> None:
        where = self.tool.state_path(plan, task, self.treatment_arm, 1)
        payload = json.loads(where.read_text(encoding="utf-8"))
        payload.update(changes)
        where.write_text(json.dumps(payload), encoding="utf-8")

    def _drop_scores(self, task: str) -> None:
        slug = task.replace(":", "")
        for path in (self.root / "state" / "scores").glob(f"{slug}.{self.treatment_arm}.*"):
            path.unlink()

    def test_every_driver_cause_reaches_the_ledger_and_the_per_arm_count(self) -> None:
        path, plan = self._finished_trial()
        # A run that answered with the fallback template: it finished, the judge was
        # never spent on it, and it must not read as "no treatment arm".
        self._state(plan, "fs:000", classification="fallback")
        self._drop_scores("fs:000")
        # A run the watchdog killed, refused after its attempt budget.
        self._state(plan, "fs:001", phase="refused", classification="stalled")
        self._drop_scores("fs:001")
        # The driver died between writing the abandonment and planning the replacement.
        self._state(plan, "fs:002", phase="abandoned")
        self._drop_scores("fs:002")
        # Admissible, the final pass has been over it, and no score file exists: every
        # draw failed. A whole trial of these publishes `pairs: 0` with an empty ledger.
        self._drop_scores("fs:003")

        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        for cause in self.CAUSES:
            with self.subTest(cause=cause):
                self.assertIn(f"| `driver:{cause}` | 1 |", report)
                self.assertIn(f"`{self.treatment_arm}`: driver:{cause}", report)
        self.assertIn(f"treatment `{self.treatment_arm}`: **4 refused**, 0 admitted", report)
        self.assertIn(f"control `{self.control_arm}`: **0 refused**, 4 admitted", report)
        # And the ledger's whole point: this is a trial's result, not a footnote.
        self.assertIn("The difference is not published", report)

    def test_an_untouched_trial_carries_no_driver_row(self) -> None:
        """The control. Without it the four rows above could come from anywhere."""
        path, _plan = self._finished_trial()
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertEqual([line for line in report.splitlines() if "| `driver:" in line], [])
        self.assertIn("- no run was refused.", report)

    def test_a_run_in_flight_is_not_an_attrition(self) -> None:
        """`phase == "launched"` is deliberately not a driver refusal: calling a run that
        has not died a death would report every interim trial as attrition."""
        path, plan = self._finished_trial()
        self._state(plan, "fs:000", phase="launched")
        self._drop_scores("fs:000")
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertEqual([line for line in report.splitlines() if "| `driver:" in line], [])

    def test_an_abandoned_attempt_a_later_one_recovered_costs_an_attempt_not_a_pair(self) -> None:
        """The other direction, and the reason the producer de-duplicates by cell.

        `CrashSurvivalTests` leaves exactly this on disk: attempt 1 abandoned, attempt 2
        finished and scored. Counting the abandonment would double the per-arm death
        count the reader is told to judge the trial on.
        """
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        plan = self.tool.load_plan(path)
        stale = self.root / "state" / "workspaces" / "fs000_treatment_stale"
        stale.mkdir(parents=True)
        self.tool.write_json(
            self.tool.state_path(plan, "fs:000", self.treatment_arm, 1),
            {
                "task_key": "fs:000", "arm": self.treatment_arm, "attempt": 1,
                "phase": "launched", "child_pid": 999_999, "workspace": str(stale),
            },
        )
        self.assertEqual(self.drive("run", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("- no run was refused.", report)
        self.assertNotIn("driver:abandoned", report)


class TheEnvironmentIsObservedAndNotCopiedFromThePlanTests(DryRunCase):
    """`FsRunEnvironment`'s central claim, at the two fields where it decides something.

    "Every one is *observed* off the artifacts rather than copied from the plan: a field
    filled from the plan agrees by construction and is therefore not the field the
    contract names." Sourcing `judge_model` from `plan.judge_model` and `dataset_sha256`
    from `plan.dataset_sha256` passed the whole suite -- and under either, the two
    warnings that hang off them become structurally unreachable, because the observation
    *is* the declaration. The pure tests of those warnings build the environment by hand
    and never touch `evidence_for`, which is the wiring that fills it.
    """

    def _finished_trial(self):
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        return path

    def test_a_judge_the_score_files_name_is_read_off_them_and_not_off_the_plan(self) -> None:
        path = self._finished_trial()
        for score in sorted((self.root / "state" / "scores").glob("*.json")):
            payload = json.loads(score.read_text(encoding="utf-8"))
            payload["judge"]["model"] = "gemini-2.5-flash"
            score.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("the judge that ran is not the judge the plan declared", report)
        self.assertIn("`gpt-5.1`", report)
        self.assertIn("gemini-2.5-flash", report)

    def test_a_dataset_the_runs_answered_is_read_off_them_and_not_off_the_plan(self) -> None:
        path = self._finished_trial()
        for where in sorted((self.root / "state" / "runs").glob("*.json")):
            payload = json.loads(where.read_text(encoding="utf-8"))
            payload["meta_dataset_sha256"] = "deadbeef" * 8
            where.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("the runs did not all answer the dataset the plan names", report)
        self.assertIn("deadbeefdeadbeef", report)

    def test_an_unedited_trial_raises_neither_warning(self) -> None:
        """The control for both: the warnings must be about the edit, not about the run."""
        path = self._finished_trial()
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("is not the judge the plan declared", report)
        self.assertNotIn("did not all answer the dataset the plan names", report)
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)

    def test_one_arm_disagreeing_is_enough_for_the_dataset_warning(self) -> None:
        """It is a claim about the population of runs, not about their consensus: two
        files answering to one name is the confound the environment digest cannot
        describe, because both arms would carry it."""
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        where = sorted((self.root / "state" / "runs").glob("*.json"))[0]
        payload = json.loads(where.read_text(encoding="utf-8"))
        payload["meta_dataset_sha256"] = "deadbeef" * 8
        where.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("the runs did not all answer the dataset the plan names", report)


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


class TheJudgeIsSpentOnlyOnCandidateMeasurementsTests(DryRunCase):
    """`final_pass`'s `classification != "ok"` filter, which nothing held.

    Dropping it -- grading every finished run -- left the suite green, and the
    consequence is not only the bill. A `fallback` or `incomplete` run acquires score
    files, becomes an `FsArmEvidence`, reaches the admission gate, and moves out of the
    `driver:fallback` ledger row into an `answer_not_fallback` one: the ledger's two
    populations swap silently, and the judge is paid 72.9 s a call for a non-run.
    """

    def _run_with_a_fallback(self, tasks=("fs:000", "fs:001")):
        path = self._plan(tasks=tasks)
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        plan = self.tool.load_plan(path)
        # Stage the non-run *after* the trial, then reopen it: `build_report` is a pure
        # function of the state directory and `final_pass` skips what it has already
        # scored, so the score files have to go too.
        where = self.tool.state_path(plan, "fs:000", self.treatment_arm, 1)
        payload = json.loads(where.read_text(encoding="utf-8"))
        payload["classification"] = "fallback"
        payload["meta_answer_source"] = "fallback"
        where.write_text(json.dumps(payload), encoding="utf-8")
        for score in (self.root / "state" / "scores").glob(
            f"fs000.{self.treatment_arm}.*"
        ):
            score.unlink()
        (self.root / "state" / "final_pass.json").unlink()
        return path, plan

    def test_a_finished_but_fallback_run_is_never_handed_to_the_judge(self) -> None:
        path, plan = self._run_with_a_fallback()
        self.tool.final_pass(plan)
        written = sorted(
            p.name for p in (self.root / "state" / "scores").glob(f"fs000.{self.treatment_arm}.*")
        )
        self.assertEqual(written, [], "the judge was spent on a run that is not a measurement")
        # The control arm of the same task was untouched and is still scored, so the
        # assertion above is about the classification and not about the task.
        self.assertTrue(
            sorted((self.root / "state" / "scores").glob(f"fs000.{self.control_arm}.*"))
        )

    def test_the_non_run_stays_in_the_driver_row_and_never_reaches_a_clause(self) -> None:
        path, plan = self._run_with_a_fallback()
        self.tool.final_pass(plan)
        self.assertEqual(self.drive("report", "--plan", str(path)), 0)
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `driver:fallback` | 1 |", report)
        self.assertIn(f"`fs:000` / `{self.treatment_arm}`: driver:fallback", report)
        # The two populations the filter keeps apart: a non-run must not be counted as a
        # run the gate looked at and refused.
        self.assertIn("| `answer_not_fallback` | 0 |", report)

    def test_an_ok_run_the_final_pass_has_not_seen_is_graded(self) -> None:
        """The control: the filter must not be a synonym for "grade nothing"."""
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        plan = self.tool.load_plan(path)
        for score in (self.root / "state" / "scores").glob("*.json"):
            score.unlink()
        self.tool.final_pass(plan)
        self.assertEqual(len(sorted((self.root / "state" / "scores").glob("*.json"))), 2)


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


class TheControlArmReachesTheChildCommandTests(DryRunCase):
    """``--no-forced-skills`` exists to be an arm, and an arm has to be launchable.

    Both command builders are checked, because there are two and the dry run uses the one
    that is easier to forget: a real trial of the withheld configuration cannot be
    rehearsed on this box -- no real AutoR run of this benchmark exists -- so a fake
    branch that could not express it would leave the arm reachable only from a hand-written
    argv in a test.
    """

    def _withheld(self, **overrides):
        """A plan whose `autor` arm is launched without the five skills.

        Both arms have to agree about it, so the control becomes a second `autor` arm --
        a `direct` arm has no run directory to install a skill into and can never be the
        one holding them back.
        """
        return self._plan(
            control={
                "label": "aaaaaaa-autor-ideate", "kind": "autor", "model": "opus",
                "answer_guidance": "minimal", "worktree": str(self.worktree),
                "sha": "aaaaaaa", "review_model": "opus", "profile": "ideate",
                "forced_skills": False,
            },
            treatment={
                "label": f"{self.sha[:7]}-autor-ideate", "kind": "autor", "model": "opus",
                "answer_guidance": "minimal", "worktree": str(self.worktree),
                "sha": self.sha[:7], "review_model": "opus", "profile": "ideate",
                "forced_skills": False,
            },
            **overrides,
        )

    def test_the_flag_is_rendered_when_the_arm_withholds_the_skills(self) -> None:
        for operator in ("claude", "fake"):
            with self.subTest(operator=operator):
                plan = self.tool.load_plan(self._withheld(operator=operator))
                argv = self.tool.agent_argv(
                    plan, "fs:000", plan.treatment.label, self.root, 1
                )
                self.assertIn("--no-forced-skills", argv)

    def test_the_flag_is_absent_when_the_arm_keeps_them(self) -> None:
        """The control. A driver that always passed it would run two control arms and
        report the difference between them as the effect of the pipeline."""
        for operator in ("claude", "fake"):
            with self.subTest(operator=operator):
                plan = self.tool.load_plan(self._plan(operator=operator))
                for arm in (self.control_arm, self.treatment_arm):
                    argv = self.tool.agent_argv(plan, "fs:000", arm, self.root, 1)
                    self.assertNotIn("--no-forced-skills", argv)

    def test_the_flag_is_the_last_word_after_the_denied_tool_list(self) -> None:
        """``--disallowed-tools`` takes as many values as it is given, and a flag appended
        behind it has to end the list rather than join it."""
        plan = self.tool.load_plan(self._withheld(operator="claude"))
        argv = self.tool.agent_argv(plan, "fs:000", plan.treatment.label, self.root, 1)
        import fs_agent

        index = argv.index("--disallowed-tools")
        self.assertEqual(argv[index + 1: index + 3], ["WebSearch", "WebFetch"])
        # Parsed by the binary that will receive it, not by this test's idea of it.
        parsed = fs_agent.parse_args(argv[2:])
        self.assertTrue(parsed.no_forced_skills)
        self.assertEqual(parsed.disallowed_tools, ["WebSearch", "WebFetch"])
        self.assertFalse(
            fs_agent.parse_args(
                self.tool.agent_argv(
                    self.tool.load_plan(self._plan(operator="claude")),
                    "fs:000", self.treatment_arm, self.root, 1,
                )[2:]
            ).no_forced_skills
        )

    def test_a_fabricated_run_records_what_it_was_and_was_not_given(self) -> None:
        """The dry run's own metadata, through the real builder, in all three shapes."""
        cases = {
            "forced": (["--kind", "autor"], list(self.tool._FAKE_FORCED_SKILLS), []),
            "withheld": (
                ["--kind", "autor", "--no-forced-skills"],
                [],
                list(self.tool._FAKE_FORCED_SKILLS),
            ),
            "direct": (["--kind", "direct"], [], []),
        }
        for name, (argv, forced, withheld) in cases.items():
            with self.subTest(arm=name):
                workspace = self.root / f"fake-{name}"
                self.drive(
                    "fake-run", "--workspace", str(workspace), "--task", "fs:000",
                    "--arm", name, *argv,
                )
                meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
                self.assertEqual(meta["skill_forced"], sorted(forced))
                self.assertEqual(meta["skill_withheld"], sorted(withheld))

    def test_the_recorded_set_is_canonical_and_not_the_order_it_was_built_in(self) -> None:
        """The control for the two `sorted` calls: a set has no order, and an order
        carried into the digest would report one configuration as two."""
        self.assertNotEqual(
            list(self.tool._FAKE_FORCED_SKILLS), sorted(self.tool._FAKE_FORCED_SKILLS)
        )

    def test_the_withheld_set_reaches_the_environment_the_pairs_are_keyed_on(self) -> None:
        """End to end: the driver reads it off `_meta.json` and folds it into the digest."""
        path = self._withheld(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        plan = self.tool.load_plan(path)
        for state in self._states():
            with self.subTest(arm=state["arm"]):
                self.assertEqual(
                    state["meta_skill_withheld"], sorted(self.tool._FAKE_FORCED_SKILLS)
                )
                evidence = self.tool.evidence_for(plan, state)
                self.assertEqual(
                    evidence.env.skill_withheld,
                    tuple(sorted(self.tool._FAKE_FORCED_SKILLS)),
                )

    def test_the_shipped_shape_still_pairs_with_the_field_in_the_digest(self) -> None:
        """The blast radius of putting a skill set in the environment digest, measured.

        The trial this benchmark runs pairs a `direct` control against a forced `ideate`
        treatment. The control installs nothing without having been denied anything, so
        the two agree and the pair survives -- which is the whole reason the *withheld*
        set is the field and the installed one is not.
        """
        path = self._plan(tasks=("fs:000",))
        self.drive("plan", "--plan", str(path))
        self.drive("run", "--plan", str(path))
        metas = {}
        for state in self._states():
            metas[state["arm"]] = json.loads(
                (Path(state["workspace"]) / "_meta.json").read_text(encoding="utf-8")
            )
        self.assertEqual(
            metas[self.treatment_arm]["skill_forced"],
            sorted(self.tool._FAKE_FORCED_SKILLS),
        )
        self.assertEqual(metas[self.control_arm]["skill_forced"], [])
        for arm, meta in metas.items():
            with self.subTest(arm=arm):
                self.assertEqual(meta["skill_withheld"], [])
        report = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        self.assertIn("pairs: **1**", report)


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
