"""The driver: the lock, the state, and one whole trial end to end without spending it.

A four-hour task per run and six runs per trial means the recovery logic gets exercised
for real perhaps twice, days apart, under conditions nobody can reproduce. So the
policy is a pure function tested in :mod:`tests.test_rcb_trial`, and what is left here
is the machinery that touches processes and files — which is tested by running it, on a
fabricated operator and a fabricated judge, against a fabricated benchmark checkout.

The dry run is not a mock of the driver. It is the driver: the real lock, real
``Popen(start_new_session=True)`` children, real atomic state writes, the real stall
watchdog, the real admission gate and the real report. Only the four hours and the
judge's bill are fake.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "rcb_trial.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("rcb_trial_tool", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


CHECKLIST = [
    {"content": "a curve of X against Y", "type": "image", "weight": 0.5, "path": "f1.png"},
    {"content": "the coupling limit in GeV^-1", "type": "text", "weight": 0.3},
    {"content": "the significance of the result", "type": "text", "weight": 0.2},
]


def make_bench(root: Path, task: str = "Energy_001") -> Path:
    bench = root / "bench"
    study = bench / "tasks" / task / "target_study"
    study.mkdir(parents=True)
    (study / "checklist.json").write_text(json.dumps(CHECKLIST), encoding="utf-8")
    (bench / "tasks" / task / "data").mkdir()
    (bench / "tasks" / task / "data" / "x.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (bench / "tasks" / task / "task_info.json").write_text(
        json.dumps({"task_description": "do the thing"}), encoding="utf-8"
    )
    return bench


def make_worktree(root: Path, name: str, agent_body: str = "# placeholder\n") -> tuple[Path, str]:
    """A real git checkout, because the revision clause reads a real ``rev-parse``.

    ``agent_body`` is the worktree's ``rcb_agent.py``. The real (non-fake) operator branch
    launches exactly that file, so a test that wants to see the argv the driver would
    really build has to have something there that runs.
    """
    path = root / name
    path.mkdir()
    (path / "rcb_agent.py").write_text(agent_body, encoding="utf-8")
    run = lambda *args: subprocess.run(  # noqa: E731
        ["git", "-C", str(path), *args], capture_output=True, text=True, check=True
    )
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("add", "-A")
    run("commit", "-q", "-m", name)
    sha = run("rev-parse", "HEAD").stdout.strip()
    return path, sha


class LockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_the_lock_is_taken_with_link_and_not_with_exclusive_create(self) -> None:
        """``O_CREAT|O_EXCL`` is not reliably atomic on NFS; ``os.link`` is, and the
        state directory sits on shared NFS by design.

        Two files, because the lock moved to :mod:`src.trial_driver` when a second
        benchmark needed the same driver and the shared kernel is now where the
        primitive has to be right. ``TOOL`` stays in the population rather than being
        swapped out: a driver that grows its own second lock -- the obvious thing to
        write on the day a trial is stuck -- is exactly what this refuses, and dropping
        the file from the scan would stop refusing it.
        """
        kernel = (REPO_ROOT / "src" / "trial_driver.py").read_text(encoding="utf-8")
        self.assertIn("os.link(", kernel)
        for body in (kernel, TOOL.read_text(encoding="utf-8")):
            self.assertNotIn("os.open(", body)

    def test_a_second_driver_is_refused_while_the_first_is_alive(self) -> None:
        # A real live process whose command line looks like a driver. A synthetic pid
        # would be indistinguishable from the stale case the next test covers.
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "tools/rcb_trial.py"]
        )
        self.addCleanup(holder.kill)
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "driver.lock").write_text(
            json.dumps({"pid": holder.pid, "boot_id": self.tool.boot_id()}), encoding="utf-8"
        )
        with self.assertRaises(SystemExit) as caught:
            self.tool.acquire_lock(self.state, marker="rcb_trial.py")
        self.assertIn(str(holder.pid), str(caught.exception))

    def test_a_stale_lock_is_taken_over(self) -> None:
        (self.state).mkdir(parents=True, exist_ok=True)
        (self.state / "driver.lock").write_text(
            json.dumps({"pid": 999999, "boot_id": self.tool.boot_id()}), encoding="utf-8"
        )
        self.tool.acquire_lock(self.state, marker="rcb_trial.py")
        self.assertEqual(
            json.loads((self.state / "driver.lock").read_text(encoding="utf-8"))["pid"],
            os.getpid(),
        )

    def test_two_drivers_cannot_both_take_over_one_stale_lock(self) -> None:
        """The takeover has to be as atomic as the creation, and it was not.

        On ``FileExistsError`` the driver read the lock, tested liveness and then
        ``os.replace``d it: two drivers that both read the same stale lock both replaced
        it and both proceeded. A stale lock is not the exotic case — it is what ``kill
        -9`` on a ``setsid`` driver leaves behind, i.e. the "I killed it and relaunched"
        case the whole design is bent around, and it was reproduced at two races in five.
        """
        self.state.mkdir(parents=True, exist_ok=True)
        lock = self.state / "driver.lock"
        stale = {"pid": 999999, "boot_id": self.tool.boot_id(), "started_at": 1.0}
        lock.write_text(json.dumps(stale), encoding="utf-8")

        first, second = self.state / "tmp.a", self.state / "tmp.b"
        first.write_text('{"pid": 1}', encoding="utf-8")
        second.write_text('{"pid": 2}', encoding="utf-8")

        self.assertTrue(self.tool.claim_stale_lock(self.state, stale, first, lock))
        self.assertFalse(
            self.tool.claim_stale_lock(self.state, stale, second, lock),
            "both drivers took over one stale lock, and both will now hit Vertex",
        )
        self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["pid"], 1)

    def test_the_driver_that_loses_the_takeover_stands_down(self) -> None:
        """Losing the race has to end the process, not fall through into the trial."""
        self.state.mkdir(parents=True, exist_ok=True)
        stale = {"pid": 999999, "boot_id": self.tool.boot_id(), "started_at": 1.0}
        (self.state / "driver.lock").write_text(json.dumps(stale), encoding="utf-8")
        # The token a rival driver leaves behind when it wins the takeover.
        (self.state / "driver.lock.taken.999999.1.0").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.tool.acquire_lock(self.state, marker="rcb_trial.py")
        self.assertIn("standing down", str(caught.exception))
        self.assertEqual(
            json.loads((self.state / "driver.lock").read_text(encoding="utf-8"))["pid"], 999999
        )

    def test_liveness_needs_the_pid_the_cmdline_and_the_boot_id(self) -> None:
        """Each on its own gives a wrong answer.

        A pid is reused. A cmdline cannot be read for a pid that is gone. And after a
        reboot a live pid with a matching cmdline can be somebody else entirely, which
        is the case the boot id exists for.
        """
        live = {"pid": os.getpid(), "boot_id": self.tool.boot_id()}
        self.assertTrue(self.tool.lock_is_live(live, marker="python"))
        self.assertFalse(self.tool.lock_is_live({**live, "pid": 999999}, marker="python"))
        self.assertFalse(self.tool.lock_is_live(live, marker="definitely-not-in-cmdline"))
        self.assertFalse(
            self.tool.lock_is_live({**live, "boot_id": "0000-stale"}, marker="python")
        )

    def test_the_lock_is_only_released_by_its_owner(self) -> None:
        lock = self.tool.acquire_lock(self.state, marker="rcb_trial.py")
        payload = json.loads(lock.read_text(encoding="utf-8"))
        payload["pid"] = 999999
        lock.write_text(json.dumps(payload), encoding="utf-8")
        self.tool.release_lock(lock)
        self.assertTrue(lock.exists(), "released another driver's lock")


class StateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_state_is_replaced_and_never_truncated(self) -> None:
        """A half-written state file after a kill is a run that cannot be classified."""
        path = self.root / "runs" / "a.json"
        self.tool.write_json(path, {"a": 1})
        self.tool.write_json(path, {"a": 2})
        self.assertEqual(self.tool.read_json(path), {"a": 2})
        self.assertEqual(list((self.root / "runs").glob("*.tmp*")), [])

    def test_the_web_search_level_is_read_from_the_progress_event(self) -> None:
        """Not from ``run_config.json``, which records the request (``"auto"``).

        The same command line produced ``info`` twice and ``warn`` once here, the warn
        being a run whose Stage 01 could not search at all.
        """
        log = self.root / "out.log"
        log.write_text(
            '{"type":"system","subtype":"init"}\n'
            '{"type":"progress","stage":"web_search","level":"warn"}\n',
            encoding="utf-8",
        )
        self.assertEqual(self.tool.search_level(log), "warn")

    def test_the_requested_web_search_mode_is_harvested_beside_the_resolved_level(self) -> None:
        """``off`` and a working ``auto`` both announce themselves at ``level: info``.

        The level is the resolved answer and the only thing the progress event carries,
        so once `rcb_agent.py` began accepting ``--web-search off`` an arm told not to
        browse and an arm that browsed freely produced the same one. The request is in
        ``run_config.json``, and reading it is what keeps the two apart in the digest.
        """
        workspace = self.root / "asked_for_off"
        root = workspace / ".autor" / "r1"
        root.mkdir(parents=True)
        (root / "run_config.json").write_text(
            json.dumps({"model": "opus", "web_search": "off"}), encoding="utf-8"
        )
        log = self.root / "off.log"
        log.write_text(
            '{"type":"progress","stage":"web_search","level":"info"}\n', encoding="utf-8"
        )

        facts = self.tool.harvest(workspace, log)
        self.assertEqual(facts["web_search_mode"], "off")
        self.assertEqual(facts["web_search_level"], "info")

    def test_a_run_whose_config_never_named_a_mode_reports_no_mode(self) -> None:
        """Control, and the shape of the field on every run recorded before this.

        A missing key must read as unknown rather than as the default: an arm harvested
        from a workspace with no ``run_config.json`` has not been observed to have asked
        for ``auto``, and writing ``auto`` in would let it pair with an arm that did.
        """
        workspace = self.root / "no_config"
        (workspace / ".autor" / "r1").mkdir(parents=True)

        self.assertEqual(self.tool.harvest(workspace)["web_search_mode"], "")

    def test_a_log_with_no_progress_event_yields_no_level_rather_than_a_guess(self) -> None:
        log = self.root / "out.log"
        log.write_text("nothing here\n", encoding="utf-8")
        self.assertEqual(self.tool.search_level(log), "")

    def test_harvest_counts_the_things_the_gate_asks_about(self) -> None:
        workspace = self.root / "ws"
        (workspace / "outputs" / "figures").mkdir(parents=True)
        (workspace / "outputs" / "figures" / "a.png").write_bytes(b"x")
        (workspace / "report").mkdir()
        (workspace / "report" / "report.md").write_text("r", encoding="utf-8")
        (workspace / "report" / "draft.md").write_text("d", encoding="utf-8")
        (workspace / ".autor" / "r1").mkdir(parents=True)
        (workspace / ".autor" / "r2").mkdir(parents=True)
        (workspace / "_meta.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")

        facts = self.tool.harvest(workspace)
        self.assertEqual(facts["images_under_outputs"], 1)
        self.assertEqual(facts["report_md_count"], 2)
        self.assertTrue(facts["report_md_present"])
        self.assertEqual(facts["autor_run_count"], 2)
        self.assertEqual(facts["meta_status"], "running")

    def test_harvest_names_report_md_rather_than_counting_markdown(self) -> None:
        """A lone ``draft.md`` counts one and is not the deliverable.

        ``score.py`` globs ``report/*.md`` unsorted when ``report.md`` is absent, so a
        count of one is satisfied by the very workspace the clause exists to catch. The
        clause reads two facts; a test that only exercises the clause leaves the
        producer of the second one free to return a constant.
        """
        workspace = self.root / "leftover"
        (workspace / "report").mkdir(parents=True)
        (workspace / "report" / "draft.md").write_text("d", encoding="utf-8")

        facts = self.tool.harvest(workspace)
        self.assertEqual(facts["report_md_count"], 1)
        self.assertFalse(facts["report_md_present"])

    def test_harvest_reports_no_report_md_when_the_report_dir_is_empty(self) -> None:
        workspace = self.root / "empty"
        (workspace / "report").mkdir(parents=True)

        facts = self.tool.harvest(workspace)
        self.assertEqual(facts["report_md_count"], 0)
        self.assertFalse(facts["report_md_present"])

    def test_harvest_reads_the_four_facts_a_quota_death_is_visible_in(self) -> None:
        """The other half of the gate's inputs, and the half only a dead run exercises.

        A run killed by quota reports ``status: completed`` and exports a fallback
        report, so the four clauses that can tell it from a real run all read fields the
        happy path never varies: ``report_source``, ``pipeline_completed``,
        ``last_event`` and the count of quota markers in the run's own log. Each of them
        could be replaced by its healthy constant with the whole suite green, and the
        end-to-end dry run cannot see it — the fake operator writes ``report_source:
        "agent"``, so that assertion agrees by construction with a hardcoded ``"agent"``.
        """
        workspace = self.root / "dead"
        (workspace / "report").mkdir(parents=True)
        (workspace / "_meta.json").write_text(
            json.dumps(
                {
                    "status": "completed", "report_source": "fallback",
                    "pipeline_completed": False, "task_id": "Energy_001",
                }
            ),
            encoding="utf-8",
        )
        root = workspace / ".autor" / "r1"
        root.mkdir(parents=True)
        (root / "run_manifest.json").write_text(
            json.dumps({"run_status": "failed", "last_event": "run.backend_unavailable"}),
            encoding="utf-8",
        )
        (root / "logs.txt").write_text(
            "API Error: 429 RESOURCE_EXHAUSTED for claude-sonnet-4-5\n", encoding="utf-8"
        )

        facts = self.tool.harvest(workspace)
        self.assertEqual(facts["meta_report_source"], "fallback")
        self.assertIs(facts["meta_pipeline_completed"], False)
        self.assertEqual(facts["last_event"], "run.backend_unavailable")
        self.assertEqual(facts["resource_exhausted_hits"], 1)

    def test_harvest_keeps_the_task_id_of_a_run_that_never_wrote_its_meta(self) -> None:
        """``rcb_agent.py`` writes ``_meta.json`` once, at the very end.

        So every run the stall watchdog killed — the case the watchdog exists for — has
        none, and reading the id out of a file that is not there returns ``None``.
        ``next_action`` keys on ``(task_id, arm)``, so that does not lose one field: it
        makes the whole attempt invisible to the planner.
        """
        workspace = self.root / "killed"
        workspace.mkdir()
        self.assertEqual(
            self.tool.harvest(workspace, task_id="Energy_001")["task_id"], "Energy_001"
        )

    def test_the_instructions_digest_holds_the_file_and_not_just_its_presence(self) -> None:
        """Normalise the workspace path out, hold everything else byte for byte.

        The path is in the file by construction and the two arms are in different
        directories by design, so digesting it raw reported every pair as an environment
        difference. But the point of the digest is that the two arms were handed the same
        background: the benchmark is a live checkout, ``INSTRUCTIONS.md`` is re-rendered
        at each launch, and a ``task_description`` edited between two runs days apart has
        to fire.
        """
        first, second, third = (self.root / name for name in ("a", "b", "c"))
        for path in (first, second, third):
            path.mkdir()
        for path, task in ((first, "do it"), (second, "do it"), (third, "do it well")):
            (path / "INSTRUCTIONS.md").write_text(
                f"# Task\n\n{task}\n\nWorkspace: {path}\n", encoding="utf-8"
            )

        self.assertEqual(
            self.tool.instructions_digest(first), self.tool.instructions_digest(second)
        )
        self.assertNotEqual(
            self.tool.instructions_digest(first),
            self.tool.instructions_digest(third),
            "a changed task description is not an environment difference",
        )
        self.assertEqual(self.tool.instructions_digest(self.root / "gone"), "")

    def test_the_heartbeat_is_the_raw_log_and_nothing_else(self) -> None:
        """``run_manifest.json`` updates on stage transitions — one healthy run was
        eight minutes stale — and ``_meta.json`` is written once, at the end."""
        workspace = self.root / "ws"
        (workspace / ".autor" / "r1").mkdir(parents=True)
        self.assertEqual(self.tool.heartbeat(workspace), 0.0)
        (workspace / ".autor" / "r1" / "logs_raw.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertGreater(self.tool.heartbeat(workspace), 0.0)

    def test_a_block_of_rejected_ideas_alone_is_a_dose_of_the_channel(self) -> None:
        """Built by the real ``build_block``, rendered by the real channel.

        The dose detector is the only thing that tells "the channel was administered and
        did nothing" from "the channel was never administered", which is the trial's whole
        interpretive claim about change (b). It looked for ``build_block``'s crux
        sub-heading, which is emitted inside ``if cruxes:`` — so a block made of rejected
        idea-pool candidates alone, one of the two things the channel routes, is a real
        delivered dose that reads as zero and gets the pair thrown away as "not a test of
        it".
        """
        from src.information_flow import CHANNELS, _render
        from src.settled_reasoning import build_block
        from src.utils import build_run_paths

        paths = build_run_paths(self.root / "run")
        paths.reviews_dir.mkdir(parents=True, exist_ok=True)
        (paths.reviews_dir / "idea_pool.json").write_text(
            json.dumps(
                {
                    "candidates": [
                        {
                            "idea_id": "i1",
                            "title": "Spectral clustering baseline",
                            "statement": "Cluster the residuals before fitting.",
                            "proposer_title": "statistics",
                            "adopted": False,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        block = build_block(paths)
        self.assertIsNotNone(block, "a rejected candidate is material the channel sends")
        self.assertNotIn("Methodological questions this run settled", block)

        channel = next(item for item in CHANNELS if item.key == "settled_reasoning")
        workspace = self.root / "ws-dose"
        cache = workspace / ".autor" / "r1" / "prompt_cache"
        cache.mkdir(parents=True)
        (cache / "07_report_attempt_01.prompt.md").write_text(
            _render(block, channel), encoding="utf-8"
        )
        self.assertTrue(
            self.tool.harvest(workspace, task_id="Energy_001")["settled_reasoning_dose"]
        )

    def test_the_launch_state_is_on_disk_before_the_child_exists(self) -> None:
        """A ``kill -9`` must cost the run in flight and nothing else, which means the
        state cannot be written after the process it describes."""
        from src.rcb_trial import ArmSpec, TrialPlan

        bench = make_bench(self.root)
        worktree, sha = make_worktree(self.root, "wt")
        plan = TrialPlan(
            capability="c", bench=str(bench), tasks=("Energy_001",),
            control=ArmSpec(sha[:7], str(worktree), sha[:7]),
            treatment=ArmSpec("other", str(worktree), "other"),
            state_dir=str(self.root / "state"), operator="fake", judge_kind="fake",
        )
        seen: list[bool] = []
        real = subprocess.Popen

        def spy(*args, **kwargs):
            # `git rev-parse` also goes through Popen; only the operator launch counts.
            if any("fake-run" in str(part) for part in (args[0] if args else [])):
                seen.append(self.tool.state_path(plan, "Energy_001", sha[:7], 1).exists())
            return real(*args, **kwargs)

        self.tool.subprocess.Popen = spy
        try:
            self.tool.launch(plan, "Energy_001", sha[:7], 1)
        finally:
            self.tool.subprocess.Popen = real
        self.assertEqual(seen, [True])


#: An operator that records the command line it was given and stops. The real launch
#: branch is otherwise unreachable from a test — every dry run sets ``operator: "fake"``,
#: which builds a completely different argv — and what it carries is fact one: the
#: reviewer model resolves independently of the operator's, so ``--model opus`` alone
#: leaves the panels on the exhausted sonnet pool, where they die mid-stage without ever
#: being classified as a quota failure.
AGENT_THAT_RECORDS_ITS_ARGV = """
import json, sys
from pathlib import Path
workspace = Path(sys.argv[sys.argv.index("--workspace") + 1])
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "argv.json").write_text(json.dumps(sys.argv), encoding="utf-8")
"""

#: An operator that dies before writing ``_meta.json`` — which ``rcb_agent.py`` writes
#: once, at the very end, so this is every stalled, killed or crashed run.
AGENT_THAT_DIES = "import sys\nsys.exit(3)\n"


class RealOperatorTests(unittest.TestCase):
    """The launch branch the dry run never takes.

    ``operator: "fake"`` builds its own argv and its own workspace, so everything the
    real branch does — the models it passes, and what the state file records when the run
    it launched leaves nothing behind — is invisible to every other test here.
    """

    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bench = make_bench(self.root)

    def _plan(self, agent_body: str):
        from src.rcb_trial import ArmSpec, TrialPlan

        worktree, sha = make_worktree(self.root, "wt", agent_body)
        return TrialPlan(
            capability="pr175",
            bench=str(self.bench),
            tasks=("Energy_001",),
            control=ArmSpec(sha[:7], str(worktree), sha[:7]),
            treatment=ArmSpec("other", str(worktree), "other"),
            state_dir=str(self.root / "state"),
            operator="autor",
            judge_kind="fake",
            agent_model="claude-opus-4-5",
            review_model="claude-opus-4-5-reviewer",
        ), sha[:7]

    def test_the_real_operator_is_launched_with_the_reviewer_model_too(self) -> None:
        """Fact one, and the flag nothing held.

        Vertex quota is per-base-model: sonnet is routinely exhausted while opus has
        headroom, and AutoR resolves the reviewer/panel model independently of the
        operator's. Without this flag every run in the plan launches ``--model opus``
        with the panels left on the exhausted pool; they die mid-stage, ``classify_backend``
        never fires because it only runs when neither attempt wrote a stage file, and both
        arms score a degraded report the gate admits.
        """
        plan, arm = self._plan(AGENT_THAT_RECORDS_ITS_ARGV)
        state = self.tool.launch(plan, "Energy_001", arm, 1)
        argv = json.loads(
            (Path(state["workspace"]) / "argv.json").read_text(encoding="utf-8")
        )
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-4-5")
        self.assertIn("--review-model", argv)
        self.assertEqual(
            argv[argv.index("--review-model") + 1], "claude-opus-4-5-reviewer",
            "the panels were left to resolve their own model",
        )
        self.assertTrue(argv[0].endswith("rcb_agent.py"), argv)

    def test_a_run_that_died_before_writing_its_meta_keeps_its_identity(self) -> None:
        """Otherwise the attempt is invisible and the driver relaunches it forever.

        ``harvest`` read ``task_id`` out of ``_meta.json`` with no fallback and ``launch``
        let that overwrite the id it launched with, so a run that died early recorded
        ``task_id: null``. ``next_action`` keys on ``(task_id, arm)``: it then sees no
        attempts for this arm, returns ``launch attempt 1``, overwrites its own state file
        and does it again — reproduced at twelve relaunches in thirteen seconds, and in
        production each cycle costs a stall timeout plus a whole opus run. ``MAX_ATTEMPTS``
        is never consulted, so the pair is never refused.
        """
        from src.rcb_trial import next_action

        plan, arm = self._plan(AGENT_THAT_DIES)
        state = self.tool.launch(plan, "Energy_001", arm, 1)
        self.assertEqual(state["task_id"], "Energy_001")
        self.assertEqual(state["classification"], "incomplete")

        states = self.tool.all_states(plan)
        self.assertEqual(next_action(plan, states, now=0.0).kind, "refuse")
        # Isolated to the one field: the same state with the id lost relaunches instead.
        blinded = [{**item, "task_id": None} for item in states]
        self.assertEqual(
            (next_action(plan, blinded, now=0.0).kind, next_action(plan, blinded, now=0.0).attempt),
            ("launch", 1),
        )


class RealScorerArgvTests(unittest.TestCase):
    """The scoring branch the dry run never takes, for the same reason.

    Every test sets ``judge_kind: "fake"``, which returns on the line above the two rules
    that decide what the number means: which judge produced it, and which five images
    every image criterion was shown.
    """

    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _capture(self, plan, out: Path) -> dict:
        seen: dict = {}
        real = self.tool.subprocess.run

        def spy(argv, env=None, **kwargs):
            seen["argv"] = list(argv)
            seen["env"] = dict(env or {})
            Path(argv[argv.index("--out") + 1]).parent.mkdir(parents=True, exist_ok=True)
            Path(argv[argv.index("--out") + 1]).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")

        self.tool.subprocess.run = spy
        try:
            seen["ok"] = self.tool.score_once(
                plan, {"workspace": str(self.root / "ws")}, out
            )
        finally:
            self.tool.subprocess.run = real
        return seen

    def plan(self):
        from src.rcb_trial import ArmSpec, TrialPlan

        return TrialPlan(
            capability="pr175", bench=str(self.root / "bench"), tasks=("Energy_001",),
            control=ArmSpec("c", "/wt/c", "c"), treatment=ArmSpec("t", "/wt/t", "t"),
            judge_kind="reference", judge_model="gpt-5.1",
            state_dir=str(self.root / "state"),
        )

    def test_the_scorer_is_told_which_judge_to_use(self) -> None:
        """Without it ``score_rcb_run.py`` falls back to its own default model, and the
        report header prints the plan's declaration either way. Judge choice is worth
        about sixteen points on identical artifacts, so that header would be stating a
        number's provenance that nothing observed."""
        plan = self.plan()
        seen = self._capture(plan, self.root / "state" / "scores" / "s.json")
        self.assertTrue(seen["ok"])
        argv = seen["argv"]
        self.assertIn("score_rcb_run.py", " ".join(argv))
        self.assertEqual(argv[argv.index("--model") + 1], "gpt-5.1")
        self.assertEqual(argv[argv.index("--judge") + 1], "reference")

    def test_the_scorer_runs_with_a_pinned_hash_seed(self) -> None:
        """The benchmark's ``IMAGE_EXTENSIONS`` is a ``set``, and which five images each
        image criterion is shown is read off a list built by iterating it. This narrows
        that variance across 60.6% of the benchmark's weight; it does not remove it,
        because ``rglob``'s order is not pinned by anything."""
        seen = self._capture(self.plan(), self.root / "state" / "scores" / "s.json")
        self.assertEqual(seen["env"].get("PYTHONHASHSEED"), "0")

    def test_a_scorer_that_writes_nothing_is_not_a_score(self) -> None:
        """``score_rcb_run.py`` exits 1 and writes no ``--out`` when a judge call failed
        or the item count is short. That refusal is inherited, not reimplemented."""
        plan = self.plan()
        real = self.tool.subprocess.run
        self.tool.subprocess.run = lambda argv, env=None, **kw: subprocess.CompletedProcess(
            argv, 1, "", "refused"
        )
        try:
            self.assertFalse(
                self.tool.score_once(plan, {"workspace": str(self.root / "ws")},
                                     self.root / "state" / "scores" / "s.json")
            )
        finally:
            self.tool.subprocess.run = real


class EvidenceTests(unittest.TestCase):
    """That the environment is *read off the run*, which nothing tested.

    Every test of :class:`RunEnvironment` builds one by hand, and the dry run gives both
    arms an identical environment, so neither can see the producer. Each of the seven
    fields could be replaced by ``""`` with the whole suite green — and with all seven
    blank the digest is a constant, the stage key is the same twelve characters in both
    arms, and the composition refusal the whole design rests on excludes nothing.
    """

    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.bench = make_bench(self.root)

    def plan(self, **overrides):
        from src.rcb_trial import ArmSpec, TrialPlan

        base = dict(
            capability="pr175", bench=str(self.bench), tasks=("Energy_001",),
            control=ArmSpec("621566b", "/wt/c", "621566b"),
            treatment=ArmSpec("47f3fbf", "/wt/t", "47f3fbf"),
            state_dir=str(self.root / "state"), replicates=2, judge_kind="fake",
        )
        base.update(overrides)
        return TrialPlan(**base)

    def state(self, arm: str, **overrides) -> dict:
        payload = {
            "task_id": "Energy_001", "arm": arm, "attempt": 1, "phase": "finished",
            "workspace": f"/ws/{arm}", "run_id": f"run-{arm}",
            "agent_model": "claude-opus-4-5", "review_model": "claude-sonnet-4-5",
            "web_search_level": "warn", "web_search_mode": "auto",
            "instructions_digest": "ins-digest",
            "meta_status": "completed", "meta_pipeline_completed": True,
            "meta_report_source": "agent", "autor_run_count": 1,
            "images_under_outputs": 0, "report_md_count": 1,
            "report_md_present": True,
            "last_event": "run.completed", "resource_exhausted_hits": 0,
            "revision_at_launch": arm + "0" * 33, "revision_at_finish": arm + "0" * 33,
            "worktree_dirty_at_launch": False, "worktree_dirty_at_finish": False,
            "classification": "ok",
        }
        payload.update(overrides)
        return payload

    def write_scores(self, plan, arm: str, score: int, **overrides) -> None:
        for rep in range(plan.replicates):
            payload = {
                "task_id": "Energy_001",
                "items": [
                    {"index": index, "type": entry["type"], "weight": entry["weight"],
                     "content": entry["content"], "score": score}
                    for index, entry in enumerate(CHECKLIST)
                ],
                "total_score": score,
                "judge_model": "gpt-5.1",
                "judge_failures": [],
                "checklist_items_expected": len(CHECKLIST),
                "images_shown": ["a.png"],
                "images_available": 1,
                "bench_revision": "bench-sha",
            }
            payload.update(overrides)
            self.tool.write_json(
                self.tool.score_path(plan, "Energy_001", arm, 1, "final", rep), payload
            )

    def test_a_replicate_the_judge_never_produced_is_written_down(self) -> None:
        """Giving up quietly is how an arm scored once was published as one scored three.

        The count reaches the report through the environment digest, which excludes the
        pair; this is the operator's copy, on the stdout they are watching and in the
        state directory, so the loss is attributable to a replicate rather than inferred
        from a missing file days later.
        """
        plan = self.plan()
        self.tool.write_json(
            self.tool.state_path(plan, "Energy_001", "621566b", 1), self.state("621566b")
        )
        real = self.tool.score_once
        self.tool.score_once = lambda *args, **kwargs: False
        try:
            self.tool.final_pass(plan)
        finally:
            self.tool.score_once = real
        recorded = self.tool.read_json(Path(plan.state_dir) / "final_pass.json")
        self.assertEqual(
            recorded["unscored_replicates"],
            ["Energy_001.621566b.a1.final.r0.json", "Energy_001.621566b.a1.final.r1.json"],
        )

    def test_every_field_of_the_environment_comes_off_the_run(self) -> None:
        plan = self.plan()
        self.write_scores(plan, "621566b", 20)
        evidence = self.tool.evidence_for(plan, self.state("621566b"))
        checklist = self.bench / "tasks" / "Energy_001" / "target_study" / "checklist.json"

        self.assertEqual(evidence.env.agent_model, "claude-opus-4-5")
        self.assertEqual(evidence.env.review_model, "claude-sonnet-4-5")
        self.assertEqual(evidence.env.web_search_level, "warn")
        self.assertEqual(evidence.env.web_search_mode, "auto")
        self.assertEqual(evidence.env.instructions_digest, "ins-digest")
        self.assertEqual(evidence.env.judge_model, "gpt-5.1")
        self.assertEqual(evidence.env.bench_revision, "bench-sha")
        self.assertEqual(evidence.env.checklist_digest, self.tool.digest_bytes(checklist))
        self.assertEqual(evidence.env.judge_replicates, 2)
        self.assertEqual(evidence.replicates_requested, 2)
        self.assertEqual((evidence.images_shown, evidence.images_available), (1, 1))

    def test_two_arms_run_on_different_models_are_not_a_pair(self) -> None:
        """Fact one's exact confound, through the real producer.

        A control run on the exhausted sonnet pool and a treatment run on opus is a
        40-point model swap that the report would publish as PR #175's effect. The gate
        that stops it is the environment digest, and the digest is only a gate if
        something actually fills it in.
        """
        from src.rcb_trial import collect_rcb_pairs

        plan = self.plan()
        self.write_scores(plan, "621566b", 20)
        self.write_scores(plan, "47f3fbf", 60)
        evidences = [
            self.tool.evidence_for(plan, self.state("621566b", agent_model="claude-sonnet-4-5")),
            self.tool.evidence_for(plan, self.state("47f3fbf", agent_model="claude-opus-4-5")),
        ]
        outcome = collect_rcb_pairs(
            evidences, capability="pr175", control_arm="621566b",
            treatment_arm="47f3fbf", planned_pairs=1,
        )
        self.assertEqual(outcome.result.n, 0)
        self.assertIn("agent_model", dict(outcome.result.excluded)["Energy_001"])

    def test_an_arm_scored_fewer_times_than_the_other_is_not_a_pair(self) -> None:
        """What ``final_pass`` leaves behind when a replicate fails both its tries."""
        from src.rcb_trial import collect_rcb_pairs

        plan = self.plan()
        self.write_scores(plan, "621566b", 20)
        self.write_scores(plan, "47f3fbf", 60)
        self.tool.score_path(plan, "Energy_001", "47f3fbf", 1, "final", 1).unlink()

        evidences = [
            self.tool.evidence_for(plan, self.state(arm)) for arm in ("621566b", "47f3fbf")
        ]
        self.assertEqual([item.replicates for item in evidences], [2, 1])
        outcome = collect_rcb_pairs(
            evidences, capability="pr175", control_arm="621566b",
            treatment_arm="47f3fbf", planned_pairs=1,
        )
        self.assertEqual(outcome.result.n, 0)
        self.assertIn("judge_replicates", dict(outcome.result.excluded)["Energy_001"])


class EndToEndDryRunTests(unittest.TestCase):
    """One whole trial, with the four hours and the judge's bill taken out.

    Everything else is the real thing. If the seam, the gate, the state machine or the
    report were wrong, this is where it shows — and it costs seconds rather than days.
    """

    def setUp(self) -> None:
        self.tool = load_tool()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # The preflight refusal is a property of the box, not of the trial: this
        # machine has been observed running three AutoR processes at once, and the test
        # is not about them.
        self.tool.foreign_runs = lambda: []

    def _plan(self, **overrides) -> Path:
        bench = make_bench(self.root)
        control, control_sha = make_worktree(self.root, "control")
        treatment, treatment_sha = make_worktree(self.root, "treatment")
        payload = {
            "capability": "pr175",
            "bench": str(bench),
            "tasks": ["Energy_001"],
            "control": {
                "label": control_sha[:7], "worktree": str(control), "sha": control_sha[:7]
            },
            "treatment": {
                "label": treatment_sha[:7], "worktree": str(treatment), "sha": treatment_sha[:7]
            },
            "judge_kind": "fake",
            "judge_model": "fake-judge",
            "state_dir": str(self.root / "state"),
            "operator": "fake",
            "replicates": 2,
            "fake_quality": 20.0,
        }
        payload.update(overrides)
        path = self.root / "plan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        self.control_arm = payload["control"]["label"]
        self.treatment_arm = payload["treatment"]["label"]
        return path

    def test_a_whole_trial_runs_freezes_scores_and_reports(self) -> None:
        plan_path = self._plan()
        self.assertEqual(self.tool.main(["plan", "--plan", str(plan_path)]), 0)
        self.assertEqual(self.tool.main(["run", "--plan", str(plan_path)]), 0)

        state = self.root / "state"
        runs = sorted(p.name for p in (state / "runs").glob("*.json"))
        self.assertEqual(len(runs), 2, runs)
        for name in runs:
            payload = json.loads((state / "runs" / name).read_text(encoding="utf-8"))
            self.assertEqual(payload["phase"], "finished")
            self.assertEqual(payload["classification"], "ok")
            self.assertEqual(payload["meta_report_source"], "agent")
            self.assertEqual(payload["web_search_level"], "info")
            self.assertEqual(payload["autor_run_count"], 1)

        # Two arms, two replicates each, in the final pass; plus one early score apiece.
        self.assertEqual(len(list((state / "scores").glob("*.final.*.json"))), 4)
        self.assertEqual(len(list((state / "scores").glob("*.early.*.json"))), 2)

        report = (state / "report.md").read_text(encoding="utf-8")
        self.assertIn("pairs: **1**", report)
        self.assertIn("RCB points", report)
        self.assertIn("fake-judge", report)
        # The fake operator hands the treatment arm a better report, so the apparatus
        # must show a signed, non-zero, correctly-directed difference. Two identical
        # columns would let a broken seam pass.
        self.assertIn("won 1, lost 0", report)

    def test_the_recovered_difference_is_the_benchmark_total_difference(self) -> None:
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])

        from src.rcb_trial import collect_rcb_pairs

        plan = self.tool.load_plan(plan_path)
        evidences = [
            self.tool.evidence_for(plan, state)
            for state in self.tool.all_states(plan)
            if state.get("phase") == "finished"
        ]
        trial = collect_rcb_pairs(
            evidences, capability=plan.capability,
            control_arm=plan.control.label, treatment_arm=plan.treatment.label,
            planned_pairs=1,
        )
        control = trial.evidence[("Energy_001", plan.control.label)]
        treatment = trial.evidence[("Energy_001", plan.treatment.label)]
        self.assertAlmostEqual(
            trial.result.mean_difference,
            treatment.total_weighted - control.total_weighted,
            places=9,
        )
        self.assertGreater(trial.result.mean_difference, 15.0)

    def test_the_treatment_arm_is_the_one_that_carries_the_channel(self) -> None:
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        plan = self.tool.load_plan(plan_path)
        dosed = {
            state["arm"]: state["settled_reasoning_dose"] for state in self.tool.all_states(plan)
        }
        self.assertTrue(dosed[self.treatment_arm])
        self.assertFalse(dosed[self.control_arm])
        self.assertNotIn(
            "Zero settled-reasoning dose",
            (self.root / "state" / "report.md").read_text(encoding="utf-8"),
        )

    def _kill_the_treatment_arm(self, state: Path, refused: dict | None) -> None:
        """Leave the state directory exactly as the driver leaves it after a death."""
        for path in (state / "runs").glob(f"Energy_001.{self.treatment_arm}.*.json"):
            path.unlink()
        for path in (state / "scores").glob(f"Energy_001.{self.treatment_arm}.*.json"):
            path.unlink()
        if refused is not None:
            (state / "runs" / f"Energy_001.{self.treatment_arm}.a0.json").write_text(
                json.dumps(refused), encoding="utf-8"
            )

    def test_a_run_the_driver_refused_is_in_the_ledger_not_missing_from_it(self) -> None:
        """Three treatment deaths against zero control deaths is this trial's result.

        The ledger could not see any of them: ``build_report`` builds evidence only from
        ``phase == "finished"`` states with score files, and ``final_pass`` scores only
        ``classification == "ok"``, so every quota death, backend death, stall, fallback
        and incomplete run was reported as "no `<arm>` arm" — the same sentence as an arm
        that was never launched — above a clause table of ten zeros and a paragraph
        telling the reader to judge the difference on the per-arm counts.
        """
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        state = self.root / "state"
        self._kill_the_treatment_arm(
            state,
            {
                "task_id": "Energy_001", "arm": self.treatment_arm, "attempt": 0,
                "phase": "refused", "classification": "quota",
            },
        )
        self.tool.main(["report", "--plan", str(plan_path)])
        report = (state / "report.md").read_text(encoding="utf-8")

        self.assertIn("| `driver:quota` | 1 |", report)
        self.assertIn(f"treatment `{self.treatment_arm}` 1", report)
        self.assertIn(f"control `{self.control_arm}` 0", report)
        self.assertNotIn("- no run was refused.", report)
        self.assertIn("was refused (driver:quota)", report)
        self.assertNotIn(f"no `{self.treatment_arm}` arm", report)

    def test_a_run_nothing_could_score_is_a_refusal_and_not_a_silence(self) -> None:
        """The whole-trial failure mode: every score fails, and the report says nothing.

        With `<state_dir>/scores/` missing the real scorer judged every item and died
        writing the result, which the driver reads as "scoring failed". Two completed
        runs then published `pairs: 0`, `mean difference: +0.0000`, an empty ledger and
        no exclusion line — three to four days of opus runs and the judge's whole bill
        for a report with no diagnosis anywhere in it.
        """
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        state = self.root / "state"
        for path in (state / "scores").glob("*.final.*.json"):
            path.unlink()

        self.tool.main(["report", "--plan", str(plan_path)])
        report = (state / "report.md").read_text(encoding="utf-8")
        self.assertIn("| `driver:unscored` | 2 |", report)
        self.assertIn(f"control `{self.control_arm}` 1", report)
        self.assertIn(f"treatment `{self.treatment_arm}` 1", report)

    def test_a_run_the_final_pass_has_not_reached_yet_is_not_a_refusal(self) -> None:
        """The report runs at any moment by design, so "not scored yet" is a state.

        Calling it a death would fill an interim ledger with attrition that has not
        happened, which is the same failure as the ledger's silence, pointed the other
        way.
        """
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        state = self.root / "state"
        for path in (state / "scores").glob("*.final.*.json"):
            path.unlink()
        (state / "final_pass.json").unlink()

        self.tool.main(["report", "--plan", str(plan_path)])
        report = (state / "report.md").read_text(encoding="utf-8")
        self.assertNotIn("driver:unscored", report)
        self.assertIn("INTERIM — 0 of 1 planned pairs", report)

    def test_a_run_still_in_flight_is_not_reported_as_a_death(self) -> None:
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        state = self.root / "state"
        self._kill_the_treatment_arm(
            state,
            {
                "task_id": "Energy_001", "arm": self.treatment_arm, "attempt": 1,
                "phase": "launched", "child_pid": 4242,
            },
        )
        self.tool.main(["report", "--plan", str(plan_path)])
        report = (state / "report.md").read_text(encoding="utf-8")
        self.assertIn("- no run was refused.", report)

    def test_the_judge_in_the_header_is_the_one_that_ran(self) -> None:
        """Not the one the plan asked for, which is what it used to print.

        Judge choice is worth about sixteen points on identical artifacts, so the header
        is the line a reader uses to decide whether the number is comparable to anything
        — and `score_rcb_run.py` will happily fall back to its own default model.
        """
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        state = self.root / "state"
        for path in (state / "scores").glob("*.final.*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["judge_model"] = "claude-opus-4-5"
            path.write_text(json.dumps(payload), encoding="utf-8")

        self.tool.main(["report", "--plan", str(plan_path)])
        report = (state / "report.md").read_text(encoding="utf-8")
        self.assertIn("- judge: `claude-opus-4-5`", report)
        self.assertIn("not the judge the plan declared", report)

    def test_the_report_is_a_pure_function_of_the_state_directory(self) -> None:
        """Re-running after fixing a bug in the producer must not leave half an answer."""
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        first = (self.root / "state" / "report.md").read_text(encoding="utf-8")
        (self.root / "state" / "report.md").unlink()
        self.tool.main(["report", "--plan", str(plan_path)])
        self.assertEqual((self.root / "state" / "report.md").read_text(encoding="utf-8"), first)

    def test_a_second_run_of_a_finished_trial_launches_nothing(self) -> None:
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        before = sorted(p.name for p in (self.root / "state" / "workspaces").iterdir())
        self.tool.main(["run", "--plan", str(plan_path)])
        after = sorted(p.name for p in (self.root / "state" / "workspaces").iterdir())
        self.assertEqual(before, after)

    def test_editing_a_frozen_plan_is_refused(self) -> None:
        """An apparatus that can be re-planned while it runs can be stopped when the
        sign looks good."""
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
        payload["tasks"] = ["Energy_001", "Astronomy_000"]
        plan_path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(SystemExit) as caught:
            self.tool.main(["run", "--plan", str(plan_path)])
        self.assertIn("frozen", str(caught.exception))

    def test_running_without_freezing_first_is_refused(self) -> None:
        plan_path = self._plan()
        with self.assertRaises(SystemExit) as caught:
            self.tool.main(["run", "--plan", str(plan_path)])
        self.assertIn("freeze the plan first", str(caught.exception))

    def test_a_foreign_autor_process_stops_the_driver_starting(self) -> None:
        """Fact three: a ``setsid`` driver survives ``pkill`` on its children, so "I
        killed it and relaunched" yields two drivers racing — which is the concurrency
        that exhausts the quota."""
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.foreign_runs = lambda: ["4242 python rcb_agent.py --workspace /x"]
        self.assertEqual(self.tool.main(["run", "--plan", str(plan_path)]), 2)

    def test_a_workspace_is_never_reused_between_arms(self) -> None:
        """Two arms pre-created in the same second land in one directory and overwrite
        each other's report, making the paired difference identically zero."""
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        workspaces = list((self.root / "state" / "workspaces").iterdir())
        self.assertEqual(len(workspaces), 2)
        self.assertEqual(len({p.name for p in workspaces}), 2)

    def test_the_benchmark_background_is_copied_identically_into_both_arms(self) -> None:
        """The judge reads ``INSTRUCTIONS.md``; ``rcb_agent.py`` never writes it."""
        plan_path = self._plan()
        self.tool.main(["plan", "--plan", str(plan_path)])
        self.tool.main(["run", "--plan", str(plan_path)])
        digests = {
            self.tool.instructions_digest(ws)
            for ws in (self.root / "state" / "workspaces").iterdir()
        }
        self.assertEqual(len(digests), 1)
        self.assertNotIn("", digests)
        for ws in (self.root / "state" / "workspaces").iterdir():
            self.assertTrue((ws / "data" / "x.csv").exists(), "data/ was not copied")


class StallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tool = load_tool()

    def test_there_is_no_per_run_wall_clock(self) -> None:
        """A measured run here took 57011 seconds and finished with
        ``report_source == "agent"``. Any cap short enough to catch a hang would have
        killed it."""
        body = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("max_seconds", body)
        self.assertIn("stall_seconds", body)

    def test_a_silent_child_is_killed_by_its_process_group(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True
        )
        started = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            stalled = self.tool.watch(child, Path(tmp), stall_seconds=1)
        self.assertTrue(stalled)
        self.assertLess(time.time() - started, 30)
        self.assertIsNotNone(child.poll())

    def test_a_beating_child_is_left_alone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            (workspace / ".autor" / "r1").mkdir(parents=True)
            beat = workspace / ".autor" / "r1" / "logs_raw.jsonl"
            child = subprocess.Popen(
                [
                    sys.executable, "-c",
                    f"import time\nfor _ in range(4):\n"
                    f"    open({str(beat)!r},'a').write('{{}}\\n')\n    time.sleep(0.5)\n",
                ],
                start_new_session=True,
            )
            self.assertFalse(self.tool.watch(child, workspace, stall_seconds=2))
        self.assertEqual(child.returncode, 0)


if __name__ == "__main__":
    unittest.main()


class ForeignRunDetectionTests(unittest.TestCase):
    """A mention is not an execution, and a fake operator is not contention.

    Both of these refused a real trial on a live box. The driver stands down for ten
    minutes per refusal, so a detector that fires on the wrong thing does not merely
    add noise -- on a machine where anyone is running the test suite, or where anyone
    types a one-liner to check whether a run is up, the trial never starts at all.

    This is the same shape as the quota classifier matching the bare substring "429":
    a detector matching a broader pattern than the thing it protects against.
    """

    def setUp(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "rcb_trial_tool", Path(__file__).resolve().parent.parent / "tools" / "rcb_trial.py"
        )
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def test_a_real_benchmark_run_is_a_run(self) -> None:
        argv = ["python3", "/home/u/AutoR/rcb_agent.py", "--workspace", "/w", "--model", "opus"]
        self.assertTrue(self.tool.is_backed_run(argv))

    def test_a_real_goal_run_is_a_run(self) -> None:
        argv = ["python", "main.py", "--goal-file", "/tmp/g.txt", "--full-auto", "--model", "opus"]
        self.assertTrue(self.tool.is_backed_run(argv))

    def test_a_fake_operator_run_contends_for_nothing(self) -> None:
        # What the test suite runs, constantly. It makes no backend call.
        argv = ["python", "main.py", "--fake-operator", "--full-auto", "--goal", "coverage"]
        self.assertFalse(self.tool.is_backed_run(argv))

    def test_a_fake_operator_benchmark_run_contends_for_nothing_either(self) -> None:
        argv = ["python3", "/home/u/AutoR/rcb_agent.py", "--fake-operator", "--no-synthesis"]
        self.assertFalse(self.tool.is_backed_run(argv))

    def test_a_shell_that_merely_names_the_script_is_not_a_run(self) -> None:
        # The exact false positive: a diagnostic one-liner asking whether a run is up.
        argv = ["/bin/bash", "-c", 'pgrep -af "rcb_agent.py" | head -3']
        self.assertFalse(self.tool.is_backed_run(argv))

    def test_a_grep_for_the_script_is_not_a_run(self) -> None:
        argv = ["grep", "-rn", "rcb_agent.py", "/home/u/AutoR"]
        self.assertFalse(self.tool.is_backed_run(argv))

    def test_a_non_python_binary_is_not_a_run(self) -> None:
        # The script name is a bare argument to grep too. Requiring an interpreter at
        # argv[0] is what separates reading the file from running it. A shebang
        # execution is unaffected: the kernel rewrites argv to put python first.
        self.assertFalse(self.tool.is_backed_run(["/usr/bin/rcb_agent.py"]))
        self.assertFalse(self.tool.is_backed_run(["vim", "rcb_agent.py"]))
        self.assertTrue(self.tool.is_backed_run(["/usr/bin/python3.11", "rcb_agent.py", "-w", "/w"]))

    def test_main_py_without_a_goal_is_not_a_run(self) -> None:
        # `main.py --trial-report` reads artifacts and calls nothing.
        self.assertFalse(self.tool.is_backed_run(["python", "main.py", "--trial-report"]))

    def test_an_empty_argv_is_not_a_run(self) -> None:
        # Kernel threads have an empty cmdline.
        self.assertFalse(self.tool.is_backed_run([]))

    def test_process_argv_splits_on_nul_rather_than_joining(self) -> None:
        argv = self.tool.process_argv(os.getpid())
        self.assertGreater(len(argv), 1)
        self.assertNotIn(" ", argv[0])

    def test_process_argv_on_a_dead_pid_is_empty_not_an_error(self) -> None:
        self.assertEqual(self.tool.process_argv(999999), [])

    def test_foreign_runs_reads_real_proc_and_separates_mention_from_execution(self) -> None:
        """The producer, not just the predicate.

        Every other test here calls ``is_backed_run`` with a hand-built argv, which
        leaves ``foreign_runs`` free to go on substring-matching the joined command
        line -- the very thing that refused a live trial. This spawns three real
        processes and asks the scanner what it sees.
        """
        import subprocess
        import tempfile
        import time

        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "rcb_agent.py"
            script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
            real = subprocess.Popen([sys.executable, str(script), "--workspace", tmp])
            faked = subprocess.Popen(
                [sys.executable, str(script), "--fake-operator", "--workspace", tmp]
            )
            mention = subprocess.Popen(["sleep", "30"] if False else
                                       ["/bin/sh", "-c", "sleep 30 # rcb_agent.py --workspace x"])
            try:
                deadline = time.time() + 10
                while time.time() < deadline:
                    listed = self.tool.foreign_runs()
                    if any(str(real.pid) == line.split()[0] for line in listed):
                        break
                    time.sleep(0.2)
                pids = {line.split()[0] for line in listed}
                self.assertIn(str(real.pid), pids, f"a real run must be seen: {listed}")
                self.assertNotIn(str(faked.pid), pids, f"a fake operator contends for nothing: {listed}")
                self.assertNotIn(str(mention.pid), pids, f"a mention is not an execution: {listed}")
            finally:
                for proc in (real, faked, mention):
                    proc.kill()
                    proc.wait()
