"""Did the adversarial pass run, and does anything act on the answer.

`_write_review(..., failed=True)` recorded `reviewer_failed: true` and no production
code read it, so a reviewer that never returned and a reviewer that attacked the stage
and found nothing were the same input to every reader downstream: an empty finding list,
nothing owed, gate open. These tests pin the three things that had to change together —
the pass reports how it ended, the manager re-asks once when it did not complete, and a
run that never got a judgement says so instead of printing "All stages approved".

The completion is deliberately *not* read back out of `workspace/reviews/`. That
directory is writable by the stage the next gate constrains, so the last test here
tampers with the artifact and checks the harness ignores it.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.manager import ResearchManager
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text
from src.validity_review import (
    COMPLETED,
    CRASHED,
    DEGRADED_COMPLETIONS,
    UNREADABLE,
    ValidityReviewer,
    is_degraded_completion,
    validate_validity_response,
    validity_review_path,
)


STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)

CLEAN_REVIEW = '{"findings": []}'
ONE_FINDING = json.dumps(
    {
        "findings": [
            {
                "id": "V1",
                "category": "confound",
                "severity": "critical",
                "finding": "Both arms were tuned on the split that reports the headline number.",
                "why_it_matters": "The gap may be selection.",
                "what_would_settle_it": "Re-tune on a development split.",
            }
        ]
    }
)


class ScriptedOperator:
    """An operator that returns a scripted (exit code, stdout) per call.

    Enough of the private surface `ValidityReviewer` reaches into, and no more: the
    reviewer calls `_prepare_invocation` and `_run_streaming_command` directly, the way
    the approval gate does.
    """

    model = "stub-model"
    backend_name = "claude"
    fake_mode = False

    def __init__(self, *turns: tuple[int, str]) -> None:
        self._turns = list(turns)
        #: (attempt_no, mode) per call, so a test can count re-asks rather than infer them.
        self.calls: list[tuple[int, str]] = []

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
        return (["stub", str(prompt_path)], str(paths.run_root), "")

    def _run_streaming_command(
        self, *, command, cwd, stage, attempt_no, paths, mode, stdin_text
    ):
        self.calls.append((attempt_no, mode))
        exit_code, stdout = self._turns[min(len(self.calls) - 1, len(self._turns) - 1)]
        return exit_code, stdout, "", [], {}


class ExplodingOperator(ScriptedOperator):
    def _run_streaming_command(self, **kwargs):
        self.calls.append((kwargs["attempt_no"], kwargs["mode"]))
        raise RuntimeError("vertex 429")


class CompletionTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.paths = build_run_paths(self.root / "runs" / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")

    def review(self, *turns: tuple[int, str]):
        operator = ScriptedOperator(*turns)
        outcome = ValidityReviewer(operator).review(
            paths=self.paths, stage=STAGE_05, stage_markdown="# Stage 05"
        )
        return operator, outcome

    def written(self) -> dict:
        return json.loads(validity_review_path(self.paths, STAGE_05.slug).read_text(encoding="utf-8"))

    def manager(self, operator) -> ResearchManager:
        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.root / "runs",
            operator=operator,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )


class CompletionVocabularyTest(CompletionTestCase):
    """Three values, borrowed from the approval gate, not a new five-value enum."""

    def test_there_are_exactly_two_ways_to_not_complete(self) -> None:
        self.assertEqual(DEGRADED_COMPLETIONS, (CRASHED, UNREADABLE))

    def test_completed_is_not_degraded(self) -> None:
        self.assertFalse(is_degraded_completion(COMPLETED))
        self.assertTrue(all(is_degraded_completion(value) for value in DEGRADED_COMPLETIONS))

    def test_the_whole_vocabulary_is_three_values(self) -> None:
        self.assertEqual(len({COMPLETED, *DEGRADED_COMPLETIONS}), 3)


class CompletionIsReportedTest(CompletionTestCase):
    def test_a_nonzero_exit_is_crashed(self) -> None:
        _operator, outcome = self.review((1, ""))
        self.assertEqual(outcome.completion, CRASHED)
        self.assertTrue(outcome.degraded)

    def test_an_answer_with_no_findings_object_is_unreadable(self) -> None:
        """The reviewer talked, at length, and never produced the object it was asked for."""
        _operator, outcome = self.review((0, "I read the protocol and it all looks reasonable."))
        self.assertEqual(outcome.completion, UNREADABLE)
        self.assertTrue(outcome.degraded)

    def test_a_transcript_carrying_some_other_json_is_still_unreadable(self) -> None:
        """`extract_json_payload` is keyed on `findings`, so a quoted data file is not a review."""
        _operator, outcome = self.review((0, 'I read `{"accuracy": 0.91, "seeds": 3}` and stopped.'))
        self.assertEqual(outcome.completion, UNREADABLE)

    def test_zero_findings_is_a_clean_review_not_a_broken_one(self) -> None:
        """The prompt says raising nothing is legitimate, so emptiness cannot be the test."""
        _operator, outcome = self.review((0, CLEAN_REVIEW))
        self.assertEqual(outcome.completion, COMPLETED)
        self.assertFalse(outcome.degraded)
        self.assertEqual(outcome.findings, [])

    def test_a_real_finding_is_a_clean_review(self) -> None:
        _operator, outcome = self.review((0, ONE_FINDING))
        self.assertEqual(outcome.completion, COMPLETED)
        self.assertEqual([item.identifier for item in outcome.findings], ["V1"])

    def test_reviewer_failed_is_still_written_and_still_derived(self) -> None:
        """docs/run-artifacts.md documents this field; it keeps meaning what it said."""
        self.review((1, ""))
        self.assertTrue(self.written()["reviewer_failed"])
        self.review((0, CLEAN_REVIEW))
        self.assertFalse(self.written()["reviewer_failed"])

    def test_an_unreadable_pass_says_so_in_the_note_rather_than_claiming_nothing_wrong(self) -> None:
        self.review((0, "narration, no object"))
        note = self.written()["note"]
        self.assertIn("no findings object", note)
        self.assertEqual(self.written()["findings"], [])


class ManagerReAsksOnceTest(CompletionTestCase):
    def test_a_crashed_pass_is_re_asked(self) -> None:
        operator = ScriptedOperator((1, ""), (0, ONE_FINDING))
        manager = self.manager(operator)

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual([attempt for attempt, _mode in operator.calls], [1, 2])
        self.assertEqual(manager.validity_reviews_not_completed, {})
        self.assertEqual(manager.validity_disclosure(), "")

    def test_a_clean_pass_is_not_re_asked(self) -> None:
        operator = ScriptedOperator((0, CLEAN_REVIEW))
        manager = self.manager(operator)

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(len(operator.calls), 1)
        self.assertEqual(manager.validity_reviews_not_completed, {})

    def test_the_re_ask_happens_exactly_once(self) -> None:
        """A second failure is evidence about the backend, not about this prompt."""
        operator = ScriptedOperator((1, ""))
        manager = self.manager(operator)

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(len(operator.calls), 2)

    def test_an_unreadable_pass_is_re_asked_too(self) -> None:
        operator = ScriptedOperator((0, "no object here"), (0, ONE_FINDING))
        manager = self.manager(operator)

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(len(operator.calls), 2)
        self.assertEqual(manager.validity_reviews_not_completed, {})

    def test_a_raised_exception_is_a_completion_rather_than_a_silent_return(self) -> None:
        """The `except` used to return, leaving the caller no outcome and the run no record."""
        operator = ExplodingOperator((0, ONE_FINDING))
        manager = self.manager(operator)

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(manager.validity_reviews_not_completed, {STAGE_05.slug: CRASHED})
        self.assertIn("validity_review_failed", read_text(self.paths.logs))


class TheDisclosureReachesTheEndOfTheRunTest(CompletionTestCase):
    """The record has to reach a reader, which is the defect this module exists to fix.

    Everything above asserts the *state*: `validity_reviews_not_completed` is populated
    and `validity_disclosure()` renders. None of it asserts the state is delivered.
    Measured before this class existed: replacing the call at the end of
    `_complete_run` with `disclosure = None` left the entire suite — 2,146 tests —
    green. A record with no reader is the exact shape of the `reviewer_failed` flag
    this branch is removing, reintroduced one layer up.
    """

    def test_the_run_banner_names_a_stage_that_was_never_attacked(self) -> None:
        manager = self.manager(ScriptedOperator((1, "")))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001
        self.assertEqual(manager.validity_reviews_not_completed, {STAGE_05.slug: CRASHED})

        manager._complete_run(self.paths)  # noqa: SLF001

        log = read_text(self.paths.logs)
        self.assertIn("validity_review_not_completed", log)
        self.assertIn(STAGE_05.slug, log.split("validity_review_not_completed", 1)[1][:400])

    def test_a_healthy_run_closes_without_the_banner(self) -> None:
        """Empty when every pass completed, or the line stops meaning anything."""
        manager = self.manager(ScriptedOperator((0, CLEAN_REVIEW)))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        manager._complete_run(self.paths)  # noqa: SLF001

        self.assertNotIn("validity_review_not_completed", read_text(self.paths.logs))


class ManagerRecordsCompletionTest(CompletionTestCase):
    def test_two_failures_are_recorded_against_the_stage(self) -> None:
        manager = self.manager(ScriptedOperator((1, "")))

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(manager.validity_reviews_not_completed, {STAGE_05.slug: CRASHED})
        self.assertIn("validity_review_not_completed", read_text(self.paths.logs))

    def test_the_two_failure_modes_are_told_apart_in_the_record(self) -> None:
        manager = self.manager(ScriptedOperator((0, "narration only")))

        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(manager.validity_reviews_not_completed, {STAGE_05.slug: UNREADABLE})

    def test_a_later_clean_pass_clears_the_record(self) -> None:
        """Thirteen backward edges: a revisited stage can be attacked on the second visit."""
        manager = self.manager(ScriptedOperator((1, "")))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001
        self.assertTrue(manager.validity_reviews_not_completed)

        manager.operator = ScriptedOperator((0, ONE_FINDING))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        self.assertEqual(manager.validity_reviews_not_completed, {})
        self.assertEqual(manager.validity_disclosure(), "")

    def test_the_record_is_the_harness_not_the_artifact(self) -> None:
        """`workspace/reviews/` is writable by the stage the next gate constrains."""
        manager = self.manager(ScriptedOperator((1, "")))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        tampered = self.written()
        tampered["reviewer_failed"] = False
        tampered["note"] = ""
        write_text(validity_review_path(self.paths, STAGE_05.slug), json.dumps(tampered))

        self.assertEqual(manager.validity_reviews_not_completed, {STAGE_05.slug: CRASHED})
        self.assertIn(STAGE_05.slug, manager.validity_disclosure())


class DisclosureBannerTest(CompletionTestCase):
    def test_a_healthy_run_adds_nothing(self) -> None:
        manager = self.manager(ScriptedOperator((0, CLEAN_REVIEW)))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001
        self.assertEqual(manager.validity_disclosure(), "")

    def test_the_banner_names_the_stage_and_how_the_pass_ended(self) -> None:
        manager = self.manager(ScriptedOperator((0, "narration only")))
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        banner = manager.validity_disclosure()
        self.assertIn(STAGE_05.slug, banner)
        self.assertIn(UNREADABLE, banner)
        self.assertIn("not because none were found", banner)

    def test_a_completed_run_prints_the_banner_beside_all_stages_approved(self) -> None:
        """Both sentences are true separately; alone the first one reads as a clean bill.

        The tail, not the whole stream. `_run_validity_review` already prints its own
        warning containing "did not complete", so asserting over everything printed
        passes whether or not `_complete_run` says anything — measured: deleting the
        disclosure from the closing line left all 2,148 tests green. What has to be
        held is that the sentence appears *beside the closing line*, because that
        line is the one a reader takes as the verdict on the run.
        """
        stream = io.StringIO()
        manager = self.manager(ScriptedOperator((1, "")))
        manager.ui = TerminalUI(output_stream=stream, interactive=False)
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001
        already_printed = len(stream.getvalue())

        manager._complete_run(self.paths)  # noqa: SLF001

        closing = stream.getvalue()[already_printed:]
        self.assertIn("All stages approved", closing)
        self.assertIn("did not complete", closing)
        self.assertIn("not because none were found", closing)
        self.assertIn("validity_review_not_completed", read_text(self.paths.logs))

    def test_a_completed_run_with_every_pass_intact_prints_only_the_usual_line(self) -> None:
        stream = io.StringIO()
        manager = self.manager(ScriptedOperator((0, CLEAN_REVIEW)))
        manager.ui = TerminalUI(output_stream=stream, interactive=False)
        manager._run_validity_review(self.paths, STAGE_05, "# Stage 05")  # noqa: SLF001

        manager._complete_run(self.paths)  # noqa: SLF001

        self.assertIn("All stages approved", stream.getvalue())
        self.assertNotIn("did not complete", stream.getvalue())


class TheGateIsNotWhereThisLivesTest(CompletionTestCase):
    def test_stage_06_is_not_blocked_by_a_crashed_stage_05_review(self) -> None:
        """Deliberate. The validator feeds Stage 06's retry loop, and a Stage 06 agent
        cannot re-run Stage 05's reviewer — refusing there would spend the attempt
        budget on a repair the stage has no way to make, then auto-skip. The manager
        holds the operator, so the re-ask is the manager's and the gate stays open.
        """
        self.manager(ScriptedOperator((1, "")))._run_validity_review(  # noqa: SLF001
            self.paths, STAGE_05, "# Stage 05"
        )
        self.assertTrue(self.written()["reviewer_failed"])
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])


if __name__ == "__main__":
    unittest.main()
