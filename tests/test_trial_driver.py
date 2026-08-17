"""The seam between the shared driver kernel and the driver that used to own it.

:mod:`src.trial_driver` arrived by moving nineteen functions out of
``tools/rcb_trial.py`` unchanged. Almost nothing here re-tests what they do --
``tests/test_rcb_trial_driver.py`` already does that, with a real ``os.link`` lock, real
``Popen(start_new_session=True)`` children, a real ``/proc`` scan over three real
processes, and a whole dry-run trial end to end. Those 156 tests keep working against
the moved code for one reason, and it is the reason this module exists: the driver
imports the names into its own namespace, so ``tool.acquire_lock`` is literally
``src.trial_driver.acquire_lock``, and the oracle is testing the kernel without knowing
it.

That property is load-bearing twice over and invisible both times.

**It is what keeps the oracle pointed at the code.** Rewrite one import as
``from src import trial_driver`` and call ``trial_driver.acquire_lock(...)``, and every
one of those 156 tests still passes while testing a module the driver no longer runs
through -- they would be reaching the same functions by a path the driver stopped using.
The identity assertions below are what refuse that.

**It is what keeps the substitutions working.** ``tests/test_rcb_trial_driver.py``
rebinds ``tool.foreign_runs`` twice, to keep a test about the state machine from
refusing on whatever else this shared box is running. A rebind only reaches the call
site if the call site looks the name up in the driver's globals, which is exactly what
``from src.trial_driver import foreign_runs`` arranges and what a qualified call would
quietly break -- the dry run would then refuse on a foreign process and the test would
fail somewhere else entirely.

The second half of the file is about the two hazards that come from there being two
drivers on one box at all, and that is a different argument: see
:class:`TwoDriversOnOneBoxTests` and :class:`AgentScriptNamesTests`.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from src import trial_driver

REPO_ROOT = Path(__file__).resolve().parent.parent
TOOL = REPO_ROOT / "tools" / "rcb_trial.py"
KERNEL = REPO_ROOT / "src" / "trial_driver.py"

_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)

#: Everything that moved out of ``tools/rcb_trial.py`` and has to be reachable on it
#: still. Written out rather than derived from the kernel, because a list derived from
#: the thing under test cannot notice a function that failed to move --
#: :meth:`TheSeamTests.test_the_moved_list_is_every_public_function_the_kernel_declares`
#: is the other direction, and the two together are what make the population honest.
MOVED = (
    "acquire_lock",
    "autor_pids",
    "boot_id",
    "claim_stale_lock",
    "contrast_log",
    "digest_bytes",
    "foreign_runs",
    "git_dirty",
    "git_head",
    "heartbeat",
    "is_backed_run",
    "kill_group",
    "lock_is_live",
    "process_argv",
    "process_cmdline",
    "read_json",
    "release_lock",
    "watch",
    "write_json",
)


def load_tool():
    """The driver, loaded the way its own test module loads it.

    By file path with ``exec_module`` rather than as ``tools.rcb_trial``, because that is
    what ``tests/test_rcb_trial_driver.py`` does and the question here is whether the
    import survives *that* loader. It does because the file inserts the repository root
    on ``sys.path`` before importing anything from ``src`` -- a bare ``from src.trial_driver
    import ...`` in a file without that bootstrap raises ``ImportError`` under this
    loader, which is why ``tools/score_rcb_run.py`` has none.
    """
    spec = importlib.util.spec_from_file_location("rcb_trial_tool_seam", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def executable_source(path: Path) -> str:
    """*path* with every docstring and comment removed, as source.

    The benchmark scan below has to read the code and not the prose. The module it reads
    spends a page explaining which benchmark's vocabulary it keeps out and why, and a
    raw text scan makes that explanation impossible to write -- which is the failure
    where a guard's own documentation is the thing that trips it, and the answer is
    never to stop documenting. ``ast.unparse`` over a tree with the docstrings dropped
    keeps every string the interpreter actually uses, including the ones inside ``if``
    tests and format strings, and loses only what nothing reads.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(node, (ast.Module, ast.ClassDef) + _FUNCTIONS) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return ast.unparse(ast.fix_missing_locations(tree))


def public_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in tree.body
        if isinstance(node, _FUNCTIONS) and not node.name.startswith("_")
    }


