"""The fence decides what the run thinks it was asked for.

``src.utils.task_statement`` reads what is inside the task fence, and every deliverable
the coverage gate holds a run to comes from there. Fencing the whole ``INSTRUCTIONS.md``
handed the gate the benchmark harness's *operating instructions* as research deliverables.

Measured over the 40 shipped tasks: ``demanding_sentences`` returned **337 demands on the
full sheet and 142 on the research task alone**. The same five phantoms appeared in all
forty runs, and "Read & Understand -- Study the related work" was one of them.

The cost was not abstract. Of the six tasks where AutoR lost most heavily to bare Claude
Code, every one auto-skipped two or three stages, and the single most common validation
error across them -- 24 occurrences -- was Stage 03's plan gate refusing an entry that
"states nothing": a deliverable list padded to cover phantoms, with the unanswerable
entries left blank.
"""

from __future__ import annotations

import unittest

from src.deliverables import demanding_sentences
from src.rcb import fence_research_task
from src.utils import TASK_BEGIN_MARKER, TASK_END_MARKER, task_statement

# The shape of ResearchClawBench's INSTRUCTIONS.md, trimmed to the sections that matter.
SHEET = """## Role

You are an autonomous scientific research agent.

1. **Read & Understand** - Study the related work and data to build domain context.
2. **Code & Execute** - Implement the analysis, generate figures, and iterate.

---

## Research Task

### Task Description
The goal is to derive statistically rigorous upper limits on ULB masses and
self-interaction coupling strengths, and to compare them against the incumbent bound.

### Available Data Files
- **samples.dat**: Contains the posterior distribution samples for the black hole.

---

## Execution Protocol

Your primary goal is to complete the research task and produce a high-quality report.

## Workspace

- **Figures are mandatory** - generate plots and save them to `report/images/`.
"""


class FenceNarrowingTest(unittest.TestCase):
    def _fenced(self, text: str = SHEET) -> str:
        return fence_research_task(text)

    def test_the_research_task_is_what_ends_up_inside_the_fence(self) -> None:
        inner = task_statement(self._fenced())
        self.assertIn("upper limits on ULB masses", inner)
        self.assertIn("samples.dat", inner)

    def test_the_harness_boilerplate_is_outside_the_fence(self) -> None:
        inner = task_statement(self._fenced())
        for phantom in ("Read & Understand", "Code & Execute", "Figures are mandatory",
                        "produce a high-quality report", "autonomous scientific research agent"):
            self.assertNotIn(phantom, inner, f"{phantom!r} is an instruction, not a deliverable")

    def test_the_agent_still_reads_the_whole_sheet(self) -> None:
        # Only the fence moves. Losing the workspace rules would trade one failure for
        # a worse one: figures written somewhere the judge never looks.
        fenced = self._fenced()
        for kept in ("## Role", "## Execution Protocol", "## Workspace",
                     "Figures are mandatory", "Read & Understand"):
            self.assertIn(kept, fenced)

    def test_the_demand_count_drops_to_the_research_task(self) -> None:
        before = demanding_sentences(SHEET)
        after = demanding_sentences(task_statement(self._fenced()))
        self.assertLess(len(after), len(before))
        self.assertTrue(any("upper limits" in s for s in after))
        self.assertFalse(any("Study the related work" in s for s in after))

    def test_a_goal_a_human_typed_is_fenced_whole(self) -> None:
        # No `## Research Task` heading. Narrowing here would delete the question.
        goal = "Work out whether regularizer choice changes which variables look predictive."
        inner = task_statement(fence_research_task(goal))
        self.assertEqual(inner, goal)

    def test_an_empty_research_task_section_falls_back_to_the_whole_sheet(self) -> None:
        # A heading with nothing under it must not fence emptiness: the run would then
        # believe it had been asked for nothing at all.
        sheet = "## Role\n\nBe an agent.\n\n## Research Task\n\n## Workspace\n\nWrite here.\n"
        inner = task_statement(fence_research_task(sheet))
        self.assertIn("Be an agent", inner)

    def test_the_fence_is_well_formed_and_appears_once(self) -> None:
        fenced = self._fenced()
        self.assertEqual(fenced.count(TASK_BEGIN_MARKER), 1)
        self.assertEqual(fenced.count(TASK_END_MARKER), 1)
        self.assertLess(fenced.index(TASK_BEGIN_MARKER), fenced.index(TASK_END_MARKER))

    def test_a_research_task_running_to_the_end_of_the_sheet_still_closes(self) -> None:
        sheet = "## Role\n\nBe an agent.\n\n## Research Task\n\nDerive the bound.\n"
        inner = task_statement(fence_research_task(sheet))
        self.assertEqual(inner, "Derive the bound.")

    def test_the_heading_itself_stays_readable_outside_the_fence(self) -> None:
        # The agent should still see what the section is called.
        self.assertIn("## Research Task", self._fenced())


