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
    "digest_bytes",
    "foreign_runs",
    "git_contrast_log",
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
    "watch_until_stalled",
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
        ResearchClawBench's vocabulary; ``research_test.jsonl`` and ``rubric`` were a
        second benchmark's adapter's, and that adapter has since been removed from this
        repository. Both tokens stay in the list: the rule is about what may live in the
        kernel, not about which adapters happen to exist this week, and a token whose
        owner is gone is the cheapest one here to keep -- the expensive direction is a
        scan that only knows the vocabulary of whatever shipped last. ``rcb_trial.py`` is
        one benchmark's *driver*, which is the form the violation actually took --
        ``autor_pids`` matched ``"rcb_agent.py"`` and ``"rcb_trial.py fake-run"`` in its
        body while its docstring said it answered for anybody, so the kernel shipped with
        a second, private encoding of "what is an agent run" that only knew about one
        benchmark.

        Exactly one exemption, and it is the keys of
        :data:`src.trial_driver.AGENT_SCRIPT_NAMES`. Recognising *every* front end by name
        is the kernel's job and is why that table exists; the tokens above are what a
        driver produces, reads or is called, and none of that belongs here. Nothing else
        is let through: a benchmark literal anywhere else in this file, including inside
        another function's ``if``, fails.

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
            "rcb_trial.py",
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, body)
        for script in trial_driver.AGENT_SCRIPT_NAMES:
            with self.subTest(exempt=script):
                self.assertEqual(
                    body.count(script),
                    1,
                    f"{script} occurs {body.count(script)} times in the kernel's code. "
                    "The exemption is the AGENT_SCRIPT_NAMES table and nothing else -- a "
                    "second occurrence is a second encoding of what an agent run is, and "
                    "one of the two will be the one that never hears about the next "
                    "benchmark, which is exactly how autor_pids was wrong",
                )

    def test_that_scan_would_notice_a_benchmark_word(self) -> None:
        """The control for the scan above: it has to be able to fail.

        A ``for token in ()`` loop, or a token list none of which any driver would ever
        write, passes on every file in the tree. This asserts the same rule finds the
        vocabulary where it does live -- including ``rcb_trial.py``, which is in the
        token list because the literals that used to be in ``autor_pids`` are now in the
        driver, where they belong and where this control finds them.
        """
        driver_body = executable_source(TOOL)
        self.assertIn("INSTRUCTIONS.md", driver_body)
        self.assertIn("checklist", driver_body)
        self.assertIn("rcb_trial.py", driver_body)