class TheSeamTests(unittest.TestCase):
    """One copy, reached by the name the driver's own tests already substitute."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tool = load_tool()

    def test_the_driver_reaches_every_moved_function_by_the_name_it_always_used(self) -> None:
        """``self.tool.acquire_lock`` has to resolve, and to the kernel's function.

        Not merely to *a* function of that name: the whole argument for the move is that
        there is one copy, and an attribute that happens to exist would be satisfied by
        a second copy left behind in the driver.
        """
        for name in MOVED:
            with self.subTest(symbol=name):
                self.assertTrue(
                    hasattr(self.tool, name),
                    f"tools/rcb_trial.py no longer exposes {name}; every test that "
                    "reaches it through the loaded module breaks",
                )
                self.assertIs(getattr(self.tool, name), getattr(trial_driver, name))

    def test_a_name_the_kernel_does_not_publish_is_not_reachable(self) -> None:
        """The control. Without it the check above passes on any driver at all.

        ``instructions_digest`` stayed behind on purpose -- it reads
        ResearchClawBench's ``INSTRUCTIONS.md`` -- so the kernel must not have it, and a
        name neither file declares must be absent from both.
        """
        self.assertTrue(hasattr(self.tool, "instructions_digest"))
        self.assertFalse(hasattr(trial_driver, "instructions_digest"))
        self.assertFalse(hasattr(trial_driver, "definitely_not_a_driver_function"))
        self.assertFalse(hasattr(self.tool, "definitely_not_a_driver_function"))

    def test_the_driver_no_longer_defines_what_it_imports(self) -> None:
        """A re-export and a second copy look identical from the outside.

        They differ in the file, so the file is what is read. The failure this refuses
        is the ordinary one: somebody debugging a stuck trial pastes ``acquire_lock``
        back into the driver to add a print, the import above still exists, the shadowed
        definition wins, and the two drivers on this box no longer share a lock
        implementation while every test still passes.
        """
        defined = public_functions(TOOL)
        collisions = sorted(defined & set(MOVED))
        self.assertEqual(
            collisions,
            [],
            f"tools/rcb_trial.py defines these again instead of importing them: {collisions}",
        )

    def test_the_moved_list_is_every_public_function_the_kernel_declares(self) -> None:
        """The other direction, so :data:`MOVED` cannot silently stop covering the kernel.

        A function added to ``src/trial_driver.py`` and not re-exported is a function the
        second driver can use and this one cannot, which is the divergence the module
        exists to prevent -- one benchmark's driver quietly running different code.
        """
        self.assertEqual(sorted(MOVED), sorted(public_functions(KERNEL)))

    def test_the_kernel_names_no_benchmark(self) -> None:
        """The line the split was drawn on, asserted rather than described.

        ``INSTRUCTIONS.md``, ``checklist.json`` and ``target_study`` are
        ResearchClawBench's vocabulary; ``research_test.jsonl`` and ``rubric`` are
        FrontierScience's. A kernel that learned either one is a kernel the other
        benchmark has to work around. ``rcb_agent.py`` and ``fs_agent.py`` are
        deliberately *not* in this list: recognising both agents by name is the kernel's
        job (:data:`src.trial_driver.AGENT_SCRIPT_NAMES`), which is a different thing
        from knowing what either of them produces.

        Over :func:`executable_source`, so the module can still say in prose which
        vocabulary it is keeping out.
        """
        body = executable_source(KERNEL)
        for token in (
            "INSTRUCTIONS.md",
            "checklist",
            "target_study",
            "research_test.jsonl",
            "rubric",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, body)

    def test_that_scan_would_notice_a_benchmark_word(self) -> None:
        """The control for the scan above: it has to be able to fail.

        A ``for token in ()`` loop, or a token list none of which any driver would ever
        write, passes on every file in the tree. This asserts the same rule finds the
        vocabulary where it does live.
        """
        driver_body = executable_source(TOOL)
        self.assertIn("INSTRUCTIONS.md", driver_body)
        self.assertIn("checklist", driver_body)


class TwoDriversOnOneBoxTests(unittest.TestCase):
    """Sharing the kernel is not enough; the kernel has to know it is shared.

    Both of these are consequences of the same fact -- from the moment a second driver
    exists, every question the kernel answers about a process has two possible subjects
    -- and neither is caught by anything in ``tests/test_rcb_trial_driver.py``, because
    that file only ever runs one driver.
    """

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _live_driver(self, script: str) -> subprocess.Popen:
        """A real process whose command line names *script*.

        Real, because a synthetic pid is indistinguishable from the stale-lock case and
        the entire question here is which of those two a driver decides it is looking at.
        """
        holder = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", f"tools/{script}"]
        )
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        deadline = time.time() + 10
        while time.time() < deadline:
            if script in trial_driver.process_cmdline(holder.pid):
                break
            time.sleep(0.05)
        return holder

    def _write_lock(self, holder: subprocess.Popen) -> dict:
        payload = {
            "pid": holder.pid,
            "boot_id": trial_driver.boot_id(),
            "started_at": 1.0,
        }
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "driver.lock").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_each_driver_recognises_its_own_kind_of_live_lock(self) -> None:
        """The hazard, stated as the thing that has to be true.

        A live ``fs_trial.py`` must read as live to another ``fs_trial.py``, and a live
        ``rcb_trial.py`` to another ``rcb_trial.py``. Before ``marker`` was required this
        was true of exactly one of the two, because the default said ``rcb_trial.py``.
        """
        for script in ("rcb_trial.py", "fs_trial.py"):
            with self.subTest(driver=script):
                holder = self._live_driver(script)
                payload = self._write_lock(holder)
                self.assertTrue(trial_driver.lock_is_live(payload, marker=script))

    def test_a_driver_of_the_other_kind_does_not_own_this_lock(self) -> None:
        """The control, and the measurement of what the old default did.

        The same live process, read with the other driver's marker, is not live -- which
        is correct as a statement about ownership and catastrophic as a *default*: it is
        the exact evaluation a second FrontierScience driver used to perform on the first
        one's lock before deciding the lock was abandoned and taking it over.
        """
        holder = self._live_driver("fs_trial.py")
        payload = self._write_lock(holder)
        self.assertFalse(trial_driver.lock_is_live(payload, marker="rcb_trial.py"))

    def test_a_second_frontierscience_driver_stands_down(self) -> None:
        """End to end through ``acquire_lock``: the refusal, not just the predicate.

        Without the marker this call took the lock over and returned, and two drivers
        then spent one quota. The pid is in the message because the operator's next move
        is to look at it.
        """
        holder = self._live_driver("fs_trial.py")
        self._write_lock(holder)
        with self.assertRaises(SystemExit) as caught:
            trial_driver.acquire_lock(self.state, marker="fs_trial.py")
        self.assertIn(str(holder.pid), str(caught.exception))

    def test_neither_lock_function_has_a_default_marker(self) -> None:
        """The gate. A default is not a smaller version of this bug, it *is* this bug.

        Both functions take it keyword-only and required, so a new driver cannot acquire
        a lock without saying what it is called -- and cannot get it wrong by omission,
        which is the only way it was ever got wrong.
        """
        for function in (trial_driver.lock_is_live, trial_driver.acquire_lock):
            with self.subTest(function=function.__name__):
                marker = inspect.signature(function).parameters["marker"]
                self.assertIs(marker.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(
                    marker.default,
                    inspect.Parameter.empty,
                    f"{function.__name__} has a default marker again; a driver that "
                    "forgets to name itself reads its own live lock as stale",
                )

    def test_the_signature_check_can_tell_a_required_parameter_from_an_optional_one(self) -> None:
        """Control for the check above, which would pass on an empty parameter list.

        ``state_dir`` is positional and required and ``lock_is_live``'s ``payload`` is
        too, so the two assertions above are each capable of failing on a real signature
        in the same file.
        """
        state_dir = inspect.signature(trial_driver.acquire_lock).parameters["state_dir"]
        self.assertIsNot(state_dir.kind, inspect.Parameter.KEYWORD_ONLY)

        def sample(a, *, b="x"):
            return a, b

        self.assertIsNot(
            inspect.signature(sample).parameters["b"].default, inspect.Parameter.empty
        )


class AgentScriptNamesTests(unittest.TestCase):
    """The second hazard: a ``/proc`` census that has never heard of the other agent.

    ``is_backed_run`` is what ``foreign_runs`` asks about every pid on the box before a
    driver will start, and the answer is "is this process going to spend the quota I am
    about to spend". With ``fs_agent.py`` missing from it, an RCB driver walks past six
    live FrontierScience children, reports a clean box, and starts a seventh opus run --
    which is the concurrency that exhausts the quota that then kills all seven.
    """

    def test_every_script_the_constant_names_is_recognised(self) -> None:
        """Over the constant, so adding a name without wiring it fails here.

        A test that hard-coded ``fs_agent.py`` would go green the moment the name was
        added to the tuple and stay green if the function never read the tuple -- the
        constant ``_RUN_SCRIPTS`` this replaced was declared, correct, and read by
        nothing at all for the whole life of the driver.
        """
        for script, required in trial_driver.AGENT_SCRIPT_NAMES.items():
            with self.subTest(script=script):
                argv = ["python3", f"/home/u/AutoR/{script}", *required, "--model", "opus"]
                self.assertTrue(trial_driver.is_backed_run(argv))

    def test_the_constant_names_both_agents_and_the_goal_entry_point(self) -> None:
        """What "both benchmarks" means, pinned. Two front ends and ``main.py``."""
        self.assertEqual(
            sorted(trial_driver.AGENT_SCRIPT_NAMES),
            ["fs_agent.py", "main.py", "rcb_agent.py"],
        )

    def test_a_frontierscience_run_is_a_run(self) -> None:
        argv = ["python3", "/home/u/AutoR/fs_agent.py", "--workspace", "/w", "--model", "opus"]
        self.assertTrue(trial_driver.is_backed_run(argv))

    def test_a_fake_operator_frontierscience_run_contends_for_nothing(self) -> None:
        """What the test suite runs, constantly. It makes no backend call.

        A driver that stands down for the unit tests never starts on a machine anybody is
        developing on, and this box is one.
        """
        argv = ["python3", "/home/u/AutoR/fs_agent.py", "--fake-operator", "--workspace", "/w"]
        self.assertFalse(trial_driver.is_backed_run(argv))

    def test_a_shell_that_merely_names_the_frontierscience_agent_is_not_a_run(self) -> None:
        """Why ``process_argv`` splits on NUL instead of joining.

        The diagnostic one-liner somebody types to ask whether a run is up has the script
        name in its joined command line. Ten minutes per false refusal, and on a busy box
        the trial never starts at all.
        """
        self.assertFalse(
            trial_driver.is_backed_run(["/bin/bash", "-c", 'pgrep -af "fs_agent.py" | head'])
        )
        self.assertFalse(trial_driver.is_backed_run(["grep", "-rn", "fs_agent.py", "/home/u"]))
        self.assertFalse(trial_driver.is_backed_run(["/usr/bin/fs_agent.py"]))

    def test_main_py_still_needs_a_goal(self) -> None:
        """The one entry in the constant that carries a condition.

        ``main.py --trial-report`` reads artifacts and calls nothing, so the script name
        alone is not enough for that one -- and folding the three scripts into one table
        must not lose the condition on the third.
        """
        self.assertFalse(trial_driver.is_backed_run(["python", "main.py", "--trial-report"]))
        self.assertTrue(
            trial_driver.is_backed_run(["python", "main.py", "--goal-file", "/tmp/g.txt"])
        )

    def test_the_census_sees_a_live_frontierscience_agent(self) -> None:
        """The producer, not just the predicate, against three real processes.

        Every other test here hands ``is_backed_run`` an argv it built. That leaves
        ``foreign_runs`` free to go on matching whatever it likes -- which is how the
        original substring match survived being wrong.
        """
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fs_agent.py"
            script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
            real = subprocess.Popen([sys.executable, str(script), "--workspace", tmp])
            faked = subprocess.Popen(
                [sys.executable, str(script), "--fake-operator", "--workspace", tmp]
            )
            mention = subprocess.Popen(
                ["/bin/sh", "-c", "sleep 30 # fs_agent.py --workspace x"]
            )
            try:
                listed: list[str] = []
                deadline = time.time() + 10
                while time.time() < deadline:
                    listed = trial_driver.foreign_runs()
                    if any(str(real.pid) == line.split()[0] for line in listed):
                        break
                    time.sleep(0.2)
                pids = {line.split()[0] for line in listed}
                self.assertIn(
                    str(real.pid),
                    pids,
                    f"an RCB driver would start a seventh opus run beside this: {listed}",
                )
                self.assertNotIn(str(faked.pid), pids, f"a fake operator spends nothing: {listed}")
                self.assertNotIn(str(mention.pid), pids, f"a mention is not a run: {listed}")
            finally:
                for proc in (real, faked, mention):
                    proc.kill()
                    proc.wait()


class TheKernelStillWorksFromItsNewHomeTests(unittest.TestCase):
    """Two behaviours the move could plausibly have broken silently.

    Not a re-run of the driver's suite -- the identity assertions above mean that suite
    is already testing these functions. These two are here because they depend on the
    *module* rather than on the function: ``os.getpid()`` and ``sys.argv`` are read at
    call time and a move is exactly the kind of edit that turns one into a stale import.
    """

    def test_state_is_replaced_and_never_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs" / "a.json"
            trial_driver.write_json(path, {"a": 1})
            trial_driver.write_json(path, {"a": 2})
            self.assertEqual(trial_driver.read_json(path), {"a": 2})
            self.assertEqual(list((Path(tmp) / "runs").glob("*.tmp*")), [])

    def test_a_lock_this_process_took_records_this_process(self) -> None:
        """``os.getpid`` and ``sys.argv`` are read inside the kernel now.

        The release path compares the recorded pid against ``os.getpid()``, so a lock
        written with anything else is a lock nobody can release.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lock = trial_driver.acquire_lock(Path(tmp), marker="rcb_trial.py")
            payload = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(payload["argv"], sys.argv)
            trial_driver.release_lock(lock)
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
