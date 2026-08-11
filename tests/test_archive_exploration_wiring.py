"""The archive's explore proposer had no caller, so the learning loop was open.

`propose_variant` reads only *believable* payoffs, and `believable()` needs at
least three runs that took an edge and three that did not. A backward edge
nobody has taken has no payoff in either direction, so it never becomes
believable, so nothing ever proposes taking it — and the archive can only learn
about edges the agent already chose on its own.

It is 0 believable edges at any N under a forward-only policy — not a large N, an
infinite one — and `tools/archive_sample_complexity.py` measures exactly that
against the real graph and the real `edge_payoffs`: P(>=1 believable) = 0.00 at
every N it sweeps, up to 1000 runs. `propose_exploration` exists to break that and
was never called outside its own tests.

The instrument had itself rotted quietly: `RunRecord` gained a required `bypassed`
field and the tool crashed on its first record, which the old version of this test
could not notice because it only checked that the file mentioned the right symbol
names. It now builds a record.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def _calls_in(path: Path) -> set[str]:
    """Attribute calls actually made in a file, by AST.

    Not a grep. The first version of this test searched for the string
    `propose_exploration`, and the explanatory comment sitting beside the call
    satisfied it — deleting the call left the test green. A test a comment can
    pass is not a test.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


class ExplorationIsReachableTest(unittest.TestCase):
    def test_something_outside_the_archive_calls_the_explore_proposer(self) -> None:
        callers = [
            path.name
            for path in [REPO_ROOT / "main.py", *(REPO_ROOT / "src").glob("*.py")]
            if path.name != "archive.py" and "propose_exploration" in _calls_in(path)
        ]
        self.assertTrue(
            callers,
            "propose_exploration has no production caller; the exploration loop is open again",
        )

    def test_exploration_runs_only_when_the_evidence_proposer_declines(self) -> None:
        """Exploitation first. Curiosity costs a run, so it is the fallback.

        If exploration ran unconditionally it would compete with a proposal the
        archive can justify, and spend runs on a hunch while holding a measured
        improvement.
        """
        tree = ast.parse((REPO_ROOT / "main.py").read_text(encoding="utf-8"))
        guarded = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.If):
                continue
            calls = {
                inner.func.attr
                for inner in ast.walk(node)
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute)
            }
            if "propose_exploration" in calls and "propose_variant" not in calls:
                guarded = True
        self.assertTrue(
            guarded,
            "propose_exploration is not inside a branch; it must only run when "
            "propose_variant has already declined",
        )

    def test_the_reason_is_recorded_next_to_the_call(self) -> None:
        """The measurement that justifies wiring this is not obvious from the code.

        This used to assert a run count appeared in `main.py`. A literal population
        size is the wrong thing to pin: it came from a file nobody else has, two
        other copies of it in this repo disagreed with it, and it would have stayed
        green forever. What the comment owes the reader is the *instrument*.
        """
        text = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn(
            "archive_sample_complexity",
            text,
            "the comment must name the instrument that measured this, not a bare number",
        )


class SampleComplexityToolTest(unittest.TestCase):
    """The instrument that produced the numbers ships with them."""

    def test_the_tool_exists_and_measures_the_shipped_code(self) -> None:
        tool = REPO_ROOT / "tools" / "archive_sample_complexity.py"
        self.assertTrue(tool.is_file())
        text = tool.read_text(encoding="utf-8")
        for symbol in ("edge_payoffs", "believable", "StageGraph"):
            self.assertIn(symbol, text, f"the tool does not exercise the real {symbol}")

    def test_the_tool_can_still_build_a_record(self) -> None:
        """A silent crash on line one is how it stopped being an instrument.

        Cheap on purpose: the sweep itself takes minutes, but constructing one
        `RunRecord` through the tool's own factory is instant and is the thing that
        breaks when the dataclass gains a field.
        """
        import importlib.util
        import random

        spec = importlib.util.spec_from_file_location(
            "_asc", REPO_ROOT / "tools" / "archive_sample_complexity.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        rng = random.Random(0)
        edges, visited = module.walk(rng, revisit_p=0.15, weighting="uniform")
        record = module.make_record(rng, 0, edges, visited)
        self.assertEqual(record.topology, "adaptive")
        self.assertTrue(record.stage_fitness)

    def test_the_tool_is_not_collected_as_a_test(self) -> None:
        """It is an instrument; it takes minutes and asserts nothing."""
        self.assertFalse((REPO_ROOT / "tests" / "archive_sample_complexity.py").exists())


if __name__ == "__main__":
    unittest.main()