class TwoDriversOnOneBoxTests(unittest.TestCase):
    """Sharing the kernel is not enough; the kernel has to know it is shared.

    Every one of these is a consequence of the same fact -- from the moment a second
    driver exists, every question the kernel answers about a process has two possible
    subjects, and each question has to say which one it means. "Is this lock live" means
    the *holder*, so the holder's recorded name decides it; "is this pid one of mine"
    means the *asker*, so the asker passes its own markers in. None of it is caught by
    anything in ``tests/test_rcb_trial_driver.py``, because that file only ever runs one
    driver.

    The second driver these were written against was another benchmark's, and it went
    when that benchmark was removed; ``tools/rcb_trial.py`` is the only caller of
    ``acquire_lock`` in the tree today. The tests use ``other_trial.py`` -- a name no file in this
    repository has -- rather than a surviving driver's, because that is the honest
    subject: the property is "a driver that is not this one", and a test that named
    whichever benchmark shipped most recently would have to be rewritten with every
    adapter and would quietly stop holding in the window where there is only one driver,
    which is exactly the window a second one is written in.
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

    def _write_lock(self, holder: subprocess.Popen, marker: str | None = None) -> dict:
        """A lock file *holder* could have written. *marker* absent is the pre-marker one.

        Both shapes are real. ``acquire_lock`` records the field now, but a lock file
        outlives the process that wrote it and a driver from before that change leaves
        one without it, so the fallback path has to be exercised by the same helper.
        """
        payload: dict = {
            "pid": holder.pid,
            "boot_id": trial_driver.boot_id(),
            "started_at": 1.0,
        }
        if marker is not None:
            payload["marker"] = marker
        self.state.mkdir(parents=True, exist_ok=True)
        (self.state / "driver.lock").write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def test_each_driver_recognises_its_own_kind_of_live_lock(self) -> None:
        """The hazard, stated as the thing that has to be true.

        A live driver must read as live to another copy of itself whatever it is called:
        ``rcb_trial.py`` to another ``rcb_trial.py``, and ``other_trial.py`` to another
        ``other_trial.py``. Before ``marker`` was required this was true of exactly one of
        the two, because the default said ``rcb_trial.py``.
        """
        for script in ("rcb_trial.py", "other_trial.py"):
            with self.subTest(driver=script):
                holder = self._live_driver(script)
                payload = self._write_lock(holder)
                self.assertTrue(trial_driver.lock_is_live(payload, marker=script))

    def test_a_live_lock_the_other_kind_of_driver_recorded_still_reads_as_live(self) -> None:
        """Liveness is a property of the holder, so the holder's own name decides it.

        A live ``other_trial.py`` holding a lock that says ``marker: other_trial.py`` must
        read as live to an ``rcb_trial.py`` asking about it. Answering with the *asker's*
        name instead returns False for every live lock the other kind of driver holds, and
        False is a takeover: ``acquire_lock`` goes straight to ``claim_stale_lock``. That
        is the same escape the required marker closes, moved from a driver against another
        copy of itself to a driver against a different benchmark's, and one copy-pasted
        ``state_dir`` away from a live trial.
        """
        holder = self._live_driver("other_trial.py")
        payload = self._write_lock(holder, marker="other_trial.py")
        self.assertTrue(trial_driver.lock_is_live(payload, marker="rcb_trial.py"))

    def test_a_driver_will_not_take_over_a_lock_the_other_kind_recorded(self) -> None:
        """The consequence, through ``acquire_lock`` rather than through the predicate.

        The predicate returning False is not the damage; the damage is this call
        returning a lock while the holder is still running. The pid in the message is the
        holder's, because that is what the operator kills.
        """
        holder = self._live_driver("other_trial.py")
        self._write_lock(holder, marker="other_trial.py")
        with self.assertRaises(SystemExit) as caught:
            trial_driver.acquire_lock(self.state, marker="rcb_trial.py")
        self.assertIn(str(holder.pid), str(caught.exception))

    def test_a_lock_with_no_recorded_marker_is_read_with_the_askers_own_name(self) -> None:
        """The fallback, and the measurement of what the old default did.

        A lock file with no ``marker`` field was written by a driver from before the
        field existed, and there is nothing better to ask about it than the asker's own
        name -- which for the other kind of driver answers False, i.e. takes it over.
        That residue is bounded by the lock's lifetime rather than by an argument, and it
        is the evaluation *every* cross-kind case used to get: it is what the second
        driver on this box -- the one that went with the benchmark since removed --
        performed on the first one's lock before deciding the lock had been abandoned.
        """
        holder = self._live_driver("other_trial.py")
        payload = self._write_lock(holder)
        self.assertNotIn("marker", payload)
        self.assertFalse(trial_driver.lock_is_live(payload, marker="rcb_trial.py"))

    def test_a_second_driver_of_the_same_kind_stands_down(self) -> None:
        """End to end through ``acquire_lock``: the refusal, not just the predicate.

        Without the marker this call took the lock over and returned, and two drivers
        then spent one quota. The pid is in the message because the operator's next move
        is to look at it.
        """
        holder = self._live_driver("other_trial.py")
        self._write_lock(holder)
        with self.assertRaises(SystemExit) as caught:
            trial_driver.acquire_lock(self.state, marker="other_trial.py")
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
        too, so the keyword-only assertions above are each capable of failing on a real
        signature in the same file; and ``sample``'s ``b`` shows the default check can
        tell an optional parameter from a required one. The same two checks are made of
        ``autor_pids``'s ``markers`` below.
        """
        state_dir = inspect.signature(trial_driver.acquire_lock).parameters["state_dir"]
        self.assertIsNot(state_dir.kind, inspect.Parameter.KEYWORD_ONLY)

        def sample(a, *, b="x"):
            return a, b

        self.assertIsNot(
            inspect.signature(sample).parameters["b"].default, inspect.Parameter.empty
        )

    def test_the_child_census_answers_for_the_driver_that_asks_and_no_other(self) -> None:
        """``autor_pids`` is "is a pid *I* launched still alive", so the caller says who.

        Two live processes, one shaped like each driver's child. Each driver's markers
        must find its own and miss the other's -- the miss as much as the hit, because
        the caller uses this as a membership test for a child pid it recorded itself, and
        a set that is too wide makes a dead run look like it is still going.

        The literals used to be in the kernel's body: ``rcb_agent.py`` and
        ``rcb_trial.py fake-run``, under a docstring that said the function answered for
        anybody. Any other benchmark's driver calling it would have got a set that never
        contains its own children, read every live run of its own as dead, and abandoned
        it -- fresh workspace, new opus run, beside the one still executing. That is a
        counterfactual and stays one: the second driver it was written against belonged to
        a benchmark since removed, and the literals were pulled out before it happened.
        ``fire_agent.py`` is the front end it would happen to next, which is why it is the
        one here.
        """
        rcb_child = self._live_driver("rcb_agent.py")
        fire_child = self._live_driver("fire_agent.py")
        self.assertIn(rcb_child.pid, trial_driver.autor_pids(markers=("rcb_agent.py",)))
        self.assertNotIn(fire_child.pid, trial_driver.autor_pids(markers=("rcb_agent.py",)))
        self.assertIn(fire_child.pid, trial_driver.autor_pids(markers=("fire_agent.py",)))
        self.assertNotIn(rcb_child.pid, trial_driver.autor_pids(markers=("fire_agent.py",)))

    def test_the_child_census_has_no_markers_of_its_own(self) -> None:
        """The gate, and the reason it is stricter than the lock's.

        ``markers`` is keyword-only and required for the same reason ``marker`` is, with
        one difference that matters: the version this replaced did not have a bad
        *default*, it had one benchmark's names in the function body, which a second
        driver cannot override at all.
        """
        markers = inspect.signature(trial_driver.autor_pids).parameters["markers"]
        self.assertIs(markers.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(
            markers.default,
            inspect.Parameter.empty,
            "autor_pids answers for whoever asks; a default answers for one of them",
        )


class AgentScriptNamesTests(unittest.TestCase):
    """The second hazard: a ``/proc`` census that has never heard of the other agent.

    ``is_backed_run`` is what ``foreign_runs`` asks about every pid on the box before a
    driver will start, and the answer is "is this process going to spend the quota I am
    about to spend". With a front end missing from the table, the ResearchClawBench
    driver walks past six live children of a second benchmark's front end, reports a
    clean box, and starts a seventh opus run -- which is the concurrency that exhausts
    the quota that then kills all seven. The front end that was missing from the chain
    has since been deleted along with its benchmark; the table is what stops the next one
    being missed, so what these tests hold is the *table*, not any one benchmark's name.
    """

    def test_every_script_the_constant_names_is_recognised(self) -> None:
        """Over the constant, so the predicate has to be the thing that reads it.

        A test that hard-coded ``fire_agent.py`` would go green the moment the name was
        added to the tuple and stay green if the function never read the tuple -- the
        constant ``_RUN_SCRIPTS`` this replaced was declared, correct, and read by
        nothing at all for the whole life of the driver.

        What this does *not* catch is a name being **added**: ``is_backed_run`` walks the
        table generically, so a new key is recognised by construction and this test goes
        green on it -- measured, by adding ``"studio.py": ()`` and watching it pass. The
        guard for the population is
        :meth:`test_the_constant_names_every_agent_and_the_goal_entry_point`, which is
        the test that entry fails.
        """
        for script, required in trial_driver.AGENT_SCRIPT_NAMES.items():
            with self.subTest(script=script):
                argv = ["python3", f"/home/u/AutoR/{script}", *required, "--model", "opus"]
                self.assertTrue(trial_driver.is_backed_run(argv))

    def test_the_constant_names_every_agent_and_the_goal_entry_point(self) -> None:
        """What "every benchmark" means, pinned. The front ends, and ``main.py``.

        This is the population guard: recognition is by construction once a key is in the
        table, so the only thing left to check is which keys are in it. A name added
        without an argument fails here, and here is the only place it fails.

        It went from two front ends to three when ``fire_agent.py`` landed, and back to
        two when a benchmark was removed from this repository and its front end with it.
        That is the whole reason this test is worth its line count, and it is worth it in
        both directions: a driver whose census cannot see a front end reads a live run as
        "nobody is spending the quota" and launches beside it, and a key for a script
        nobody can run tells the next reader a front end exists that does not. Neither
        edit to the table is visible anywhere else -- ``is_backed_run`` reads it
        generically and goes green on any population at all -- so this assertion is the
        record of what the census currently knows about.
        """
        self.assertEqual(
            sorted(trial_driver.AGENT_SCRIPT_NAMES),
            ["fire_agent.py", "main.py", "rcb_agent.py"],
        )

    def test_a_firebench_run_is_a_run(self) -> None:
        argv = ["python3", "/home/u/AutoR/fire_agent.py", "--task", "cot_in_planning", "--model", "opus"]
        self.assertTrue(trial_driver.is_backed_run(argv))

    def test_a_researchclawbench_run_is_a_run(self) -> None:
        argv = ["python3", "/home/u/AutoR/rcb_agent.py", "--workspace", "/w", "--model", "opus"]
        self.assertTrue(trial_driver.is_backed_run(argv))

    def test_a_fake_operator_run_contends_for_nothing(self) -> None:
        """What the test suite runs, constantly. It makes no backend call.

        A driver that stands down for the unit tests never starts on a machine anybody is
        developing on, and this box is one.
        """
        argv = ["python3", "/home/u/AutoR/rcb_agent.py", "--fake-operator", "--workspace", "/w"]
        self.assertFalse(trial_driver.is_backed_run(argv))

    def test_a_shell_that_merely_names_an_agent_is_not_a_run(self) -> None:
        """Why ``process_argv`` splits on NUL instead of joining.

        The diagnostic one-liner somebody types to ask whether a run is up has the script
        name in its joined command line. Ten minutes per false refusal, and on a busy box
        the trial never starts at all.
        """
        self.assertFalse(
            trial_driver.is_backed_run(["/bin/bash", "-c", 'pgrep -af "fire_agent.py" | head'])
        )
        self.assertFalse(trial_driver.is_backed_run(["grep", "-rn", "fire_agent.py", "/home/u"]))
        self.assertFalse(trial_driver.is_backed_run(["/usr/bin/fire_agent.py"]))

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

    def test_the_census_sees_a_live_agent(self) -> None:
        """The producer, not just the predicate, against three real processes.

        Every other test here hands ``is_backed_run`` an argv it built. That leaves
        ``foreign_runs`` free to go on matching whatever it likes -- which is how the
        original substring match survived being wrong.

        All three processes are waited for, not just the one the positive assertion is
        about. ``Popen`` returns before the child has exec'd, and until it does its
        ``/proc`` command line is empty -- so a census taken too early omits the fake
        operator and the mention for the most boring reason there is, and the two
        ``assertNotIn``s pass without having looked at anything. Waiting on the same
        ``/proc`` read that ``foreign_runs`` performs is what makes them refusals.
        """
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fire_agent.py"
            script.write_text("import time; time.sleep(30)\n", encoding="utf-8")
            real = subprocess.Popen([sys.executable, str(script), "--workspace", tmp])
            faked = subprocess.Popen(
                [sys.executable, str(script), "--fake-operator", "--workspace", tmp]
            )
            mention = subprocess.Popen(
                ["/bin/sh", "-c", "sleep 30 # fire_agent.py --workspace x"]
            )
            try:
                deadline = time.time() + 10
                for proc in (real, faked, mention):
                    while time.time() < deadline and "fire_agent.py" not in (
                        trial_driver.process_cmdline(proc.pid)
                    ):
                        time.sleep(0.05)
                    self.assertIn(
                        "fire_agent.py",
                        trial_driver.process_cmdline(proc.pid),
                        f"pid {proc.pid} never exec'd; an assertion about a process that "
                        "does not exist yet measures nothing",
                    )
                listed = trial_driver.foreign_runs()
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
    """Two properties of the kernel that no other test in the tree holds.

    Not a re-run of the driver's suite -- the identity assertions above mean that suite
    is already testing these functions, and a test that repeats one of them verbatim
    doubles the count without holding anything. One is here because it depends on the
    *module* rather than on the function: ``os.getpid()`` and ``sys.argv`` are read at
    call time and a move is exactly the kind of edit that turns one into a stale import.
    The other is here because the property the module docstring sells the kernel on --
    atomic state writes for a directory on shared NFS -- was, until this test, asserted
    by nothing anywhere.
    """

    def test_a_state_file_is_only_ever_reached_through_os_replace(self) -> None:
        """The mechanism, because the outcome cannot tell the two implementations apart.

        ``write_json`` exists for the tmp-and-``os.replace`` dance: ``/home`` here is
        shared NFS, a driver is killed with ``kill -9`` as a matter of routine, and a
        state file caught half-written is a run whose phase nobody can read. The test
        that used to be here asserted the *result* -- the file reads back as the second
        payload, and no ``.tmp`` is left behind -- and both of those are true of
        ``path.write_text(json.dumps(...))``, which has no atomicity at all. Replacing
        the body with that one line left the whole 176-test suite green.

        So: ``os.replace`` is intercepted and does nothing, and what the target file
        holds afterwards is the answer. A direct write has already destroyed the old
        payload by this point, and it never called ``os.replace`` at all. The source
        being complete and in the same directory as the target is the other half -- a
        rename is atomic only within one filesystem, and only a fully written source is
        worth renaming.

        Nothing here re-asserts that a real write round-trips. The driver's own suite
        does, in ``StateTests``, and so does every dry run; two tests of one name holding
        one property between them was the problem, not the coverage.
        """
        seen: list[tuple[Path, Path]] = []

        def spy(src, dst) -> None:
            seen.append((Path(src), Path(dst)))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs" / "a.json"
            trial_driver.write_json(path, {"a": 1})
            real_replace = os.replace
            os.replace = spy
            try:
                trial_driver.write_json(path, {"a": 2})
            finally:
                os.replace = real_replace

            self.assertEqual(len(seen), 1, "the target was written without a rename")
            source, target = seen[0]
            self.assertEqual(target, path)
            self.assertEqual(source.parent, path.parent)
            self.assertEqual(json.loads(source.read_text(encoding="utf-8")), {"a": 2})
            self.assertEqual(
                trial_driver.read_json(path),
                {"a": 1},
                "the old payload was gone before the rename, so a crash mid-write loses it",
            )

    def test_a_lock_this_process_took_records_this_process(self) -> None:
        """``os.getpid`` and ``sys.argv`` are read inside the kernel now.

        The release path compares the recorded pid against ``os.getpid()``, so a lock
        written with anything else is a lock nobody can release. The marker is recorded
        for a harder reason: it is what the *next* driver reads back to decide whether
        this lock is live, so dropping the field turns every cross-kind liveness question
        back into the asker's own name. Deleting it from the payload used to leave all
        176 tests green.
        """
        with tempfile.TemporaryDirectory() as tmp:
            lock = trial_driver.acquire_lock(Path(tmp), marker="rcb_trial.py")
            payload = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(payload["argv"], sys.argv)
            self.assertEqual(payload["marker"], "rcb_trial.py")
            trial_driver.release_lock(lock)
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
