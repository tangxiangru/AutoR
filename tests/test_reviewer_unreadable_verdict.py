"""What happens when the reviewer answers but AutoR cannot read the answer.

Observed on a real ResearchClawBench run: Stage 01 produced a strong, validated draft
after 40 minutes and two attempts; the reviewer inspected it for 21 turns and then
narrated its findings in prose instead of emitting the verdict JSON. AutoR aborted the
whole run. An unreadable verdict is not a refusal to approve -- it is a failure to read
the answer -- and unattended those deserve different outcomes.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.approval_agent import CLOSING_VERDICT_INSTRUCTION, DECISION_TO_CHOICE, UNSUPPORTED_REASON, UNREADABLE_REASON, AutomatedReviewer, ReviewDecision
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text
from src.approval_agent import DECISION_TO_CHOICE, UNSUPPORTED_REASON, UNREADABLE_REASON, AutomatedReviewer, ReviewDecision
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout

GOOD = '{"decision": "approve", "reason": "Artifacts check out."}'
PROSE = "I reviewed the draft and the artifacts. Everything looks broadly reasonable."


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        self.stage = STAGES[0]

    def _reviewer(self, *, unattended: bool) -> AutomatedReviewer:
        with patch("src.approval_agent.ClaudeOperator"):
            return AutomatedReviewer("claude", model="opus", unattended=unattended)

    def _review(self, replies, *, unattended: bool):
        """Drive one review, with `replies` consumed one per backend call."""
        seen: list[str] = []
        reviewer = self._reviewer(unattended=unattended)

        def run_prompt(*, paths, stage, attempt_no, prompt, label):
            seen.append(label)
            return (0, replies[len(seen) - 1], "")

        with patch.object(reviewer, "run_prompt", side_effect=run_prompt), \
             patch.object(reviewer, "_build_review_prompt", return_value="prompt"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
            )
        return decision, seen


class ReadableVerdictTest(_Harness):
    def test_a_parseable_verdict_is_used_and_nothing_is_re_asked(self) -> None:
        decision, calls = self._review([GOOD], unattended=True)
        self.assertEqual(decision.decision_token, "approve")
        self.assertEqual(calls, ["review"])

    def test_a_refusal_is_still_a_refusal(self) -> None:
        """The fix must not turn a reviewer that genuinely says abort into a retry."""
        reply = '{"decision": "abort", "reason": "The results are fabricated."}'
        decision, calls = self._review([reply], unattended=True)
        self.assertEqual(decision.decision_token, "abort")
        self.assertIn("fabricated", decision.reason)
        self.assertEqual(calls, ["review"])


class ReAskTest(_Harness):
    def test_an_unreadable_verdict_is_re_asked_once(self) -> None:
        decision, calls = self._review([PROSE, GOOD], unattended=False)
        self.assertEqual(decision.decision_token, "approve")
        self.assertEqual(calls, ["review", "review_verdict"])

    def test_the_re_ask_demands_the_verdict_alone(self) -> None:
        reviewer = self._reviewer(unattended=True)
        prompt = reviewer._build_verdict_only_prompt(stage=self.stage, previous=PROSE)
        self.assertIn("Do not call any tool", prompt)
        self.assertIn('"decision"', prompt)
        self.assertIn(PROSE, prompt)

    def test_the_re_ask_carries_a_distinct_label_so_it_is_auditable(self) -> None:
        """It writes its own prompt_cache entry rather than overwriting the first."""
        _, calls = self._review([PROSE, GOOD], unattended=True)
        self.assertEqual(calls[1], "review_verdict")


class UnreadableTwiceTest(_Harness):
    def test_attended_still_aborts(self) -> None:
        """A human is there; guessing at a verdict is what the gate exists to prevent."""
        decision, calls = self._review([PROSE, PROSE], unattended=False)
        self.assertEqual(decision.choice, "6")
        self.assertEqual(decision.decision_token, "abort")
        self.assertEqual(calls, ["review", "review_verdict"])

    def test_unattended_revises_instead_of_discarding_the_run(self) -> None:
        decision, _ = self._review([PROSE, PROSE], unattended=True)
        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.decision_token, "revise")

    def test_unattended_never_approves_what_it_could_not_read(self) -> None:
        """Revising is the middle path; approving blindly is still forbidden."""
        decision, _ = self._review([PROSE, PROSE], unattended=True)
        self.assertNotEqual(decision.decision_token, "approve")
        self.assertNotEqual(decision.choice, "5")

    def test_the_revision_carries_actionable_feedback(self) -> None:
        decision, _ = self._review([PROSE, PROSE], unattended=True)
        self.assertTrue(decision.feedback.strip())
        self.assertIn("not approved", decision.feedback)

    def test_both_outcomes_say_the_verdict_was_unreadable(self) -> None:
        for unattended in (True, False):
            with self.subTest(unattended=unattended):
                decision, _ = self._review([PROSE, PROSE], unattended=unattended)
                self.assertIn(UNREADABLE_REASON, decision.reason)

    def test_the_raw_response_is_kept_for_diagnosis(self) -> None:
        decision, _ = self._review([PROSE, PROSE], unattended=True)
        self.assertIn(PROSE, decision.raw_response)


class ReAskFailureTest(_Harness):
    def test_a_failed_re_ask_falls_back_rather_than_raising(self) -> None:
        reviewer = self._reviewer(unattended=True)
        calls: list[str] = []

        def run_prompt(*, paths, stage, attempt_no, prompt, label):
            calls.append(label)
            return (0, PROSE, "") if label == "review" else (1, "", "boom")

        with patch.object(reviewer, "run_prompt", side_effect=run_prompt), \
             patch.object(reviewer, "_build_review_prompt", return_value="p"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.choice, "4")
        self.assertEqual(calls, ["review", "review_verdict"])

    def test_a_crashed_backend_is_never_re_asked(self) -> None:
        """A process that died is not one attempt away from a usable verdict.

        The re-ask exists for a reviewer that answered unreadably. Re-asking a backend that
        failed to run risks turning a transport failure into a fabricated decision, so the
        no-re-ask rule holds whether or not anyone is watching.
        """
        for unattended in (True, False):
            reviewer = self._reviewer(unattended=unattended)
            calls: list[str] = []

            def run_prompt(**kwargs):
                calls.append(kwargs.get("label"))
                return (2, "", "boom")

            with patch.object(reviewer, "run_prompt", side_effect=run_prompt), \
                 patch.object(reviewer, "_build_review_prompt", return_value="p"):
                reviewer.review_stage(
                    paths=self.paths, stage=self.stage, attempt_no=1,
                    stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
                )
            self.assertEqual(calls, ["review"], unattended)

    def test_a_crashed_backend_still_aborts_when_a_human_is_watching(self) -> None:
        reviewer = self._reviewer(unattended=False)
        with patch.object(reviewer, "run_prompt", return_value=(2, "", "boom")), \
             patch.object(reviewer, "_build_review_prompt", return_value="p"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.decision_token, "abort")
        self.assertIn("exit code 2", decision.reason)

    def test_a_crashed_backend_sends_the_stage_back_when_nobody_is(self) -> None:
        """Unattended, aborting here forfeits the task for a reason unrelated to the work.

        Information_001 lost a run holding four approved stages to `exit code -1` -- a
        signal kill, with nothing wrong with the research. Sending the stage back is bounded
        by its own attempt budget; aborting discards everything already earned.
        """
        reviewer = self._reviewer(unattended=True)
        with patch.object(reviewer, "run_prompt", return_value=(-1, "", "killed")), \
             patch.object(reviewer, "_build_review_prompt", return_value="p"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.choice, "4")
        self.assertNotEqual(decision.decision_token, "abort")
        self.assertIn("-1", decision.reason)
        self.assertTrue(decision.feedback.strip())

    def test_a_crashed_backend_never_becomes_an_approval(self) -> None:
        reviewer = self._reviewer(unattended=True)
        with patch.object(reviewer, "run_prompt", return_value=(1, "", "boom")), \
             patch.object(reviewer, "_build_review_prompt", return_value="p"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
            )
        self.assertNotEqual(decision.choice, "5")


class RcbAgentIsUnattendedTest(unittest.TestCase):
    def test_the_benchmark_adapter_builds_an_unattended_reviewer(self) -> None:
        """The benchmark has no human, and aborting at Stage 01 forfeits the task."""
        source = Path(__file__).resolve().parent.parent / "rcb_agent.py"
        text = source.read_text()
        block = text[text.index("reviewer = AutomatedReviewer("):]
        self.assertIn("unattended=True", block[: block.index(")\n")])


class DecisionVocabularyTest(unittest.TestCase):
    """The words a reviewer actually uses when it means "send this back".

    Three of five benchmark runs died because the reviewer answered `"revise"` and the map
    did not contain it, so an ordinary request for changes was read as an unsupported token
    and ended the run at Stage 01 or 02.
    """

    def _reviewer(self) -> AutomatedReviewer:
        return AutomatedReviewer(
            "claude", model="opus", fake_mode=True,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False), unattended=True,
        )

    def test_revise_is_a_request_for_changes_not_an_unsupported_token(self) -> None:
        decision = self._reviewer()._parse_decision(
            json.dumps({"decision": "revise", "reason": "r", "feedback": "fix the power analysis"})
        )
        self.assertEqual(decision.choice, "4")
        self.assertIn("power analysis", decision.feedback)

    def test_the_other_natural_synonyms_are_accepted(self) -> None:
        for token in ("refine", "revision", "request_changes", "changes_requested",
                      "revise_with_feedback", "REVISE", "Request Changes"):
            decision = self._reviewer()._parse_decision(
                json.dumps({"decision": token, "reason": "r", "feedback": "f"})
            )
            self.assertEqual(decision.choice, "4", token)

    def test_autor_own_fallback_token_round_trips(self) -> None:
        """The unreadable-verdict fallback emits `revise`; the map has to accept its own word."""
        self.assertIn("revise", DECISION_TO_CHOICE)

    def test_reject_stays_out_because_it_reads_both_ways(self) -> None:
        """"Reject" means both "send back" and "stop"; guessing either way is worse."""
        self.assertNotIn("reject", DECISION_TO_CHOICE)

    def test_approve_and_abort_are_untouched(self) -> None:
        for token, choice in (("approve", "5"), ("abort", "6")):
            decision = self._reviewer()._parse_decision(json.dumps({"decision": token, "reason": "r"}))
            self.assertEqual(decision.choice, choice, token)

    def test_a_genuinely_unknown_token_is_still_treated_as_unanswered(self) -> None:
        decision = self._reviewer()._parse_decision(json.dumps({"decision": "banana", "reason": "r"}))
        self.assertIn(UNSUPPORTED_REASON, decision.reason)


class ClosingVerdictInstructionTest(unittest.TestCase):
    """The verdict contract has to be the last thing the reviewer reads.

    Over one benchmark run's 65 recorded review calls, the primary call's closing output
    carried no parseable decision almost every time, while the verdict-only re-ask produced
    one on essentially every attempt. The difference is position: the contract was stated
    near the top and the prompt then ended with five thousand characters of log tail.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")
        self.reviewer = AutomatedReviewer(
            "claude", model="opus", fake_mode=True,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )

    def _prompt(self) -> str:
        return self.reviewer._build_review_prompt(
            paths=self.paths, stage=STAGES[0], attempt_no=1,
            stage_markdown="# Stage 01: Literature Survey", suggestions=["a", "b", "c"],
        )

    def test_the_prompt_ends_with_the_verdict_contract(self) -> None:
        self.assertTrue(self._prompt().rstrip().endswith(CLOSING_VERDICT_INSTRUCTION.rstrip()))

    def test_it_comes_after_the_log_excerpt_that_used_to_be_last(self) -> None:
        prompt = self._prompt()
        self.assertLess(prompt.index("Recent Log Excerpt"), prompt.index("Your Final Message"))

    def test_it_offers_only_tokens_the_parser_accepts(self) -> None:
        """The re-ask prompt once offered `revise`, which the parser rejected outright."""
        import re

        listed = re.findall(r'"decision":"([^"]+)"', CLOSING_VERDICT_INSTRUCTION)
        self.assertTrue(listed)
        for token in listed[0].split("|"):
            self.assertIn(token, DECISION_TO_CHOICE, token)

    def test_it_says_narrative_belongs_inside_the_object(self) -> None:
        self.assertIn("reason", CLOSING_VERDICT_INSTRUCTION)
        self.assertIn("nothing else", CLOSING_VERDICT_INSTRUCTION)

    def test_it_warns_that_abort_stops_the_run(self) -> None:
        """Three benchmark runs ended on a verdict the reviewer did not mean as fatal."""
        self.assertIn("stops the whole run", CLOSING_VERDICT_INSTRUCTION)

    def test_the_verdict_only_re_ask_also_offers_accepted_tokens(self) -> None:
        import re

        prompt = self.reviewer._build_verdict_only_prompt(stage=STAGES[0], previous="prose")
        for token in re.findall(r'"(approve|revise|abort|custom_feedback)"', prompt):
            self.assertIn(token, DECISION_TO_CHOICE, token)
