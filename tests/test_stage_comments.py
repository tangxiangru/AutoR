"""Anchored review comments, and revisions checked against them.

The feature's whole claim is that a refusal can be *local*. That claim is only worth anything
if something measures whether the revision stayed local, so most of these tests are about the
diff rather than about the prompt.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.stage_comments import (
    COMMENT_LEDGER_FILENAME,
    MIN_QUOTE_CHARS,
    RevisionOutcome,
    StageComment,
    assess_revision,
    build_comment_feedback,
    carry_forward,
    locate,
    normalize,
    parse_comments,
    record_round,
    section_for,
)
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    read_text,
    write_text,
)


STAGE_03 = next(stage for stage in STAGES if stage.slug == "03_study_design")

DRAFT = """# Stage 03: Study Design

## Key Results
We will compare the treated and control groups using a difference-in-differences design.
The sample contains 2,000 households drawn from the national panel.
Statistical power is adequate for the expected effect size.

## Decision Ledger
- **Locked Decisions**: use household fixed effects
"""

_POWER = "Statistical power is adequate for the expected effect size."
_SAMPLE = "The sample contains 2,000 households drawn from the national panel."


def _payload(*comments: dict) -> dict:
    return {"decision": "custom_feedback", "comments": list(comments)}


class AnchorTests(unittest.TestCase):
    def test_a_verbatim_quote_is_located(self) -> None:
        self.assertIsNotNone(locate(DRAFT, _POWER))

    def test_a_rewrapped_quote_still_locates(self) -> None:
        rewrapped = "Statistical power is adequate\n   for the expected effect size."
        self.assertIsNotNone(locate(DRAFT, rewrapped))

    def test_a_quote_that_is_not_there_does_not_locate(self) -> None:
        self.assertIsNone(locate(DRAFT, "a pre-registered instrumental variables strategy"))

    def test_an_empty_quote_does_not_locate(self) -> None:
        self.assertIsNone(locate(DRAFT, "   "))

    def test_the_enclosing_heading_is_reported(self) -> None:
        self.assertEqual(section_for(DRAFT, locate(DRAFT, _POWER)), "Key Results")
        self.assertEqual(
            section_for(DRAFT, locate(DRAFT, "use household fixed effects")), "Decision Ledger"
        )

    def test_normalize_collapses_whitespace(self) -> None:
        self.assertEqual(normalize("  a\n\n  b\t c "), "a b c")


class ParseTests(unittest.TestCase):
    def test_comments_are_anchored_to_their_section(self) -> None:
        comments = parse_comments(
            _payload({"quote": _POWER, "severity": "blocking", "comment": "No power calculation."}),
            author="method", markdown=DRAFT,
        )
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0].status, "open")
        self.assertEqual(comments[0].section, "Key Results")
        self.assertEqual(comments[0].severity, "blocking")

    def test_a_quote_absent_from_the_draft_is_marked_unanchored(self) -> None:
        # A reviewer objecting to text the document does not contain is objecting to something
        # it imagined; that is surfaced rather than passed on as an instruction.
        comments = parse_comments(
            _payload({"quote": "a pre-registered IV strategy for the endogenous regressor",
                      "comment": "Exclusion restriction undefended."}),
            author="method", markdown=DRAFT,
        )
        self.assertEqual(comments[0].status, "unanchored")

    def test_a_quote_too_short_to_anchor_anything_is_dropped(self) -> None:
        self.assertLess(len("the results"), MIN_QUOTE_CHARS)
        comments = parse_comments(
            _payload({"quote": "the results", "comment": "Too vague."}),
            author="method", markdown=DRAFT,
        )
        self.assertEqual(comments, [])

    def test_a_comment_with_no_body_is_dropped(self) -> None:
        comments = parse_comments(
            _payload({"quote": _POWER, "comment": "   "}), author="method", markdown=DRAFT
        )
        self.assertEqual(comments, [])

    def test_an_unknown_severity_falls_back_to_major(self) -> None:
        comments = parse_comments(
            _payload({"quote": _POWER, "severity": "catastrophic", "comment": "x"}),
            author="method", markdown=DRAFT,
        )
        self.assertEqual(comments[0].severity, "major")

    def test_a_reviewer_that_sends_no_comments_still_works(self) -> None:
        # The unanchored prose path must keep working; this is not a breaking contract change.
        self.assertEqual(parse_comments({"decision": "custom_feedback"}, author="r", markdown=DRAFT), [])
        self.assertEqual(parse_comments(None, author="r", markdown=DRAFT), [])
        self.assertEqual(parse_comments({"comments": "nope"}, author="r", markdown=DRAFT), [])


class FeedbackTests(unittest.TestCase):
    def _comments(self):
        return parse_comments(
            _payload(
                {"quote": _SAMPLE, "severity": "minor", "comment": "Say which wave."},
                {"quote": _POWER, "severity": "blocking", "comment": "No power calculation.",
                 "required_change": "Report the MDE at 80% power."},
            ),
            author="method", markdown=DRAFT,
        )

    def test_the_instruction_quotes_the_passages_and_forbids_the_rest(self) -> None:
        rendered = build_comment_feedback(self._comments())
        self.assertIn(_POWER, rendered)
        self.assertIn("byte-identical", rendered)
        self.assertIn("Report the MDE at 80% power.", rendered)

    def test_blocking_comments_come_first(self) -> None:
        rendered = build_comment_feedback(self._comments())
        self.assertLess(rendered.index("blocking"), rendered.index("minor"))

    def test_disagreeing_is_allowed_but_ignoring_is_not(self) -> None:
        self.assertIn("Arguing is allowed", build_comment_feedback(self._comments()))

    def test_unanchored_comments_never_reach_the_operator(self) -> None:
        comments = parse_comments(
            _payload({"quote": "text that is nowhere in the draft at all", "comment": "x"}),
            author="method", markdown=DRAFT,
        )
        self.assertEqual(build_comment_feedback(comments), "")


class RevisionAssessmentTests(unittest.TestCase):
    """The measurement that turns 'change only this' from a wish into a check."""

    def _comments(self):
        return parse_comments(
            _payload(
                {"quote": _POWER, "severity": "blocking", "comment": "No power calculation."},
                {"quote": _SAMPLE, "severity": "minor", "comment": "Say which wave."},
            ),
            author="method", markdown=DRAFT,
        )

    def test_a_targeted_revision_reports_no_collateral(self) -> None:
        revised = DRAFT.replace(_POWER, "With n=2,000 the MDE at 80% power is 0.14 SD.")
        outcome = assess_revision(DRAFT, revised, self._comments())
        self.assertEqual(outcome.addressed, ["method-1"])
        self.assertEqual(outcome.untouched, ["method-2"])
        self.assertEqual(outcome.collateral_lines_changed, 0)
        self.assertEqual(outcome.collateral_ratio, 0.0)

    def test_a_whole_stage_rewrite_is_reported_as_collateral(self) -> None:
        rewritten = """# Stage 03: Study Design

