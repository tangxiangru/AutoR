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
        self.assertIn("Omitting it is not", format_deliverables_for_prompt(TASK))

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