class BuiltGoalTest(unittest.TestCase):
    """The producer, not the helper.

    Every test above calls ``fence_research_task`` directly, which leaves
    ``build_benchmark_goal`` free to go on fencing the whole sheet -- the actual defect.
    Reverting the call site killed no test until this class existed.
    """

    def _goal(self, sheet: str = SHEET) -> str:
        import tempfile
        from pathlib import Path

        from src.rcb import build_benchmark_goal

        with tempfile.TemporaryDirectory() as tmp:
            return build_benchmark_goal(Path(tmp), sheet)

    def test_the_built_goal_fences_only_the_research_task(self) -> None:
        inner = task_statement(self._goal())
        self.assertIn("upper limits on ULB masses", inner)
        self.assertNotIn("Read & Understand", inner)
        self.assertNotIn("Figures are mandatory", inner)

    def test_the_built_goal_still_carries_the_whole_sheet_for_the_agent(self) -> None:
        goal = self._goal()
        self.assertIn("Read & Understand", goal)
        self.assertIn("## Execution Protocol", goal)

    def test_autors_own_contract_never_leaks_into_the_task(self) -> None:
        """The property the fence exists for, held at the producer.

        Without it the fallbacks are untestable in isolation: an empty fence makes
        ``extract_fenced_task`` return None and ``task_statement`` hand back the whole
        goal -- AutoR's grading contract and workspace rules included, which is the
        phantom-deliverable bug the fence was introduced to fix.
        """
        inner = task_statement(self._goal())
        for wrapper in ("Benchmark Run: ResearchClawBench", "Benchmark Workspace Contract",
                        "How This Report Is Graded"):
            self.assertNotIn(wrapper, inner)

    def test_a_sheet_whose_research_task_section_is_empty_does_not_leak_the_contract(self) -> None:
        sheet = "## Role\n\nBe an agent.\n\n## Research Task\n\n## Workspace\n\nWrite here.\n"
        inner = task_statement(self._goal(sheet))
        self.assertIn("Be an agent", inner)
        self.assertNotIn("How This Report Is Graded", inner)

    def test_a_human_goal_through_the_producer_keeps_its_question(self) -> None:
        inner = task_statement(self._goal("Does regularizer choice change which variables look predictive?"))
        self.assertIn("regularizer choice", inner)
        self.assertNotIn("Benchmark Workspace Contract", inner)


class BenchmarkEntryPointTest(unittest.TestCase):
    def test_the_benchmark_path_has_the_same_retry_budget_as_main(self) -> None:
        """The divergence that turned recoverable stages into skipped ones.

        ``main.py`` removed the attempt ceiling; ``rcb_agent.py`` kept eight, and
        ``rcb_agent.py`` is the entry point that produces every benchmark score. All six
        of the worst-losing tasks auto-skipped stages "after bounded retries were
        exhausted".
        """
        import rcb_agent

        from src.utils import MAX_STAGE_ATTEMPTS

        self.assertEqual(rcb_agent.DEFAULT_MAX_ATTEMPTS, MAX_STAGE_ATTEMPTS)

    def test_the_benchmark_path_does_not_reintroduce_a_number(self) -> None:
        import rcb_agent

        self.assertIsNone(rcb_agent.DEFAULT_MAX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
