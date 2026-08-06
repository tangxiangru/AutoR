from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.approval_agent import ReviewDecision
from src.cross_reviewer import (
    DEFAULT_CROSS_REVIEW_MODEL,
    MIN_REASON_CHARS,
    CrossVerdict,
    GeminiCrossReviewer,
    resolve_cross_reviewer,
)
from src.manager import ResearchManager
from src.review_policy import load_policy
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text
from src.web_search import SearchBackend


STAGE_01 = STAGES[0]
GOOD_REASON = "The summary reports an AUROC of 0.99 with no method or data split stated anywhere."


class ParseTest(unittest.TestCase):
    def test_a_plain_agreement_parses(self) -> None:
        v = GeminiCrossReviewer.parse('{"verdict":"agree","reason":"consistent"}')
        self.assertTrue(v.agrees)
        self.assertFalse(v.vetoes)
        self.assertFalse(v.unavailable)

    def test_a_substantiated_refusal_vetoes(self) -> None:
        v = GeminiCrossReviewer.parse('{"verdict":"refuse","reason":"%s"}' % GOOD_REASON)
        self.assertTrue(v.vetoes)
        self.assertIn("AUROC", v.reason)

    def test_refusal_synonyms_all_veto(self) -> None:
        for token in ("refuse", "reject", "disagree", "block", "veto", "REFUSE"):
            v = GeminiCrossReviewer.parse('{"verdict":"%s","reason":"%s"}' % (token, GOOD_REASON))
            self.assertTrue(v.vetoes, token)

    def test_a_fenced_response_parses(self) -> None:
        raw = 'Here is my verdict:\n```json\n{"verdict":"refuse","reason":"%s"}\n```\n' % GOOD_REASON
        self.assertTrue(GeminiCrossReviewer.parse(raw).vetoes)

    def test_an_unsubstantiated_refusal_is_ignored(self) -> None:
        """A veto must justify itself, or good work gets bounced on a shrug."""
        v = GeminiCrossReviewer.parse('{"verdict":"refuse","reason":"bad"}')
        self.assertFalse(v.vetoes)
        self.assertIn("no substantive reason", v.reason)

    def test_the_reason_floor_is_exercised_at_the_boundary(self) -> None:
        under = "x" * (MIN_REASON_CHARS - 1)
        over = "y" * MIN_REASON_CHARS
        self.assertFalse(GeminiCrossReviewer.parse('{"verdict":"refuse","reason":"%s"}' % under).vetoes)
        self.assertTrue(GeminiCrossReviewer.parse('{"verdict":"refuse","reason":"%s"}' % over).vetoes)

    def test_garbage_is_unavailable_not_agreement(self) -> None:
        """Silence must not be laundered into a passed audit."""
        v = GeminiCrossReviewer.parse("the model rambled and returned no json")
        self.assertTrue(v.unavailable)
        self.assertFalse(v.vetoes)

    def test_an_empty_response_is_unavailable(self) -> None:
        self.assertTrue(GeminiCrossReviewer.parse("").unavailable)

    def test_an_unknown_verdict_token_is_treated_as_agreement(self) -> None:
        # Only an explicit refusal blocks; anything else must not silently veto.
        self.assertFalse(GeminiCrossReviewer.parse('{"verdict":"maybe","reason":"x"}').vetoes)


class AvailabilityTest(unittest.TestCase):
    def _no_backend(self):
        return patch("src.cross_reviewer.resolve_backend", return_value=None)

    def _backend(self):
        return patch(
            "src.cross_reviewer.resolve_backend",
            return_value=SearchBackend(kind="vertex", model="gemini-x", project="p", location="global"),
        )

    def test_auto_is_off_without_a_backend(self) -> None:
        with self._no_backend():
            self.assertIsNone(resolve_cross_reviewer("auto"))

    def test_auto_is_on_with_a_backend(self) -> None:
        with self._backend():
            self.assertIsNotNone(resolve_cross_reviewer("auto"))

    def test_off_is_always_off(self) -> None:
        with self._backend():
            self.assertIsNone(resolve_cross_reviewer("off"))

    def test_the_default_model_is_not_the_cheap_search_model(self) -> None:
        """A reviewer auditing frontier output should not be the flash-tier search model."""
        from src.web_search import DEFAULT_SEARCH_MODEL, DEFAULT_VERTEX_SEARCH_MODEL

        self.assertNotIn(DEFAULT_CROSS_REVIEW_MODEL, {DEFAULT_SEARCH_MODEL, DEFAULT_VERTEX_SEARCH_MODEL})

    def test_an_unconfigured_audit_reports_unavailable_not_agreement(self) -> None:
        with self._no_backend():
            reviewer = GeminiCrossReviewer()
            with tempfile.TemporaryDirectory() as tmp:
                paths = build_run_paths(Path(tmp) / "run")
                ensure_run_layout(paths)
                verdict = reviewer.audit(
                    paths=paths, stage=STAGE_01, stage_markdown="# Stage 01: Literature Survey\n",
                    primary_reason="fine", primary_model="opus",
                )
        self.assertTrue(verdict.unavailable)
        self.assertFalse(verdict.vetoes)


