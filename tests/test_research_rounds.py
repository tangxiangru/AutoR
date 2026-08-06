"""Research rounds: the loop that lets a refuted hypothesis lead somewhere.

Before this, Stages 01-08 ran once. Rollback existed but is a repair mechanism —
something went wrong, redo it — and there was no way to say *we predicted X, X
was wrong, here is round two*. A refuted hypothesis had nowhere to go, so the
only paths from Stage 06 were to write up a result the run did not have or to
roll back and pretend the attempt never happened.

The tests that carry the most weight are the ones about `converged`. An agent
asked "are we done?" says yes, and a run that refuted everything it predicted
will otherwise proceed to write a paper with nothing objecting.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.manager import ResearchManager
from src.research_rounds import (
    DECISIONS,
    current_round_number,
    format_round_status,
    format_rounds_for_prompt,
    latest_round,
    load_rounds,
    read_round_decision,
    record_round,
    resume_stage_slug_for,
    validate_round_decision,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, validate_stage_artifacts, write_text
from tests.prereg_support import write_round_decision, write_validity_chain


REPO_ROOT = Path(__file__).resolve().parent.parent
STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


class RoundTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.results_dir / "metrics.json", '{"acc": 0.9}')

    def refute_everything(self) -> None:
        outcomes = json.loads(self.paths.hypothesis_outcomes.read_text(encoding="utf-8"))
        for entry in outcomes["outcomes"]:
            entry["verdict"] = "refuted"
            entry["rationale"] = "the measured gap fell short of the preregistered rule"
        write_text(self.paths.hypothesis_outcomes, json.dumps(outcomes))


class DecisionContractTest(RoundTestCase):
    def test_stage_06_must_declare_a_decision(self) -> None:
        problems = validate_round_decision(self.paths, STAGE_06)
        self.assertTrue(any("round_decision.json" in problem for problem in problems), problems)

    def test_an_unknown_decision_word_is_refused(self) -> None:
        write_round_decision(self.paths, decision="keep_going")
        problems = validate_round_decision(self.paths, STAGE_06)
        self.assertTrue(any("expected one of" in problem for problem in problems), problems)

    def test_the_vocabulary_has_no_bare_continue(self) -> None:
        """A round that wants another one has to say what it would change."""
        self.assertNotIn("continue", DECISIONS)

    def test_iterating_without_saying_what_changes_is_refused(self) -> None:
        write_round_decision(self.paths, decision="refine_design", what_changes_next="")
        problems = validate_round_decision(self.paths, STAGE_06)
        self.assertTrue(any("does not say what would change" in p for p in problems), problems)

    def test_converging_needs_no_change_plan(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        write_round_decision(self.paths)
        self.assertEqual(validate_round_decision(self.paths, STAGE_06), [])

    def test_a_thin_rationale_is_refused(self) -> None:
        write_round_decision(self.paths, rationale="done")
        problems = validate_round_decision(self.paths, STAGE_06)
        self.assertTrue(any("substantive rationale" in problem for problem in problems), problems)

    def test_stages_before_06_owe_no_decision(self) -> None:
        self.assertEqual(validate_round_decision(self.paths, STAGE_05), [])


class ConvergenceHonestyTest(RoundTestCase):
    """The rule that stops every round declaring victory."""

    def setUp(self) -> None:
        super().setUp()
        write_validity_chain(self.paths, close_first_round=False)
        self.refute_everything()

    def test_converging_with_nothing_supported_is_refused(self) -> None:
        write_round_decision(self.paths)
        problems = validate_round_decision(self.paths, STAGE_06)
        self.assertTrue(any("no preregistered" in problem for problem in problems), problems)

    def test_the_same_round_may_converge_on_a_declared_negative_result(self) -> None:
        """Reporting what does not work is a real contribution. Hiding it is not."""
        write_round_decision(self.paths, negative_result=True)
        self.assertEqual(validate_round_decision(self.paths, STAGE_06), [])

    def test_the_same_round_may_choose_to_iterate_instead(self) -> None:
        write_round_decision(
            self.paths,
            decision="new_hypothesis",
            what_changes_next="Replace H1 with a mechanism-level hypothesis the data can separate.",
        )
        self.assertEqual(validate_round_decision(self.paths, STAGE_06), [])

    def test_a_supported_hypothesis_makes_convergence_unremarkable(self) -> None:
        outcomes = json.loads(self.paths.hypothesis_outcomes.read_text(encoding="utf-8"))
        outcomes["outcomes"][0]["verdict"] = "supported"
        write_text(self.paths.hypothesis_outcomes, json.dumps(outcomes))
        write_round_decision(self.paths)
        self.assertEqual(validate_round_decision(self.paths, STAGE_06), [])


class LedgerTest(RoundTestCase):
    def test_closing_a_round_captures_the_verdicts_alongside_the_decision(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        self.refute_everything()
        write_round_decision(self.paths, negative_result=True)

        entry = record_round(self.paths, acted_on=True)

        assert entry is not None
        self.assertEqual(entry.number, 1)
        self.assertEqual(entry.hypothesis_verdicts, {"H1": "refuted"})
        self.assertTrue(entry.negative_result)

    def test_the_declaration_is_consumed_so_the_next_round_cannot_inherit_it(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        write_round_decision(self.paths)
        record_round(self.paths, acted_on=True)
        self.assertIsNone(read_round_decision(self.paths))

    def test_rounds_accumulate(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        for _ in range(3):
            write_round_decision(self.paths)
            record_round(self.paths, acted_on=True)
        self.assertEqual([item.number for item in load_rounds(self.paths)], [1, 2, 3])
        self.assertEqual(current_round_number(self.paths), 4)

    def test_a_decision_the_budget_blocked_is_recorded_as_not_acted_on(self) -> None:
        """Otherwise the record cannot distinguish converging from merely stopping."""
        write_validity_chain(self.paths, close_first_round=False)
        write_round_decision(
            self.paths, decision="refine_design", what_changes_next="Use a held-out split for tuning."
        )
        entry = record_round(self.paths, acted_on=False, budget_note="round budget spent (1/1)")

        assert entry is not None
        self.assertFalse(entry.acted_on)
        self.assertIn("budget spent", entry.budget_note)
        self.assertIn("wanting refine_design", format_round_status(self.paths, 1))

    def test_the_status_line_distinguishes_a_negative_convergence(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        self.refute_everything()
        write_round_decision(self.paths, negative_result=True)
        record_round(self.paths, acted_on=True)
        self.assertIn("negative result", format_round_status(self.paths, 3))


class ResumeRoutingTest(RoundTestCase):
    def test_refine_design_restarts_at_the_design_stage(self) -> None:
        self.assertEqual(resume_stage_slug_for("refine_design"), "03_study_design")

    def test_new_hypothesis_restarts_at_the_hypothesis_stage(self) -> None:
        self.assertEqual(resume_stage_slug_for("new_hypothesis"), "02_hypothesis_generation")

    def test_converged_and_abandon_do_not_resume(self) -> None:
        self.assertIsNone(resume_stage_slug_for("converged"))
        self.assertIsNone(resume_stage_slug_for("abandon"))


class Stage07GateTest(RoundTestCase):
    def test_writing_requires_a_closed_round(self) -> None:
        problems = validate_round_decision(self.paths, STAGE_07)
        self.assertTrue(any("closed research round" in problem for problem in problems), problems)

    def test_writing_is_refused_after_an_abandoned_round(self) -> None:
        """Writing up a run that decided the question is unanswerable contradicts its record."""
        write_validity_chain(self.paths, close_first_round=False)
        write_round_decision(
            self.paths,
            decision="abandon",
            what_changes_next="Nothing available would settle this within the compute budget.",
        )
        record_round(self.paths, acted_on=True)

        problems = validate_round_decision(self.paths, STAGE_07)
        self.assertTrue(any("concluded `abandon`" in problem for problem in problems), problems)

    def test_writing_proceeds_after_a_converged_round(self) -> None:
        write_validity_chain(self.paths)
        self.assertEqual(validate_round_decision(self.paths, STAGE_07), [])

    def test_writing_proceeds_when_the_budget_stopped_an_iteration(self) -> None:
        write_validity_chain(self.paths, close_first_round=False)
        write_round_decision(
            self.paths, decision="refine_design", what_changes_next="Tune on a development split."
        )
        record_round(self.paths, acted_on=False, budget_note="budget spent")
        self.assertEqual(validate_round_decision(self.paths, STAGE_07), [])

    def test_the_stage_gate_calls_this(self) -> None:
        problems = validate_stage_artifacts(STAGE_07, self.paths)
        self.assertTrue(any("closed research round" in problem for problem in problems), problems)


class PromptCarryForwardTest(RoundTestCase):
    def test_a_later_round_is_told_what_the_earlier_ones_established(self) -> None:
        """Without this a second round repeats the first at full cost."""
        write_validity_chain(self.paths, close_first_round=False)
        self.refute_everything()
        write_round_decision(
            self.paths,
            decision="refine_design",
            what_changes_next="Tune both arms on a development split instead of the reporting split.",
            what_we_learned="The gap disappears once tuning and reporting use different splits.",
        )
        record_round(self.paths, acted_on=True)

        rendered = format_rounds_for_prompt(self.paths)

        self.assertIn("This is round 2", rendered)
        self.assertIn("H1: refuted", rendered)
        self.assertIn("development split", rendered)
        self.assertIn("Do not repeat an earlier round's design", rendered)

    def test_the_first_round_gets_no_block(self) -> None:
        self.assertEqual(format_rounds_for_prompt(self.paths), "")


class ManagerLoopTest(unittest.TestCase):
    """The loop itself: does a decision to iterate actually re-run the stages?"""

    def _manager(self, tmp_dir: str, max_rounds: int):
        from tests.test_manager_smoke import ScriptedSmokeOperator

        operator = ScriptedSmokeOperator()
        manager = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=Path(tmp_dir) / "runs",
            operator=operator,
            output_stream=io.StringIO(),
            max_rounds=max_rounds,
        )
        return operator, manager

    def _iterate_once_then_converge(self, manager, paths):
        """Patch the scripted operator so round 1 asks for a second one."""
        original = manager.operator.run_stage

        def run_stage(stage, prompt, run_paths, attempt_no, continue_session=False):
            result = original(stage, prompt, run_paths, attempt_no, continue_session)
            if stage.number == 6 and not load_rounds(run_paths):
                write_text(
                    run_paths.round_decision,
                    json.dumps(
                        {
                            "decision": "refine_design",
                            "rationale": "The first design could not separate the effect from tuning noise.",
                            "what_we_learned": "The comparison was confounded by tuning on the reporting split.",
                            "what_changes_next": "Tune both arms on a held-out development split and re-run.",
                            "negative_result": False,
                        }
                    ),
                )
            return result

        manager.operator.run_stage = run_stage

    def test_a_round_that_asks_to_iterate_reruns_the_design_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            operator, manager = self._manager(tmp_dir, max_rounds=2)
            paths = manager._create_run("Round loop test.", venue="neurips_2025")
            self._iterate_once_then_converge(manager, paths)

            with patch.object(manager, "_ask_choice", return_value="5"):
                completed = manager._run_from_paths(paths)

            self.assertTrue(completed)
            rounds = load_rounds(paths)
            self.assertEqual([item.decision for item in rounds], ["refine_design", "converged"])
            # Stage 03 ran twice: once per round.
            self.assertEqual(operator.invocations["03_study_design"], 2)

    def test_the_round_budget_stops_the_loop_and_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            operator, manager = self._manager(tmp_dir, max_rounds=1)
            paths = manager._create_run("Round budget test.", venue="neurips_2025")
            self._iterate_once_then_converge(manager, paths)

            with patch.object(manager, "_ask_choice", return_value="5"):
                completed = manager._run_from_paths(paths)

            self.assertTrue(completed)
            rounds = load_rounds(paths)
            self.assertEqual(len(rounds), 1)
            self.assertEqual(rounds[0].decision, "refine_design")
            self.assertFalse(rounds[0].acted_on)
            self.assertIn("budget spent", rounds[0].budget_note)
            # The run still finished rather than stalling.
            self.assertEqual(operator.invocations["03_study_design"], 1)
            self.assertIn("07_writing", operator.invocations)

    def test_a_single_round_run_still_records_that_it_converged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _operator, manager = self._manager(tmp_dir, max_rounds=1)
            paths = manager._create_run("Single round test.", venue="neurips_2025")

            with patch.object(manager, "_ask_choice", return_value="5"):
                manager._run_from_paths(paths)

            final = latest_round(paths)
            assert final is not None
            self.assertEqual(final.decision, "converged")
            self.assertTrue(final.acted_on)


if __name__ == "__main__":
    unittest.main()
