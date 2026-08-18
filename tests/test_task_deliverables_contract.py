"""Does the report answer what the task asked?

Every other AutoR gate measures how *well* a stage worked. None asked the prior question.

Observed on ResearchClawBench Astronomy_000. The task statement said "derive statistically
rigorous upper limits on ULB masses **and self-interaction coupling strengths**". The run
delivered a rigorous mass exclusion band and no coupling limit. Its own rubric scored
1.000. The scored criterion asking for the coupling constant in GeV^-1 scored 25/100 and
carried half the task's weight, and nothing in the pipeline noticed.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.deliverables import (
    COVERAGE_FILENAME,
    demanding_sentences,
    format_deliverables_for_prompt,
    research_brief,
    task_demands,
    validate_deliverables_coverage,
)
from src.utils import STAGES, build_prompt, build_run_paths, ensure_run_layout, write_text

# The real statement, trimmed to the sentence the run failed.
# One demanding sentence, so a single quote can legitimately cover the whole task and
# the pass-cases below test the gate rather than the fixture.
TASK = (
    "The dataset holds posterior samples for two black holes. "
    "The goal is to derive statistically rigorous upper limits on ULB masses and "
    "self-interaction coupling strengths, using astrophysical data to probe particle physics."
)

#: Two demands, for the case where a stage answers one and quietly drops the other.
TWO_DEMAND_TASK = (
    "The goal is to derive upper limits on ULB masses and self-interaction coupling strengths. "
    "Separately, compare the box method against the full posterior approach on both objects."
)
MASS_QUOTE = "derive statistically rigorous upper limits on ULB masses and self-interaction coupling strengths"


class DemandExtractionTest(unittest.TestCase):
    def test_it_finds_the_sentence_that_was_missed(self) -> None:
        found = demanding_sentences(TASK)
        self.assertTrue(any("coupling strengths" in s for s in found))

    def test_context_without_a_demand_verb_is_not_a_demand(self) -> None:
        self.assertEqual(demanding_sentences(
            "The dataset contains posterior samples. It was collected in 2019."), [])

    def test_a_fragment_is_too_short_to_be_a_demand(self) -> None:
        self.assertEqual(demanding_sentences("Derive it."), [])

    def test_bullet_markers_do_not_hide_a_demand(self) -> None:
        found = demanding_sentences("- Compare the box method against the full posterior approach.")
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0].startswith("-"))

    def test_an_output_written_as_a_noun_phrase_is_still_a_demand(self) -> None:
        """Physics_000's brief, verbatim in shape.

        Two of its three outputs are noun phrases with no demand verb in them, and the
        two graded criteria they name carry 0.70 of that task's weight. Before the
        `Output:` block was read, `task_demands` returned neither, so neither reached
        `# What the Task Asks For` and neither could be a row in the coverage file.
        """
        brief = (
            "Input:  1. Particle types and sizes: Atoms of varying sizes.  "
            "2. Path rules: Shell sequence paths defined in the hexagonal lattice.  "
            "Output:  1. Predicted stable multi-shell icosahedral structures for the alloy.  "
            "2. Optimal size mismatch values between adjacent shells.  "
            "3. Shell sequences and paths formed via self-assembly in growth simulations.  "
            "Scientific Objective: To establish a universal theoretical framework."
        )
        found = demanding_sentences(brief)
        self.assertIn("Optimal size mismatch values between adjacent shells.", found)
        self.assertIn(
            "Shell sequences and paths formed via self-assembly in growth simulations.", found
        )
        # The input side stays out: a description of what the run *has* is not a
        # description of what it *owes*, which is the same line `_BRIEF_HEADINGS` holds.
        self.assertFalse(any("Particle types and sizes" in s for s in found))
        self.assertFalse(any("Path rules" in s for s in found))

    def test_a_single_line_output_label_is_a_demand(self) -> None:
        brief = (
            "Input: Global atmospheric reanalysis data at 0.25 degree resolution.  "
            "Output: 15-day global weather forecasts at 6-hour temporal resolution.  "
            "Scientific Goal: Build a cascade forecasting system."
        )
        found = demanding_sentences(brief)
        self.assertTrue(
            any("15-day global weather forecasts" in s for s in found),
            f"the labelled output was dropped: {found}",
        )

    def test_every_demand_is_a_verbatim_span_of_the_statement(self) -> None:
        """The coverage gate refuses a `task_quote` that is not verbatim.

        Admitting the output block must not change that: the block capture starts after
        the label, and a quote reconstructed from it would not be findable in the source.
        """
        brief = (
            "Output:  1. Predicted stable multi-shell icosahedral structures for the alloy.  "
            "2. Optimal size mismatch values between adjacent shells.  "
            "Scientific Objective: To establish a universal theoretical framework."
        )
        normalised = " ".join(brief.split())
        for sentence in demanding_sentences(brief):
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, normalised)


class DemandsComeFromTheTaskNotTheWrapperTest(unittest.TestCase):
    """AutoR's own prose is not a requirement the report owes an answer to.

    A goal is not always only the question: the benchmark adapter builds one carrying a
    workspace contract, a grading rubric and a figure budget around the task. Read off
    the whole thing, `demanding_sentences` returned 23 demands for Astronomy_000 against
    the task's 10 — 857 against 337 across all 40 shipped tasks, so 61% of what every
    stage was told it owed was AutoR talking to itself. The first phantom demand was
    literally "Benchmark Run: ResearchClawBench".
    """

    def _wrapped(self) -> str:
        from src.rcb import build_benchmark_goal

        with tempfile.TemporaryDirectory() as tmp:
            return build_benchmark_goal(Path(tmp).resolve(), TASK)

    def test_the_wrapper_contributes_no_demands(self) -> None:
        from src.utils import task_statement

        goal = self._wrapped()
        self.assertGreater(len(demanding_sentences(goal)), len(demanding_sentences(TASK)))
        self.assertEqual(demanding_sentences(task_statement(goal)), demanding_sentences(TASK))

    def test_the_prompt_block_does_not_ask_for_the_benchmark_contract(self) -> None:
        from src.utils import task_statement

        block = format_deliverables_for_prompt(task_statement(self._wrapped()))
        self.assertIn("coupling strengths", block)
        self.assertNotIn("ResearchClawBench", block)
        self.assertNotIn("Workspace Contract", block)

    def test_a_goal_nobody_wrapped_is_read_whole(self) -> None:
        from src.utils import task_statement

        self.assertEqual(task_statement(TASK), TASK)


class TheDeliveryContractIsNotTheResearchQuestionTest(unittest.TestCase):
    """`task_statement` stripped AutoR's wrapper and left the benchmark's inner one.

    Measured over the 40 archived ResearchClawBench tasks: 337 demanding sentences, of
    which 200 (59.3%) are five lines identical in all 40 -- "Read & Understand", "Code &
    Execute", "Analyze & Report", "produce a high-quality report/report.md", "Figures are
    mandatory". Information_002 was told, in every prompt from Stage 01 to Stage 08, that
    five sixths of what it owed was to read the related work and save PNGs. It did all
    five and scored 0, because the sixth was the physics.
    """

    #: The shape of a shipped task: a brief under headings, wrapped in a delivery contract.
    BENCHMARK_SHAPED = (
        "## Role\n\n"
        "1. **Read & Understand** - Study the related work and data to build domain context.\n"
        "2. **Code & Execute** - Implement the analysis, generate figures, and iterate.\n\n"
        "## Research Task\n\n"
        "### Task Description\n"
        "Input posterior samples for two black holes; output statistically rigorous upper "
        "limits on ULB masses and self-interaction coupling strengths.\n\n"
        "## Execution Protocol\n\n"
        "Your primary goal is to complete the research task and produce a high-quality "
        "`report/report.md`.\n"
        "**Figures are mandatory** - generate plots and save to `report/images/`.\n"
    )

    def test_the_contract_lines_are_not_counted_as_demands(self) -> None:
        demands = task_demands(self.BENCHMARK_SHAPED)
        joined = " ".join(demands)
        self.assertNotIn("Figures are mandatory", joined)
        self.assertNotIn("Read & Understand", joined)
        self.assertNotIn("report/report.md", joined)

    def test_a_semicolon_separates_two_named_outputs(self) -> None:
        """Information_002's whole brief was one sentence with three outputs in it."""
        demands = task_demands(self.BENCHMARK_SHAPED)
        self.assertEqual(len(demands), 2)
        self.assertTrue(demands[0].startswith("Input posterior samples"))
        self.assertIn("coupling strengths", demands[1])

    def test_the_contract_still_reaches_the_stage_unnumbered(self) -> None:
        """Removed from the question, not from the prompt: the stage still owes figures."""
        block = format_deliverables_for_prompt(self.BENCHMARK_SHAPED)
        self.assertIn("How to deliver, which is not what to find", block)
        self.assertIn("Figures are mandatory", block)
        self.assertLess(block.index("coupling strengths"),
                        block.index("How to deliver"))

    def test_a_brief_with_no_demand_verb_still_yields_its_sentences(self) -> None:
        """Some briefs are machine-concatenated ("features.Output:") and split badly."""
        statement = (
            "### Task Description\n"
            "Input: Network traffic flow data with temporal and topological features."
            "Output: Intrusion detection over known and few-shot attack scenarios.\n"
        )
        demands = task_demands(statement)
        self.assertTrue(demands)
        self.assertIn("Intrusion detection", " ".join(demands))

    def test_a_free_form_goal_with_no_headings_is_unchanged(self) -> None:
        self.assertEqual(task_demands(TASK), demanding_sentences(TASK))
        self.assertEqual(task_demands("Some background prose about black holes."), [])

    def test_the_gate_holds_the_narrowed_population_and_not_the_wide_one(self) -> None:
        """The one line that gives the coverage gate any teeth, pinned.

        `_uncovered_demands` reads `task_demands`, not `demanding_sentences`. Reverting
        that single call left the whole suite green while taking the gate from firing on
        3 of 40 archived runs back to 0 of 40 — its entire measurable effect, uncovered.
        Asserted behaviourally rather than by reading the source: a record that accounts
        only for the delivery contract must not satisfy a brief that asks for something
        else.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, self.BENCHMARK_SHAPED)
        write_text(paths.report_file, "# Report\n\n## Findings\n\nSee images/f.png\n")
        write_text(
            paths.artifacts_dir / COVERAGE_FILENAME,
            json.dumps({"deliverables": [{
                "task_quote": "Figures are mandatory",
                "addressed": True,
                "where": "## Findings",
            }]}),
        )
        problems = validate_deliverables_coverage(paths, self.BENCHMARK_SHAPED)
        self.assertTrue(
            any("does not account for what the task asked" in p for p in problems),
            problems,
        )
        self.assertTrue(any("coupling strengths" in p or "ULB" in p for p in problems), problems)

    def test_the_brief_is_the_headed_part_only(self) -> None:
        brief = research_brief(self.BENCHMARK_SHAPED)
        self.assertIn("coupling strengths", brief)
        self.assertNotIn("Figures are mandatory", brief)


class CoverageGateTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, TASK)
        write_text(self.paths.report_file,
                   "# Report\n\n## Coupling Limits\n\nSee images/fig1_coupling.png\n")

    def _write(self, payload) -> None:
        write_text(self.paths.artifacts_dir / COVERAGE_FILENAME, json.dumps(payload))

    def _check(self):
        return validate_deliverables_coverage(self.paths, TASK)

    def test_a_missing_file_is_a_problem(self) -> None:
        self.assertIn(COVERAGE_FILENAME, " ".join(self._check()))

    def test_invalid_json_is_a_problem(self) -> None:
        write_text(self.paths.artifacts_dir / COVERAGE_FILENAME, "{not json")
        self.assertIn("not valid JSON", " ".join(self._check()))

    def test_an_empty_list_is_a_problem(self) -> None:
        self._write({"deliverables": []})
        self.assertIn("non-empty", " ".join(self._check()))

    def test_a_covered_addressed_deliverable_passes(self) -> None:
        self._write({"deliverables": [
            {"task_quote": MASS_QUOTE, "addressed": True, "where": "Coupling Limits"}]})
        self.assertEqual(self._check(), [])

    def test_an_honestly_unmet_deliverable_passes(self) -> None:
        """Reporting a requirement as unmet is a valid outcome; omitting it is not."""
        self._write({"deliverables": [
            {"task_quote": MASS_QUOTE, "addressed": False,
             "reason": "the coupling derivation did not converge in the time available"}]})
        self.assertEqual(self._check(), [])

    def test_an_unmet_deliverable_with_no_reason_fails(self) -> None:
        self._write({"deliverables": [{"task_quote": MASS_QUOTE, "addressed": False}]})
        self.assertIn("gives no reason", " ".join(self._check()))

    def test_a_paraphrased_quote_is_rejected(self) -> None:
        """The teeth. Without this a stage restates the requirement as one it already met."""
        self._write({"deliverables": [
            {"task_quote": "derive limits on boson masses", "addressed": True,
             "where": "Coupling Limits"}]})
        self.assertIn("not in the task statement", " ".join(self._check()))

    def test_a_verbatim_quote_survives_rewrapping(self) -> None:
        self._write({"deliverables": [
            {"task_quote": "derive statistically rigorous\n  upper limits on ULB masses and "
                           "self-interaction coupling strengths",
             "addressed": True, "where": "Coupling Limits"}]})
        self.assertEqual(self._check(), [])

    def test_answering_only_part_of_the_task_is_caught(self) -> None:
        """The observed failure shape: satisfy one demand, quietly drop the other."""
        write_text(self.paths.user_input, TWO_DEMAND_TASK)
        self._write({"deliverables": [
            {"task_quote": "derive upper limits on ULB masses and self-interaction coupling "
                           "strengths", "addressed": True, "where": "Coupling Limits"}]})
        problems = validate_deliverables_coverage(self.paths, TWO_DEMAND_TASK)
        self.assertIn("does not account for what the task asked", " ".join(problems))
        self.assertIn("box method", " ".join(problems))

    def test_covering_both_demands_passes(self) -> None:
        write_text(self.paths.user_input, TWO_DEMAND_TASK)
        write_text(self.paths.report_file,
                   "# Report\n\n## Coupling Limits\n\n## Box Method Comparison\n")
        self._write({"deliverables": [
            {"task_quote": "derive upper limits on ULB masses and self-interaction coupling "
                           "strengths", "addressed": True, "where": "Coupling Limits"},
            {"task_quote": "compare the box method against the full posterior approach on both "
                           "objects", "addressed": True, "where": "Box Method Comparison"}]})
        self.assertEqual(validate_deliverables_coverage(self.paths, TWO_DEMAND_TASK), [])

    def test_a_fabricated_location_is_caught(self) -> None:
        self._write({"deliverables": [
            {"task_quote": MASS_QUOTE, "addressed": True, "where": "Section 9: Coupling Tables"}]})
        self.assertIn("does not appear in report.md", " ".join(self._check()))

    def test_a_figure_reference_counts_as_a_location(self) -> None:
        self._write({"deliverables": [
            {"task_quote": MASS_QUOTE, "addressed": True, "where": "images/fig1_coupling.png"}]})
        self.assertEqual(self._check(), [])

    def test_addressed_must_be_a_boolean(self) -> None:
        self._write({"deliverables": [{"task_quote": MASS_QUOTE, "addressed": "yes"}]})
        self.assertIn("boolean", " ".join(self._check()))

    def test_a_bare_list_is_accepted_as_well_as_the_wrapper(self) -> None:
        self._write([{"task_quote": MASS_QUOTE, "addressed": True, "where": "Coupling Limits"}])
        self.assertEqual(self._check(), [])


class PromptBlockTest(unittest.TestCase):
    def test_the_block_lists_what_the_task_demands(self) -> None:
        block = format_deliverables_for_prompt(TASK)
        self.assertIn("coupling strengths", block)
        self.assertIn(COVERAGE_FILENAME, block)

    def test_it_says_the_quote_must_be_verbatim(self) -> None:
        self.assertIn("verbatim", format_deliverables_for_prompt(TASK))

    def test_it_says_an_unmet_requirement_must_be_reported(self) -> None:
        self.assertIn("Omitting a requirement is never an option",
                      format_deliverables_for_prompt(TASK))

    def test_an_unmet_requirement_must_first_be_checked_for_runnability(self) -> None:
        """`addressed: false` is for what could not be done, not for what was re-scoped.

        Information_002 declined its Task Description clause and its only named data
        file, with reasons, and passed the gate at 0.0. The reviewer side already applies
        this test (`src/approval_agent.py`: is the named work runnable from what is in
        this workspace?); before this the executing side was not told about it.
        """
        block = format_deliverables_for_prompt(TASK)
        self.assertIn("runnable from what is in this workspace", block)
        self.assertIn("not a way to narrow the task", block)

    def test_a_statement_with_no_demands_yields_no_block(self) -> None:
        self.assertEqual(format_deliverables_for_prompt("Some background prose."), "")

    def test_the_block_reaches_the_stage_prompt(self) -> None:
        prompt = build_prompt(STAGES[6], "template", TASK, "memory")
        self.assertIn("# What the Task Asks For", prompt)
        self.assertIn("coupling strengths", prompt)

    def test_a_goal_with_no_demands_adds_no_heading(self) -> None:
        prompt = build_prompt(STAGES[6], "template", "Background only.", "memory")
        self.assertNotIn("# What the Task Asks For", prompt)


class AddressedWithoutALocationTest(CoverageGateTest):
    def test_addressed_but_no_where_is_a_problem(self) -> None:
        """"Yes we did it" with no pointer is the easiest way to pass a coverage check
        without having covered anything."""
        self._write({"deliverables": [{"task_quote": MASS_QUOTE, "addressed": True}]})
        self.assertIn("does not say where", " ".join(self._check()))

    def test_a_blank_where_is_the_same_as_none(self) -> None:
        self._write({"deliverables": [
            {"task_quote": MASS_QUOTE, "addressed": True, "where": "   "}]})
        self.assertIn("does not say where", " ".join(self._check()))


class TheStageGateCallsItTest(unittest.TestCase):
    """Through `validate_stage_artifacts`, not just the validator in isolation.

    A checker nothing calls is the same as no checker.
    """

    def _paths_with_complete_report(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, TASK)
        write_text(paths.report_file, "# Report\n\n## Coupling Limits\n\ntext\n")
        return paths

    def test_stage_07_markdown_reports_the_missing_artifact(self) -> None:
        from src.utils import validate_stage_artifacts

        paths = self._paths_with_complete_report()
        problems = " ".join(validate_stage_artifacts(STAGES[6], paths))
        self.assertIn(COVERAGE_FILENAME, problems)

    def test_an_earlier_stage_is_not_asked_for_it(self) -> None:
        """The contract is a Stage 07 gate; Stage 03 has no report to check it against."""
        from src.utils import validate_stage_artifacts

        paths = self._paths_with_complete_report()
        problems = " ".join(validate_stage_artifacts(STAGES[2], paths))
        self.assertNotIn(COVERAGE_FILENAME, problems)


class CoverageIsNotAMarkdownQuestionTest(unittest.TestCase):
    """The gate that asks whether the run answered the brief, asked of a latex run too.

    It sat inside `if stage.number >= 7 and selected_output_format(paths) == "markdown"`.
    That condition arrived with the change making markdown the default report format and
    the coverage check was appended inside it, so a latex run was never asked whether it
    covered the task. Measured over 335 archived run configs every one is `markdown`, so
    no archived run changes verdict -- which is also why nothing noticed.

    Two halves, and both need holding: the gate has to *run* for a latex stage, and the
    locator check inside it has to have a document to read, or it degrades to a skip with
    no counter.
    """

    def _paths(self, output_format: str):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, TASK)
        write_text(paths.run_config, json.dumps({"output_format": output_format}))
        return paths

    def _cover(self, paths, **entry):
        write_text(paths.artifacts_dir / COVERAGE_FILENAME,
                   json.dumps({"deliverables": [{"task_quote": MASS_QUOTE, **entry}]}))

    def test_a_latex_stage_is_asked_for_the_coverage_artifact(self) -> None:
        from src.utils import validate_stage_artifacts

        paths = self._paths("latex")
        write_text(paths.writing_dir / "main.tex", r"\section{Coupling Limits}")
        problems = " ".join(validate_stage_artifacts(STAGES[6], paths))
        self.assertIn(COVERAGE_FILENAME, problems)

    def test_a_markdown_stage_is_still_asked(self) -> None:
        """Control: the move must not take the check off the format that had it."""
        from src.utils import validate_stage_artifacts

        paths = self._paths("markdown")
        write_text(paths.report_file, "# Report\n")
        problems = " ".join(validate_stage_artifacts(STAGES[6], paths))
        self.assertIn(COVERAGE_FILENAME, problems)

    def test_a_locator_is_checked_against_the_tex_sources(self) -> None:
        paths = self._paths("latex")
        write_text(paths.writing_dir / "main.tex", r"\section{Coupling Limits}" + "\ntext\n")
        self._cover(paths, addressed=True, where="Coupling Limits")
        self.assertEqual(validate_deliverables_coverage(paths, TASK), [])

    def test_a_locator_that_points_nowhere_in_the_tex_is_refused(self) -> None:
        """The half that used to fall through: no report.md, so no check at all."""
        paths = self._paths("latex")
        write_text(paths.writing_dir / "main.tex", r"\section{Mass Limits}" + "\ntext\n")
        self._cover(paths, addressed=True, where="Coupling Limits")
        problems = " ".join(validate_deliverables_coverage(paths, TASK))
        self.assertIn("does not appear in", problems)
        self.assertIn("main.tex", problems)

    def test_sections_under_writing_are_read_too(self) -> None:
        paths = self._paths("latex")
        write_text(paths.writing_dir / "main.tex", r"\input{sections/results}")
        write_text(paths.writing_dir / "sections" / "results.tex", r"\subsection{Coupling Limits}")
        self._cover(paths, addressed=True, where="Coupling Limits")
        self.assertEqual(validate_deliverables_coverage(paths, TASK), [])

    def test_with_no_deliverable_at_all_the_locator_still_fails_open(self) -> None:
        """A stage that has written nothing is caught by the gates that check for one.

        Two refusals for one condition is one too many, and the second is the one nobody
        maintains.
        """
        paths = self._paths("latex")
        self._cover(paths, addressed=True, where="Coupling Limits")
        self.assertEqual(validate_deliverables_coverage(paths, TASK), [])


class RefinementTurnsKeepTheContractTest(unittest.TestCase):
    """A contract that only appears on the first attempt is one every retry can forget.

    Stage 07 took nine attempts on the observed run. If the requirement is stated once and
    then drops out, the attempt that finally passes is the one that never saw it.
    """

    def _continuation(self, statement: str) -> str:
        from src.utils import build_continuation_prompt

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, statement)
        return build_continuation_prompt(STAGES[6], "template", paths, "handoff", "feedback")

    def test_a_retry_still_sees_what_the_task_asked(self) -> None:
        prompt = self._continuation(TASK)
        self.assertIn("# What the Task Asks For", prompt)
        self.assertIn("coupling strengths", prompt)

    def test_both_builders_agree(self) -> None:
        from src.utils import build_prompt

        first = build_prompt(STAGES[6], "template", TASK, "memory")
        retry = self._continuation(TASK)
        for prompt in (first, retry):
            self.assertIn("# What the Task Asks For", prompt)

    def test_a_goal_with_no_demands_adds_nothing_on_retry(self) -> None:
        self.assertNotIn("# What the Task Asks For", self._continuation("Background only."))