## Key Results
We adopt a staggered difference-in-differences estimator with never-treated controls.
Our analytic sample is 1,850 households from waves 4-9 of the national panel.
With n=1,850 the MDE at 80% power is 0.15 SD.

## Decision Ledger
- **Locked Decisions**: two-way fixed effects with cluster-robust errors
"""
        outcome = assess_revision(DRAFT, rewritten, self._comments())
        self.assertGreater(outcome.collateral_lines_changed, 0)
        self.assertGreaterEqual(outcome.collateral_ratio, 0.5)
        self.assertIn("no comment asked about", outcome.verdict())

    def test_a_revision_that_changed_nothing_says_so(self) -> None:
        outcome = assess_revision(DRAFT, DRAFT, self._comments())
        self.assertEqual(outcome.addressed, [])
        self.assertEqual(sorted(outcome.untouched), ["method-1", "method-2"])
        self.assertIn("left the quoted passage unchanged", outcome.verdict())

    def test_an_unanchored_comment_is_never_counted_as_addressed(self) -> None:
        comments = parse_comments(
            _payload({"quote": "language that appears nowhere in this draft", "comment": "x"}),
            author="method", markdown=DRAFT,
        )
        outcome = assess_revision(DRAFT, "totally different text", comments)
        self.assertEqual(outcome.addressed, [])
        self.assertEqual(outcome.unanchored, ["method-1"])

    def test_untouched_comments_are_carried_into_the_next_round(self) -> None:
        revised = DRAFT.replace(_POWER, "With n=2,000 the MDE at 80% power is 0.14 SD.")
        comments = self._comments()
        outcome = assess_revision(DRAFT, revised, comments)
        carried = carry_forward(comments, outcome)
        # An unaddressed comment that quietly expires is how a review becomes advisory.
        self.assertEqual([c.comment_id for c in carried], ["method-2"])

    def test_an_addressed_comment_is_not_carried_forward(self) -> None:
        revised = DRAFT.replace(_POWER, "MDE reported.").replace(_SAMPLE, "Wave 7 of the panel, n=2,000.")
        comments = self._comments()
        self.assertEqual(carry_forward(comments, assess_revision(DRAFT, revised, comments)), [])

    def test_added_lines_are_counted(self) -> None:
        revised = DRAFT.replace(_POWER, _POWER + "\nA new supporting sentence was appended here.")
        outcome = assess_revision(DRAFT, revised, self._comments())
        self.assertGreaterEqual(outcome.lines_added, 1)


class LedgerTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        return paths

    def _comments(self):
        return parse_comments(
            _payload({"quote": _POWER, "severity": "blocking", "comment": "No power calculation."}),
            author="method", markdown=DRAFT,
        )

    def test_a_round_is_written_where_stage_08_reads_reviews(self) -> None:
        paths = self._paths()
        record_round(paths, STAGE_03, 1, self._comments())
        payload = json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))
        self.assertEqual(payload["rounds"][0]["stage"], STAGE_03.slug)
        self.assertEqual(payload["summary"]["comments_raised"], 1)

    def test_the_outcome_is_appended_to_the_same_round(self) -> None:
        paths = self._paths()
        comments = self._comments()
        record_round(paths, STAGE_03, 1, comments)
        revised = DRAFT.replace(_POWER, "MDE at 80% power is 0.14 SD.")
        record_round(paths, STAGE_03, 1, comments, assess_revision(DRAFT, revised, comments))

        payload = json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))
        # One round, updated in place, not two.
        self.assertEqual(len(payload["rounds"]), 1)
        self.assertEqual(payload["summary"]["comments_addressed"], 1)

    def test_a_rewrite_heavy_run_is_called_out_in_the_summary(self) -> None:
        paths = self._paths()
        comments = self._comments()
        rewritten = "# Stage 03\n\nEverything here is different now.\nAnd so is this line.\nAnd this one.\n"
        record_round(paths, STAGE_03, 1, comments, assess_revision(DRAFT, rewritten, comments))
        summary = json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))["summary"]
        self.assertIn("being rewritten, not patched", summary["verdict"])

    def test_a_corrupt_ledger_is_replaced_rather_than_crashing(self) -> None:
        paths = self._paths()
        paths.reviews_dir.mkdir(parents=True, exist_ok=True)
        write_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME, "{ not json")
        record_round(paths, STAGE_03, 1, self._comments())
        payload = json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))
        self.assertEqual(len(payload["rounds"]), 1)

    def test_an_empty_ledger_summary_does_not_divide_by_zero(self) -> None:
        outcome = RevisionOutcome()
        self.assertEqual(outcome.collateral_ratio, 0.0)
        self.assertIn("no measurable change", outcome.verdict())


class ReviewerContractTests(unittest.TestCase):
    def test_a_reviewer_decision_carries_its_anchored_comments(self) -> None:
        from src.approval_agent import AutomatedReviewer

        reviewer = AutomatedReviewer("claude", model="sonnet", fake_mode=True)
        decision = reviewer.parse_decision(
            json.dumps(_payload({"quote": _POWER, "severity": "blocking", "comment": "No power calc."})),
            markdown=DRAFT,
        )
        self.assertEqual(decision.choice, "4")
        self.assertEqual(len(decision.comments), 1)
        self.assertEqual(decision.comments[0].section, "Key Results")

    def test_an_approval_carries_no_comments(self) -> None:
        from src.approval_agent import AutomatedReviewer

        reviewer = AutomatedReviewer("claude", model="sonnet", fake_mode=True)
        decision = reviewer.parse_decision(
            json.dumps({"decision": "approve",
                        "comments": [{"quote": _POWER, "comment": "minor nit"}]}),
            markdown=DRAFT,
        )
        # An approval sends nothing back, so a comment on it is an instruction nobody acts on.
        self.assertEqual(decision.choice, "5")
        self.assertEqual(decision.comments, [])

    def test_parsing_without_the_draft_stays_backward_compatible(self) -> None:
        from src.approval_agent import AutomatedReviewer

        reviewer = AutomatedReviewer("claude", model="sonnet", fake_mode=True)
        decision = reviewer.parse_decision(json.dumps({"decision": "approve", "reason": "ok"}))
        self.assertEqual(decision.choice, "5")
        self.assertEqual(decision.comments, [])


class ManagerRoundTripTests(unittest.TestCase):
    def _manager_and_paths(self):
        import io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI
        from src.utils import ensure_run_config

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")

        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        return manager, paths

    def test_a_comment_round_produces_an_instruction_and_is_verified(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._pending_comments = parse_comments(
            _payload({"quote": _POWER, "severity": "blocking", "comment": "No power calculation."}),
            author="method", markdown=DRAFT,
        )

        feedback = manager._begin_comment_round(paths, STAGE_03, 1, DRAFT)
        self.assertIn(_POWER, feedback)
        self.assertIn("byte-identical", feedback)

        revised = DRAFT.replace(_POWER, "With n=2,000 the MDE at 80% power is 0.14 SD.")
        manager._close_comment_round(paths, STAGE_03, 2, revised)

        payload = json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))
        self.assertEqual(payload["summary"]["comments_addressed"], 1)
        self.assertEqual(payload["summary"]["lines_changed_as_collateral"], 0)
        # Nothing left owing, so nothing is carried into the next round.
        self.assertEqual(manager._pending_comments, [])

    def test_an_ignored_comment_is_carried_into_the_next_round(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._pending_comments = parse_comments(
            _payload({"quote": _POWER, "severity": "blocking", "comment": "No power calculation."}),
            author="method", markdown=DRAFT,
        )
        manager._begin_comment_round(paths, STAGE_03, 1, DRAFT)
        manager._close_comment_round(paths, STAGE_03, 2, DRAFT)  # unchanged draft

        self.assertEqual([c.comment_id for c in manager._pending_comments], ["method-1"])
        self.assertIn(
            "left the quoted passage unchanged",
            json.loads(read_text(paths.reviews_dir / COMMENT_LEDGER_FILENAME))["rounds"][0]["outcome"]["verdict"],
        )

    def test_closing_without_an_open_round_is_a_no_op(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._close_comment_round(paths, STAGE_03, 1, DRAFT)
        self.assertFalse((paths.reviews_dir / COMMENT_LEDGER_FILENAME).exists())

    def test_measurement_failure_cannot_derail_the_stage(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._open_comments = [StageComment(comment_id="x-1", quote=_POWER, comment="c")]
        manager._commented_draft = DRAFT
        import src.manager as manager_module

        original = manager_module.assess_revision
        manager_module.assess_revision = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("diff blew up"))
        try:
            manager._close_comment_round(paths, STAGE_03, 2, DRAFT)
        finally:
            manager_module.assess_revision = original
        self.assertIn("diff blew up", read_text(paths.logs))


if __name__ == "__main__":
    unittest.main()