class StubOperator:
    model = "opus"
    backend_name = "claude"


class VetoWiringTest(unittest.TestCase):
    """The veto must be able to send a stage back, and must never do the opposite."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")

    def _manager(self, verdict: CrossVerdict | None) -> ResearchManager:
        reviewer = None
        if verdict is not None:
            reviewer = GeminiCrossReviewer()
            reviewer.audit = lambda **kwargs: verdict  # type: ignore[assignment]
        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.paths.run_root.parent,
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            cross_reviewer=reviewer,
        )

    def _apply(self, verdict, choice="5"):
        return self._manager(verdict)._apply_cross_review(
            paths=self.paths, stage=STAGE_01, attempt_no=1,
            decision=ReviewDecision(choice=choice, decision_token="t", reason="approved"),
            stage_markdown="# Stage 01: Literature Survey\n",
        )

    def test_a_veto_turns_an_approval_into_a_refinement(self) -> None:
        result = self._apply(CrossVerdict(agrees=False, reason=GOOD_REASON, model="gemini-x"))
        self.assertIsNotNone(result)
        choice, feedback = result
        self.assertEqual(choice, "4")
        self.assertIn(GOOD_REASON, feedback)

    def test_agreement_leaves_the_approval_standing(self) -> None:
        self.assertIsNone(self._apply(CrossVerdict(agrees=True, model="gemini-x")))

    def test_an_unavailable_audit_leaves_the_approval_standing(self) -> None:
        self.assertIsNone(self._apply(CrossVerdict(agrees=True, unavailable=True, reason="no backend")))

    def test_a_refusal_is_never_audited(self) -> None:
        """It is a veto, never an override: it must not be able to rescue a refusal."""
        for refusal in ("1", "2", "3", "4", "6"):
            self.assertIsNone(
                self._apply(CrossVerdict(agrees=False, reason=GOOD_REASON), choice=refusal),
                refusal,
            )

    def test_no_cross_reviewer_means_no_change(self) -> None:
        self.assertIsNone(self._apply(None))

    def test_a_veto_becomes_a_standing_rule(self) -> None:
        """A blind spot caught once must be checked on every stage afterwards."""
        self._apply(CrossVerdict(agrees=False, reason=GOOD_REASON, model="gemini-x"))
        rules = load_policy(self.paths).rules
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].source, "rollback")
        self.assertIn(GOOD_REASON, rules[0].text)

    def test_every_outcome_is_written_to_the_run_log(self) -> None:
        self._apply(CrossVerdict(agrees=True, model="gemini-x"))
        self.assertIn("cross_review", read_text(self.paths.logs))

    def test_an_unavailable_audit_is_logged_as_unavailable(self) -> None:
        self._apply(CrossVerdict(agrees=True, unavailable=True, reason="backend down"))
        log = read_text(self.paths.logs)
        self.assertIn("unavailable: True", log)


class AuditPacketTest(unittest.TestCase):
    """An absent excerpt is a limit of the packet, never evidence of a missing artifact."""

    def test_an_absent_artifact_renders_as_a_disclaimer_not_as_missing(self) -> None:
        from src.cross_reviewer import NOT_INCLUDED, _excerpt

        with tempfile.TemporaryDirectory() as tmp:
            rendered = _excerpt(Path(tmp) / "absent.json", 100)
        self.assertEqual(rendered, NOT_INCLUDED)
        self.assertNotIn("missing", rendered.split("—")[0].lower())

    def test_an_empty_artifact_renders_the_same_way(self) -> None:
        from src.cross_reviewer import NOT_INCLUDED, _excerpt

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.json"
            path.write_text("   ", encoding="utf-8")
            self.assertEqual(_excerpt(path, 100), NOT_INCLUDED)

    def test_present_content_is_included(self) -> None:
        from src.cross_reviewer import _excerpt

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "index.json"
            path.write_text('{"artifacts": 3}', encoding="utf-8")
            self.assertIn("artifacts", _excerpt(path, 100))


class PromptTest(unittest.TestCase):
    def test_the_prompt_frames_the_shared_blind_spot_and_forbids_style_vetoes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "study the data")
            prompt = GeminiCrossReviewer().build_prompt(
                paths=paths, stage=STAGE_01,
                stage_markdown="# Stage 01: Literature Survey\n\nclaims here",
                primary_reason="looks thorough", primary_model="opus",
            )
        self.assertIn("different model family", prompt)
        self.assertIn("looks thorough", prompt)
        self.assertIn("Do not refuse over style", prompt)
        # A section absent from the packet must not read as a missing artifact. Testing
        # showed the auditor veto sound work on exactly this confusion.
        self.assertIn("not included in this audit packet", prompt)
        self.assertIn("never infer from it that the approving reviewer fabricated", prompt)
        # It must not be asked to verify files it cannot reach.
        self.assertIn("You have no", prompt)


if __name__ == "__main__":
    unittest.main()
