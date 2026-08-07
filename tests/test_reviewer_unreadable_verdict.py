"""What happens when the reviewer answers but AutoR cannot read the answer.

Observed on a real ResearchClawBench run: Stage 01 produced a strong, validated draft
after 40 minutes and two attempts; the reviewer inspected it for 21 turns and then
narrated its findings in prose instead of emitting the verdict JSON. AutoR aborted the
whole run. An unreadable verdict is not a refusal to approve -- it is a failure to read
the answer -- and unattended those deserve different outcomes.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.approval_agent import UNREADABLE_REASON, AutomatedReviewer, ReviewDecision
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

    def test_a_nonzero_first_call_still_aborts_without_a_re_ask(self) -> None:
        """A backend that failed to run is a different thing from one that answered
        unreadably, and must not be re-asked into a false decision."""
        reviewer = self._reviewer(unattended=True)
        calls: list[str] = []

        def run_prompt(*, paths, stage, attempt_no, prompt, label):
            calls.append(label)
            return (2, "", "backend exploded")

        with patch.object(reviewer, "run_prompt", side_effect=run_prompt), \
             patch.object(reviewer, "_build_review_prompt", return_value="p"):
            decision = reviewer.review_stage(
                paths=self.paths, stage=self.stage, attempt_no=1,
                stage_markdown="# Stage 01", suggestions=["a", "b", "c"],
            )
        self.assertEqual(decision.decision_token, "abort")
        self.assertIn("exit code 2", decision.reason)
        self.assertEqual(calls, ["review"])


class RcbAgentIsUnattendedTest(unittest.TestCase):
    def test_the_benchmark_adapter_builds_an_unattended_reviewer(self) -> None:
        """The benchmark has no human, and aborting at Stage 01 forfeits the task."""
        source = Path(__file__).resolve().parent.parent / "rcb_agent.py"
        text = source.read_text()
        block = text[text.index("reviewer = AutomatedReviewer("):]
        self.assertIn("unattended=True", block[: block.index(")\n")])
