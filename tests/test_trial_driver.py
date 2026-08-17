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
"""

from __future__ import annotations

import ast
import importlib.util
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
        benchmark has to work around. ``rcb_agent.py`` is deliberately not in this list:
        recognising an agent by name is the kernel's job, which is a different thing
        from knowing what that agent produces.

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
            lock = trial_driver.acquire_lock(Path(tmp))
            payload = json.loads(lock.read_text(encoding="utf-8"))
            self.assertEqual(payload["pid"], os.getpid())
            self.assertEqual(payload["argv"], sys.argv)
            trial_driver.release_lock(lock)
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
