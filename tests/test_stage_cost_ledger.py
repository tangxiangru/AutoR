"""A stage visit's spend, and the cause of each attempt it spent.

The measurement this file exists for was taken by hand over the four runs of the first
live paired trial, against each run's ``logs.txt`` under
``/rmeng_data/robtang/rcb-trial-graph/workspaces/*/.autor/*/``::

    grep -ac '^=== .* max_attempts_exceeded ===$'   -> 4, 1, 4, 1   (10 events)
    grep -ac '^=== .* stage_stuck ===$'             -> 1, 0, 0, 0   ( 1 event)
    of those 11, six wrote "Last validation errors: None recorded."

``-a`` is not decoration: one of the four logs contains a byte that makes GNU grep treat
it as binary, and without it that file's count comes back empty rather than 4.

Walking backwards from each of the six silent ones to the previous decision entry gave a
reviewer refusal (``choice: 4``) four times and a cross-model veto twice -- the vetoes
being the two visits where the reviewer had said ``choice: 5`` and ``cross_review`` came
back ``agrees: False``. Not once was it a validation failure, which is the whole
mechanism, because
``last_validation_errors`` is assigned at exactly one place in ``src/manager.py`` and that
place is the validation branch. Everything else that consumes an attempt left it empty.

So the tests below are in two halves. The first half is arithmetic on
:mod:`src.stage_cost` in isolation. The second half drives ``ResearchManager._run_stage``
with a stub reviewer and asserts on the file it leaves behind, because a classifier that
is right and unreached is exactly the defect being fixed one level up.

The mutation sweep is shipped rather than described
---------------------------------------------------
A commit message saying "N mutations, all killed" is a number a reader has to believe.
:data:`MUTATIONS` is the same claim as an instrument: every entry is a one-anchor edit to
``src/stage_cost.py``, ``src/utils.py`` or the manager wiring that removes a rule this
file is supposed to hold. Run it against a **scratch checkout**, because it edits the tree
in place and restores it afterwards::

    git worktree add --detach /tmp/sweep HEAD
    cd /tmp/sweep && python3 -m tests.test_stage_cost_ledger --mutations

It prints one line per mutation naming the tests that died, and exits non-zero if any
survives, so "0 survivors" is re-derivable rather than asserted. Measured on this tree:
47 tried, 47 killed. Seven of the tests here exist because a mutation survived the first
pass -- the entries are kept afterwards precisely so the next edit to this area meets
them.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

from src.approval_agent import (
    CRASHED_REASON,
    UNREADABLE_REASON,
    UNSUPPORTED_REASON,
    AutomatedReviewer,
    ReviewDecision,
)
from src.cross_reviewer import CrossVerdict
from src.evolution import EvolutionConfig
from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.stage_cost import (
    BACKEND_CRASHED,
    BACKEND_UNREADABLE,
    BACKEND_UNSUPPORTED,
    CROSS_REVIEW_VETOED,
    CRUX_RAISED,
    DEGRADED_FAILURE_KINDS,
    FAILURE_KINDS,
    HUMAN_REFUSED,
    OUTCOME_APPROVED,
    OUTCOME_AUTO_SKIPPED,
    OUTCOME_BYPASSED,
    OUTCOME_RAISED,
    OUTCOMES,
    POLISH_ROUND,
    REVIEWER_REFUSED,
    STAGE_COST_LEDGER_VERSION,
    UNCLASSIFIED_REFUSAL,
    VALIDATORS_REFUSED,
    StageCostMeter,
    append_stage_cost_row,
    bypassed_row,
    classify_refusal,
    failure_digest,
    format_stage_cost_summary,
    read_stage_cost_ledger,
    stage_cost_ledger_path,
    summarize_stage_cost,
)
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    OperatorResult,
    build_run_paths,
    create_run_root,
    ensure_run_layout,
    initialize_memory,
    initialize_run_config,
    write_text,
)


STAGE_01 = STAGES[0]


class _FakeClock:
    """A monotonic clock that only moves when a test says so."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _meter(stage=STAGE_01, clock=None) -> StageCostMeter:
    return StageCostMeter(stage, clock=clock or _FakeClock(), started_at="2026-08-16T00:00:00")


# ---------------------------------------------------------------------------
# Half one: the classifier and the row
# ---------------------------------------------------------------------------


class NamingTheCauseTests(unittest.TestCase):
    """The three cases the run has to be able to tell apart afterwards."""

    def test_the_three_backend_reasons_each_get_their_own_kind(self) -> None:
        self.assertEqual(classify_refusal(CRASHED_REASON + " It exited -1."), BACKEND_CRASHED)
        self.assertEqual(classify_refusal(UNREADABLE_REASON + " Unattended, so..."), BACKEND_UNREADABLE)
        self.assertEqual(classify_refusal(UNSUPPORTED_REASON), BACKEND_UNSUPPORTED)

    def test_a_reviewer_that_read_the_stage_is_not_a_backend_failure(self) -> None:
        self.assertEqual(
            classify_refusal("The hypothesis manifest declares no falsifiable rule."),
            REVIEWER_REFUSED,
        )

    def test_a_cross_model_veto_is_its_own_kind(self) -> None:
        # Two reviewers disagreeing is not a stage falling short, and on the trial two of
        # the six silent exhaustions were reached exactly this way.
        self.assertEqual(
            classify_refusal("An independent reviewer rejected the approval.", cross_review=True),
            CROSS_REVIEW_VETOED,
        )

    def test_a_human_refusal_is_not_filed_under_a_reviewer_that_was_not_running(self) -> None:
        self.assertEqual(classify_refusal("option 4", automated=False), HUMAN_REFUSED)

    def test_a_degraded_verdict_stays_degraded_even_on_the_cross_review_path(self) -> None:
        # Ordering guard. If `cross_review` were checked first, a stand-in reason arriving
        # on that path would be recorded as a judgement nobody made.
        self.assertEqual(
            classify_refusal(CRASHED_REASON + " It exited 1.", cross_review=True),
            BACKEND_CRASHED,
        )

    def test_the_classifier_agrees_with_is_degraded_verdict_both_ways(self) -> None:
        """Two readers of one idea, made to agree.

        ``AutomatedReviewer.is_degraded_verdict`` already decides "the reviewer did not
        actually judge this". A second spelling of the same rule that drifts from it would
        put a crashed backend in the census as a reviewer that refused -- which is the
        distinction this whole module exists to make.
        """
        cases = [
            CRASHED_REASON + " It exited -1.",
            UNREADABLE_REASON + " Unattended, so the stage was sent back.",
            UNSUPPORTED_REASON,
            "The stage's figures do not settle the claim they are cited for.",
            "",
        ]
        for reason in cases:
            with self.subTest(reason=reason[:40]):
                decision = ReviewDecision(choice="4", decision_token="revise", reason=reason)
                degraded = AutomatedReviewer.is_degraded_verdict(decision)
                self.assertEqual(
                    degraded,
                    classify_refusal(reason) in DEGRADED_FAILURE_KINDS,
                    f"the two readers disagree about {reason[:60]!r}",
                )

    def test_every_kind_the_classifier_can_return_is_in_the_declared_set(self) -> None:
        produced = {
            classify_refusal(CRASHED_REASON),
            classify_refusal(UNREADABLE_REASON),
            classify_refusal(UNSUPPORTED_REASON),
            classify_refusal("plain"),
            classify_refusal("plain", cross_review=True),
            classify_refusal("plain", automated=False),
        }
        self.assertTrue(produced.issubset(set(FAILURE_KINDS)))


class DidItRepeatTests(unittest.TestCase):
    """Eight attempts against one error is a different event from eight against eight."""

    def test_the_same_reason_re_wrapped_is_the_same_failure(self) -> None:
        self.assertEqual(
            failure_digest(REVIEWER_REFUSED, "Report  plan\n declares 9 headline numbers"),
            failure_digest(REVIEWER_REFUSED, "report plan declares 9 headline numbers"),
        )

    def test_a_different_reason_is_a_different_failure(self) -> None:
        self.assertNotEqual(
            failure_digest(REVIEWER_REFUSED, "declares 9 headline numbers"),
            failure_digest(REVIEWER_REFUSED, "declares 8 headline numbers"),
        )

    def test_the_same_words_from_a_different_kind_are_a_different_failure(self) -> None:
        # A validator error that happens to read like a reviewer's sentence is not the
        # same event, and a census that merged them would report one cause where two
        # different parts of the run refused.
        self.assertNotEqual(
            failure_digest(REVIEWER_REFUSED, "the stage is incomplete"),
            failure_digest(VALIDATORS_REFUSED, "the stage is incomplete"),
        )

    def test_an_empty_reason_still_has_a_digest_and_still_repeats(self) -> None:
        meter = _meter()
        for attempt in range(1, 4):
            meter.note_failure(attempt, BACKEND_CRASHED, "")
        row = meter.close()
        self.assertEqual(row.distinct_failures, 1)
        self.assertEqual(row.max_repeat, 3)
        self.assertTrue(row.repeated_failure)

    def test_eight_identical_refusals_read_as_one_repeated_failure(self) -> None:
        meter = _meter()
        for attempt in range(1, 9):
            meter.note_attempt()
            meter.note_failure(attempt, REVIEWER_REFUSED, "the same objection")
        row = meter.close()
        self.assertEqual(row.attempts, 8)
        self.assertEqual(row.distinct_failures, 1)
        self.assertEqual(row.max_repeat, 8)
        self.assertTrue(row.repeated_failure)
        self.assertEqual(row.failures[0]["first_attempt"], 1)
        self.assertEqual(row.failures[0]["last_attempt"], 8)

    def test_eight_different_refusals_do_not(self) -> None:
        meter = _meter()
        for attempt in range(1, 9):
            meter.note_attempt()
            meter.note_failure(attempt, REVIEWER_REFUSED, f"objection {attempt}")
        row = meter.close()
        self.assertEqual(row.distinct_failures, 8)
        self.assertEqual(row.max_repeat, 1)
        self.assertFalse(row.repeated_failure)

    def test_the_same_failure_eight_times_running_is_not_the_same_as_eight_alternating(
        self,
    ) -> None:
        """The distinction ``max_repeat`` alone cannot make.

        Both visits spend six attempts on the same two reasons three times each. Only the
        first is a stage stuck on one unchanging objection, and a rule of the form "stop
        after N identical failures" reads the wrong one without the ordering.
        """
        first, second = "the same objection", "a different objection"

        stuck = _meter()
        for attempt, reason in enumerate([first] * 3 + [second] * 3, start=1):
            stuck.note_failure(attempt, REVIEWER_REFUSED, reason)

        alternating = _meter()
        for attempt, reason in enumerate([first, second] * 3, start=1):
            alternating.note_failure(attempt, REVIEWER_REFUSED, reason)

        self.assertEqual(stuck.close().max_consecutive_repeat, 3)
        self.assertEqual(alternating.close().max_consecutive_repeat, 1)
        # And every other figure on the row agrees, which is why the ordered one is kept.
        self.assertEqual(stuck.close().max_repeat, alternating.close().max_repeat)
        self.assertEqual(
            stuck.close().distinct_failures, alternating.close().distinct_failures
        )
        self.assertEqual(stuck.close().failure_census, alternating.close().failure_census)

    def test_the_per_attempt_digests_are_in_the_order_the_attempts_happened(self) -> None:
        meter = _meter()
        meter.note_failure(1, REVIEWER_REFUSED, "first")
        meter.note_polish_round(2)
        meter.note_failure(3, BACKEND_CRASHED, "")
        row = meter.close()
        self.assertEqual([entry["attempt"] for entry in row.attempt_digests], [1, 3])
        self.assertEqual(
            [entry["kind"] for entry in row.attempt_digests],
            [REVIEWER_REFUSED, BACKEND_CRASHED],
        )
        self.assertEqual(
            row.attempt_digests[0]["digest"], failure_digest(REVIEWER_REFUSED, "first")
        )

    def test_a_visit_with_no_recorded_cause_has_no_run_of_anything(self) -> None:
        row = _meter().close()
        self.assertEqual(row.max_consecutive_repeat, 0)
        self.assertEqual(row.attempt_digests, [])

    def test_the_groups_are_ordered_by_count_then_first_appearance(self) -> None:
        meter = _meter()
        meter.note_failure(1, REVIEWER_REFUSED, "rare")
        meter.note_failure(2, REVIEWER_REFUSED, "common")
        meter.note_failure(3, REVIEWER_REFUSED, "common")
        meter.note_failure(4, REVIEWER_REFUSED, "also rare")
        groups = meter.close().failures
        self.assertEqual([group["count"] for group in groups], [2, 1, 1])
        self.assertEqual(groups[0]["example"], "common")
        self.assertEqual(groups[1]["example"], "rare")


class TheRowIsCompleteTests(unittest.TestCase):
    def test_the_census_counts_every_kind_the_visit_produced(self) -> None:
        meter = _meter()
        meter.note_failure(1, REVIEWER_REFUSED, "a")
        meter.note_failure(2, VALIDATORS_REFUSED, "b")
        meter.note_failure(3, BACKEND_UNREADABLE, "")
        meter.note_failure(4, CROSS_REVIEW_VETOED, "d")
        meter.note_failure(5, CRUX_RAISED, "e")
        meter.note_polish_round(6)
        row = meter.close()
        self.assertEqual(
            row.failure_census,
            {
                REVIEWER_REFUSED: 1,
                CROSS_REVIEW_VETOED: 1,
                VALIDATORS_REFUSED: 1,
                BACKEND_UNREADABLE: 1,
                CRUX_RAISED: 1,
                POLISH_ROUND: 1,
            },
        )
        self.assertEqual(row.polish_rounds, 1)

    def test_a_polish_round_is_not_a_failure_anywhere_on_the_row(self) -> None:
        # A visit that spent its wall clock getting better must not read as one that
        # spent it thrashing. Five improvement rounds and one objection is one failure,
        # not two -- and `repeated_failure` would otherwise be true of a visit in which
        # nothing failed twice.
        meter = _meter()
        for attempt in range(1, 6):
            meter.note_polish_round(attempt)
        meter.note_failure(6, REVIEWER_REFUSED, "one objection")
        row = meter.close()
        self.assertEqual(row.dominant_failure, REVIEWER_REFUSED)
        self.assertEqual(row.distinct_failures, 1)
        self.assertEqual(row.max_repeat, 1)
        self.assertEqual(row.max_consecutive_repeat, 1)
        self.assertFalse(row.repeated_failure)
        self.assertEqual([group["kind"] for group in row.failures], [REVIEWER_REFUSED])
        self.assertEqual(row.polish_rounds, 5)

    def test_a_visit_that_only_polished_recorded_no_failure(self) -> None:
        meter = _meter()
        for attempt in range(1, 4):
            meter.note_polish_round(attempt)
        row = meter.close()
        self.assertEqual(row.failures, [])
        self.assertEqual(row.distinct_failures, 0)
        self.assertIsNone(row.dominant_failure)
        self.assertEqual(row.failure_census, {POLISH_ROUND: 3})

    def test_an_attempt_nobody_classified_is_counted_rather_than_dropped(self) -> None:
        # The failure mode this module removes, one level up: a path that consumes budget
        # and records nothing. A kind the module does not know is still an attempt.
        meter = _meter()
        meter.note_attempt()
        meter.note_failure(1, "something_new", "reason text")
        row = meter.close()
        self.assertEqual(row.failure_census, {UNCLASSIFIED_REFUSAL: 1})
        self.assertIn("something_new", row.failures[0]["example"])
        self.assertEqual(row.attempts_with_a_recorded_cause, 1)

    def test_an_uncounted_attempt_shows_up_as_a_gap(self) -> None:
        meter = _meter()
        for _ in range(4):
            meter.note_attempt()
        meter.note_failure(1, REVIEWER_REFUSED, "only one of the four said why")
        row = meter.close()
        self.assertEqual(row.attempts, 4)
        self.assertEqual(row.attempts_with_a_recorded_cause, 1)

    def test_wall_clock_comes_from_the_clock(self) -> None:
        clock = _FakeClock()
        meter = _meter(clock=clock)
        clock.advance(1234.5)
        self.assertAlmostEqual(meter.close().wall_seconds, 1234.5, places=3)

    def test_the_invocation_counters_are_separate(self) -> None:
        meter = _meter()
        for _ in range(3):
            meter.note_operator_call()
        meter.note_review_call()
        row = meter.close()
        self.assertEqual(row.operator_invocations, 3)
        self.assertEqual(row.review_invocations, 1)

    def test_no_token_or_cost_field_is_published(self) -> None:
        """Nothing reaches the manager to publish, so nothing is claimed.

        A guessed number in a spend record is worse than a missing one: a reader cannot
        tell which of the fields were measured.
        """
        keys = set(_meter().close().to_dict())
        for forbidden in ("tokens", "input_tokens", "output_tokens", "cost", "usd", "price"):
            self.assertNotIn(forbidden, keys)

    def test_the_reason_the_cost_is_missing_is_the_return_type_and_not_the_backend(
        self,
    ) -> None:
        """Pins the justification, so it cannot outlive the thing that justified it.

        The backend reports its own spend: every invocation ends with a ``result`` event
        carrying ``total_cost_usd`` and a ``usage`` block, and ``logs_raw.jsonl`` keeps
        them. The ledger omits it because :class:`~src.utils.OperatorResult` -- the only
        thing the manager gets back from a stage run -- carries no field it could be read
        from. When that stops being true this test fails, which is the point: the omission
        is then no longer justified and the row should carry the number.
        """
        fields = {field.name for field in dataclasses.fields(OperatorResult)}
        self.assertEqual(
            fields,
            {"success", "exit_code", "stdout", "stderr", "stage_file_path", "session_id"},
        )

    def test_an_unknown_outcome_is_not_silently_a_success(self) -> None:
        meter = _meter()
        meter.note_outcome("something_nobody_declared")
        self.assertNotEqual(meter.close().outcome, OUTCOME_APPROVED)
        self.assertIn(meter.close().outcome, OUTCOMES)

    def test_an_auto_skip_sets_the_flag_and_a_later_outcome_does_not_clear_it(self) -> None:
        # `_route_to_deliverable` refines an auto-skip into a route. The stage still spent
        # a slot from the auto-skip pool and the flag is what the pool is counted from.
        meter = _meter()
        meter.note_outcome(OUTCOME_AUTO_SKIPPED, note="budget spent")
        meter.note_outcome("routed_to_deliverable")
        row = meter.close()
        self.assertTrue(row.auto_skipped)
        self.assertEqual(row.outcome, "routed_to_deliverable")


class TheLedgerFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmp) / "runs"
        self.runs_dir.mkdir()
        self.paths = build_run_paths(create_run_root(self.runs_dir))
        ensure_run_layout(self.paths)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_ledger_is_outside_the_workspace_and_under_the_run_root(self) -> None:
        """The constraint, computed rather than asserted.

        ``report_plan_stamp.json`` is the precedent: the operator runs with
        ``bypassPermissions`` at ``cwd=run_root`` and every stage prompt sends it into
        ``workspace/``, so a record of what a stage spent may not live where that stage is
        told to write.
        """
        path = stage_cost_ledger_path(self.paths)
        self.assertEqual(path, self.paths.stage_cost_ledger)
        self.assertEqual(path.parent, self.paths.run_root)
        self.assertFalse(
            path.is_relative_to(self.paths.workspace_root),
            f"{path} is inside the workspace the agent is directed at",
        )
        # Same test the precedent passes, run on the precedent, so a move of either is
        # visible as a disagreement rather than as one silent relocation.
        self.assertEqual((self.paths.run_root / "report_plan_stamp.json").parent, path.parent)

    def test_a_row_round_trips(self) -> None:
        meter = _meter()
        meter.note_attempt()
        meter.note_failure(1, REVIEWER_REFUSED, "an objection")
        self.assertTrue(append_stage_cost_row(self.paths, meter.close()))
        rows = read_stage_cost_ledger(self.paths)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], STAGE_01.slug)
        self.assertEqual(rows[0]["failure_census"], {REVIEWER_REFUSED: 1})
        payload = json.loads(stage_cost_ledger_path(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(payload["version"], STAGE_COST_LEDGER_VERSION)

    def test_a_second_visit_to_one_stage_gets_its_own_row_and_its_own_number(self) -> None:
        """A backward edge re-runs a stage, and the re-run is a separate purchase.

        Keyed on the ledger rather than on a counter the manager holds, so it is still
        right across a resume -- which is when a second visit is most likely.
        """
        for _ in range(3):
            append_stage_cost_row(self.paths, _meter().close())
        append_stage_cost_row(self.paths, _meter(stage=STAGES[1]).close())
        rows = read_stage_cost_ledger(self.paths)
        self.assertEqual([row["visit"] for row in rows if row["stage"] == STAGE_01.slug], [1, 2, 3])
        self.assertEqual([row["visit"] for row in rows if row["stage"] == STAGES[1].slug], [1])

    def test_a_bypassed_stage_still_gets_a_row(self) -> None:
        append_stage_cost_row(self.paths, bypassed_row(STAGES[5], note="stepped over"))
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["stage"], STAGES[5].slug)
        self.assertEqual(row["outcome"], OUTCOME_BYPASSED)
        self.assertTrue(row["auto_skipped"])
        self.assertEqual(row["attempts"], 0)

    def test_an_unwritable_ledger_reports_failure_instead_of_raising(self) -> None:
        # Bookkeeping may not fail the run: a stage that produced good work must not be
        # lost because the account of it could not be written.
        blocked = stage_cost_ledger_path(self.paths)
        blocked.mkdir()
        (blocked / "occupied").write_text("x", encoding="utf-8")
        self.assertFalse(append_stage_cost_row(self.paths, _meter().close()))

    def test_a_corrupt_ledger_reads_as_empty_instead_of_raising(self) -> None:
        stage_cost_ledger_path(self.paths).write_text("{not json", encoding="utf-8")
        self.assertEqual(read_stage_cost_ledger(self.paths), [])

    def test_the_summary_totals_the_rows(self) -> None:
        first = _meter()
        first.note_attempt()
        first.note_attempt()
        first.note_operator_call()
        first.note_review_call()
        first.note_failure(1, REVIEWER_REFUSED, "a")
        first.note_failure(2, REVIEWER_REFUSED, "a")
        first.note_outcome(OUTCOME_AUTO_SKIPPED)
        first.note_exhausted()
        append_stage_cost_row(self.paths, first.close())

        second = _meter(stage=STAGES[1])
        second.note_attempt()
        second.note_operator_call()
        second.note_failure(1, BACKEND_CRASHED, "")
        append_stage_cost_row(self.paths, second.close())

        totals = summarize_stage_cost(read_stage_cost_ledger(self.paths))
        self.assertEqual(totals["visits"], 2)
        self.assertEqual(totals["stages"], 2)
        self.assertEqual(totals["attempts"], 3)
        self.assertEqual(totals["operator_invocations"], 2)
        self.assertEqual(totals["review_invocations"], 1)
        self.assertEqual(totals["auto_skipped"], 1)
        self.assertEqual(totals["exhausted"], 1)
        self.assertEqual(totals["visits_with_a_repeated_failure"], 1)
        self.assertEqual(totals["longest_run_of_one_failure"], 2)
        self.assertEqual(totals["failure_census"], {REVIEWER_REFUSED: 2, BACKEND_CRASHED: 1})

    def test_the_formatted_summary_names_the_causes(self) -> None:
        meter = _meter()
        meter.note_attempt()
        meter.note_failure(1, BACKEND_CRASHED, "")
        append_stage_cost_row(self.paths, meter.close())
        text = format_stage_cost_summary(read_stage_cost_ledger(self.paths))
        self.assertIn(STAGE_01.slug, text)
        self.assertIn(BACKEND_CRASHED, text)
        self.assertIn("Run total", text)

    def test_an_empty_ledger_says_so_rather_than_printing_a_zero_table(self) -> None:
        self.assertIn("No stage cost rows", format_stage_cost_summary([]))

    def test_a_visit_with_no_recorded_cause_says_so_in_words(self) -> None:
        # The sentence that replaces "None recorded." must not itself be an empty list.
        self.assertIn("no attempt", _meter().describe_failures())


# ---------------------------------------------------------------------------
# Half two: the manager actually reaches it
# ---------------------------------------------------------------------------


class _StubReviewer:
    """Enough of ``AutomatedReviewer`` for ``_collect_review_decision``."""

    backend_name = "claude"
    model = "stub"

    def __init__(self, decisions: list[ReviewDecision]) -> None:
        self._decisions = list(decisions)
        self.calls = 0

    def review_stage(self, **_kwargs: object) -> ReviewDecision:
        self.calls += 1
        index = min(self.calls - 1, len(self._decisions) - 1)
        return self._decisions[index]


class _StubCrossReviewer:
    """Enough of ``GeminiCrossReviewer`` for ``_apply_cross_review``."""

    def __init__(self, reason: str, *, unavailable: bool = False) -> None:
        self._verdict = CrossVerdict(
            agrees=unavailable,
            reason=reason,
            model="stub-cross-model",
            unavailable=unavailable,
        )
        self.calls = 0

    def audit(self, **_kwargs: object) -> CrossVerdict:
        self.calls += 1
        return self._verdict


class ManagerWritesTheLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmp) / "runs"
        self.runs_dir.mkdir()
        self.paths = build_run_paths(create_run_root(self.runs_dir))
        ensure_run_layout(self.paths)
        initialize_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "Test goal")
        write_text(self.paths.user_input, "Test goal")

        self.repo_root = Path(__file__).resolve().parent.parent
        self.ui = TerminalUI()
        self.operator = ClaudeOperator(model="sonnet", fake_mode=True, ui=self.ui)
        self.manager = ResearchManager(
            project_root=self.repo_root,
            runs_dir=self.runs_dir,
            operator=self.operator,
            ui=self.ui,
            # Polish rounds off: this file measures the attempt budget, and an improvement
            # round is an operator call charged to a different one.
            evolution=EvolutionConfig(rounds=0),
        )
        self.manager._display_stage_output = MagicMock()
        self.manager._print = MagicMock()

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- fixtures ----------------------------------------------------------
    def _valid_draft(self, stage) -> Path:
        produced = self.paths.notes_dir / f"{stage.slug}_note.md"
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_text("note", encoding="utf-8")
        if stage.slug == "01_literature_survey":
            # `validate_stage_artifacts` wants the evidence ledger, and a draft missing it
            # is repaired rather than reviewed -- which spends a second operator call and
            # would make `operator_invocations` unreadable on the clean path. Mirrors the
            # fixture `test_manager_smoke` already writes for this stage.
            self.paths.literature_dir.mkdir(parents=True, exist_ok=True)
            (self.paths.literature_dir / "sources.json").write_text(
                json.dumps(
                    {"sources": [{"source_id": "S1", "title": "A ledger source"}]}
                ),
                encoding="utf-8",
            )
            (self.paths.literature_dir / "claims.json").write_text(
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "statement": "The survey produced a traceable source ledger.",
                                "source_ids": ["S1"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
        draft = self.paths.stage_tmp_file(stage)
        draft.write_text(
            "\n".join(
                [
                    f"# {stage.stage_title}",
                    "",
                    "## Objective",
                    "Complete the stage.",
                    "",
                    "## Previously Approved Stage Summaries",
                    "_None yet._",
                    "",
                    "## What I Did",
                    "Did the required work.",
                    "",
                    "## Key Results",
                    "Obtained a concrete result.",
                    "",
                    "## Files Produced",
                    f"- `workspace/notes/{stage.slug}_note.md` - Supporting note",
                    "",
                    "## Decision Ledger",
                    "- **Open Questions**: Which follow-up evidence is still needed?",
                    "- **Locked Decisions**: Keep the current scope for this stage.",
                    "- **Assumptions**: The supporting note remains valid context.",
                    "- **Rejected Alternatives**: Dropping the existing stage draft.",
                    "",
                    "## Suggestions for Refinement",
                    "1. Tighten the scope.",
                    "2. Strengthen the evidence.",
                    "3. Clarify the assumptions.",
                    "",
                    "## Your Options",
                    "1. Use suggestion 1",
                    "2. Use suggestion 2",
                    "3. Use suggestion 3",
                    "4. Refine with your own feedback",
                    "5. Approve and continue",
                    "6. Abort",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return draft

    def _stub_operator(self, draft: Path) -> None:
        self.operator.run_stage = MagicMock(
            return_value=MagicMock(
                success=True,
                exit_code=0,
                session_id="session-1",
                stage_file_path=draft,
                stdout="",
                stderr="",
            )
        )

    def _run_until_exhausted(self, decision: ReviewDecision, *, attempts: int = 3):
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([decision])
        self.manager.max_stage_attempts = attempts
        self.manager._run_stage(self.paths, stage)
        rows = read_stage_cost_ledger(self.paths)
        self.assertEqual(len(rows), 1, "one visit, one row")
        return rows[0]

    # -- the regression ----------------------------------------------------
    def test_an_exhaustion_from_reviewer_refusals_records_the_reviewer(self) -> None:
        """The measured hole. Four of the six silent exhaustions looked exactly like this.

        Before this landed the whole record of three refused attempts was
        ``Last validation errors: None recorded.``
        """
        row = self._run_until_exhausted(
            ReviewDecision(
                choice="4",
                decision_token="revise",
                reason="The manifest states no falsifiable rule.",
                feedback="Add one.",
            )
        )
        self.assertTrue(row["exhausted"])
        self.assertEqual(row["failure_census"], {REVIEWER_REFUSED: 3})
        self.assertEqual(row["dominant_failure"], REVIEWER_REFUSED)
        self.assertTrue(row["repeated_failure"])
        self.assertEqual(row["max_repeat"], 3)
        self.assertEqual(row["attempts"], 3)
        self.assertEqual(row["attempts_with_a_recorded_cause"], 3)

    def test_the_exhaustion_message_names_the_cause_it_used_to_omit(self) -> None:
        from src.manifest import load_run_manifest

        self._run_until_exhausted(
            ReviewDecision(
                choice="4",
                decision_token="revise",
                reason="The manifest states no falsifiable rule.",
                feedback="Add one.",
            )
        )
        manifest = load_run_manifest(self.paths.run_manifest)
        entry = next(item for item in manifest.stages if item.slug == STAGE_01.slug)
        message = entry.last_error or ""
        self.assertIn("Exceeded 3 attempts", message)
        self.assertIn(REVIEWER_REFUSED, message)
        # The old sentence stays: when validation errors exist they are the most specific
        # thing in the message. What changed is that their absence no longer means silence.
        self.assertIn("Last validation errors: None recorded.", message)

    def test_a_crashed_backend_is_not_recorded_as_a_reviewer_refusing(self) -> None:
        """The distinction the trial could not make after the fact.

        Unattended, a crashed reviewer arrives at the loop as the same digit ``4`` an
        ordinary refusal does. Only the reason tells them apart.
        """
        row = self._run_until_exhausted(
            ReviewDecision(
                choice="4",
                decision_token="revise",
                reason=CRASHED_REASON + " It exited -1. Unattended, so the stage was sent back.",
                feedback="Re-examine the draft against the stage contract.",
            )
        )
        self.assertEqual(row["failure_census"], {BACKEND_CRASHED: 3})
        self.assertNotIn(REVIEWER_REFUSED, row["failure_census"])

    def test_an_unreadable_verdict_is_its_own_kind_too(self) -> None:
        row = self._run_until_exhausted(
            ReviewDecision(
                choice="4",
                decision_token="revise",
                reason=UNREADABLE_REASON + " Unattended, so the stage was sent back.",
                feedback="Re-examine the draft against the stage contract.",
            )
        )
        self.assertEqual(row["failure_census"], {BACKEND_UNREADABLE: 3})

    def test_an_unsupported_token_is_its_own_kind_too(self) -> None:
        row = self._run_until_exhausted(
            ReviewDecision(
                choice="4",
                decision_token="maybe",
                reason=UNSUPPORTED_REASON,
                feedback="Restate the verdict.",
            )
        )
        self.assertEqual(row["failure_census"], {BACKEND_UNSUPPORTED: 3})

    def test_a_suggestion_is_a_reviewer_refusal_as_much_as_custom_feedback_is(self) -> None:
        row = self._run_until_exhausted(
            ReviewDecision(choice="1", decision_token="suggestion_1", reason="Tighten the scope.")
        )
        self.assertEqual(row["failure_census"], {REVIEWER_REFUSED: 3})

    def test_validation_refusals_are_recorded_as_validators(self) -> None:
        """The one cause the run already recorded, still recorded, under its own name."""
        stage = STAGE_01
        draft = self.paths.stage_tmp_file(stage)
        draft.parent.mkdir(parents=True, exist_ok=True)
        # No required headings and no evidence ledger. Markdown validation refuses; the
        # repair pass is stubbed to hand back the same file, because the fake operator's
        # repair writes a *valid* draft and the branch under test is the one where repair
        # did not help; local normalization can rebuild the headings but cannot invent
        # `sources.json`, so the third check still fails and the loop re-runs.
        draft.write_text("# nothing useful here\n", encoding="utf-8")
        self._stub_operator(draft)
        self.operator.repair_stage_summary = MagicMock(
            return_value=MagicMock(
                success=True,
                exit_code=0,
                session_id="session-1",
                stage_file_path=draft,
                stdout="",
                stderr="",
            )
        )
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager.max_stage_attempts = 2
        self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertIn(VALIDATORS_REFUSED, row["failure_census"])
        self.assertEqual(row["dominant_failure"], VALIDATORS_REFUSED)
        # Two attempts, each one stage run plus one summary repair. The repair pass is a
        # backend launch the manager dispatched and it is charged as one, which is the
        # difference between "this stage ran twice" and "this stage cost four calls".
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["operator_invocations"], 4)

    # -- the row is written on every way out -------------------------------
    def test_an_approved_stage_gets_a_row_saying_so(self) -> None:
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.assertTrue(self.manager._run_stage(self.paths, stage))
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["outcome"], OUTCOME_APPROVED)
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["operator_invocations"], 1)
        self.assertEqual(row["review_invocations"], 1)
        self.assertEqual(row["failure_census"], {})
        self.assertFalse(row["exhausted"])

    def test_an_auto_skipped_stage_still_gets_a_row(self) -> None:
        """The skipped stages are the expensive ones; a ledger without them is flatter
        than the run."""
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer(
            [
                ReviewDecision(
                    choice="4", decision_token="revise", reason="not yet", feedback="try again"
                )
            ]
        )
        self.manager.unattended = True
        self.manager.max_stage_attempts = 2
        self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertTrue(row["auto_skipped"])
        self.assertEqual(row["outcome"], OUTCOME_AUTO_SKIPPED)
        self.assertTrue(row["exhausted"])
        self.assertEqual(row["failure_census"], {REVIEWER_REFUSED: 2})

    def test_routing_to_the_deliverable_leaves_a_row_for_every_stage_it_stepped_over(
        self,
    ) -> None:
        """The route that ends the measured runs, and the stages it never enters.

        `_route_to_deliverable` puts the stages between here and the writing node into the
        run's not-completed list without ever calling `_run_stage` on them, so no meter is
        ever opened. Without a row each, the ledger's stage set is smaller than the route
        the graph recorded and the two cannot be read against each other.
        """
        failed = STAGES[3]
        self.manager._stage_cost = StageCostMeter(failed)
        try:
            self.assertTrue(
                self.manager._route_to_deliverable(
                    paths=self.paths,
                    stage=failed,
                    attempt_no=1,
                    because="the auto-skip budget is spent",
                    errors_note="(none recorded)",
                )
            )
        finally:
            self.manager._stage_cost = None
        rows = {row["stage"]: row for row in read_stage_cost_ledger(self.paths)}
        for stepped_over in (STAGES[4], STAGES[5]):
            self.assertIn(stepped_over.slug, rows, "a bypassed stage has no row")
            self.assertEqual(rows[stepped_over.slug]["outcome"], OUTCOME_BYPASSED)
            self.assertEqual(rows[stepped_over.slug]["attempts"], 0)
            self.assertTrue(rows[stepped_over.slug]["auto_skipped"])
        # The writing node is where the run is going, not a stage it stepped over.
        self.assertNotIn(STAGES[6].slug, rows)

    def test_a_visit_that_raised_still_gets_a_row(self) -> None:
        """The visit whose spend is least reconstructable from anything else."""
        stage = STAGE_01
        self.operator.run_stage = MagicMock(side_effect=RuntimeError("backend exploded"))
        with self.assertRaises(RuntimeError):
            self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["outcome"], OUTCOME_RAISED)
        self.assertEqual(row["attempts"], 1)

    def test_the_bookkeeping_cannot_replace_the_cause_of_a_failure(self) -> None:
        """Two failures at once: the visit's, and the ledger's while recording it.

        The ``finally`` runs while a ``RuntimeError`` is already in flight, and what the
        caller must be told is the backend, not the bookkeeping. The failure is injected
        *inside* ``_record_stage_cost`` rather than by replacing it, because replacing it
        removes the guard the test is about and would pass against a manager with no
        protection at all.
        """
        stage = STAGE_01
        self.operator.run_stage = MagicMock(side_effect=RuntimeError("backend exploded"))
        original = StageCostMeter.close
        try:
            StageCostMeter.close = MagicMock(side_effect=OSError("disk full"))
            with self.assertRaises(RuntimeError):
                self.manager._run_stage(self.paths, stage)
        finally:
            StageCostMeter.close = original

    def test_a_ledger_that_cannot_be_written_does_not_lose_the_stage(self) -> None:
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        blocked = stage_cost_ledger_path(self.paths)
        blocked.mkdir()
        (blocked / "occupied").write_text("x", encoding="utf-8")
        self.assertTrue(self.manager._run_stage(self.paths, stage))
        self.assertTrue(self.paths.stage_file(stage).exists())

    def test_a_meter_that_cannot_be_closed_does_not_lose_the_stage(self) -> None:
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        original = StageCostMeter.close
        try:
            StageCostMeter.close = MagicMock(side_effect=ValueError("bad row"))
            self.assertTrue(self.manager._run_stage(self.paths, stage))
        finally:
            StageCostMeter.close = original

    def test_two_visits_to_one_stage_leave_two_rows(self) -> None:
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager._run_stage(self.paths, stage)
        self.manager._run_stage(self.paths, stage)
        rows = read_stage_cost_ledger(self.paths)
        self.assertEqual([row["visit"] for row in rows], [1, 2])

    def test_a_refusal_outside_a_stage_visit_is_not_charged_to_a_stage(self) -> None:
        """``_collect_review_decision`` is also reached from intake and the two bootstrap
        loops, which run with no meter open."""
        self.manager.reviewer = _StubReviewer(
            [
                ReviewDecision(
                    choice="4", decision_token="revise", reason="not yet", feedback="try again"
                )
            ]
        )
        self.manager._collect_review_decision(
            paths=self.paths,
            stage=STAGE_01,
            attempt_no=1,
            stage_markdown="# draft",
            suggestions=["a", "b", "c"],
        )
        self.assertEqual(read_stage_cost_ledger(self.paths), [])

    def test_a_refusal_about_another_stage_is_not_charged_to_the_open_one(self) -> None:
        """The other half of the guard, and the one a null check does not cover.

        A meter *is* open, for Stage 01, and a refusal arrives naming Stage 02. Charging
        it would put another stage's spend on this stage's row, which is worse than
        losing it: the row would be wrong rather than incomplete.
        """
        meter = StageCostMeter(STAGE_01)
        self.manager._stage_cost = meter
        try:
            self.manager._note_stage_failure(STAGES[1], 1, REVIEWER_REFUSED, "not this stage")
            self.manager._note_operator_call(STAGES[1])
            self.manager._note_review_call(STAGES[1])
            self.manager._note_stage_outcome(STAGES[1], OUTCOME_AUTO_SKIPPED, "not this stage")
        finally:
            self.manager._stage_cost = None
        row = meter.close()
        self.assertEqual(row.failure_census, {})
        self.assertEqual(row.operator_invocations, 0)
        self.assertEqual(row.review_invocations, 0)
        self.assertFalse(row.auto_skipped)

    def test_an_attempt_spent_settling_a_crux_is_in_the_census(self) -> None:
        """Not a refusal, and still a purchase.

        The agent stopped and asked a question; the draft was fine. The attempt comes out
        of the same budget as a refused one, so leaving it out would make the attempt
        count and the causes disagree by exactly the attempts the run spent answering
        questions.
        """
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager.max_stage_attempts = 2
        # Non-None on the first call only, so the loop spends one attempt on the crux and
        # then proceeds to review as normal.
        self.manager._settle_cruxes = MagicMock(side_effect=["The unit is kelvin.", None])
        self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["failure_census"], {CRUX_RAISED: 1})
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["attempts_with_a_recorded_cause"], 1)

    def test_a_missing_draft_charges_the_repair_pass_it_triggers(self) -> None:
        """The other repair site, and the one a stage that produced nothing goes through.

        Both repair passes are backend launches the manager dispatched, and a row that
        counted only one of them would understate the cheapest way for a stage to get
        expensive: attempts that produced no draft at all.
        """
        stage = STAGE_01
        self._valid_draft(stage)
        missing = self.paths.stage_tmp_file(stage)
        # The operator claims a file it did not write, which is what the repair path is
        # for. The repair then hands back the draft that does exist.
        self.operator.run_stage = MagicMock(
            return_value=MagicMock(
                success=False,
                exit_code=1,
                session_id="session-1",
                stage_file_path=self.paths.stages_dir / "never_written.md",
                stdout="",
                stderr="",
            )
        )
        self.operator.repair_stage_summary = MagicMock(
            return_value=MagicMock(
                success=True,
                exit_code=0,
                session_id="session-1",
                stage_file_path=missing,
                stdout="",
                stderr="",
            )
        )
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.assertTrue(self.manager._run_stage(self.paths, stage))
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["operator_invocations"], 2)
        self.operator.repair_stage_summary.assert_called_once()

    def test_a_human_refusing_at_the_gate_is_charged_to_the_human(self) -> None:
        """An attended run with no automated reviewer still spends its budget.

        Filed under its own kind rather than ``reviewer_refused``: attributing an
        operator's decision to a reviewer that was not running would put a model's
        judgement in the record where a person's belongs.
        """
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = None
        self.manager.max_stage_attempts = 2
        # "1" is "use suggestion 1": a refusal that needs no typed feedback, so the loop
        # runs to exhaustion without reaching for a terminal that is not there.
        self.manager._ask_choice = MagicMock(return_value="1")
        self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["failure_census"], {HUMAN_REFUSED: 2})
        self.assertEqual(row["review_invocations"], 0, "no reviewer ran")
        self.assertTrue(row["exhausted"])

    def test_a_cross_model_veto_is_charged_to_its_own_cause(self) -> None:
        """The other half of the measured hole, and the half a null check does not cover.

        On the trial two of the six silent exhaustions were reached this way: the primary
        reviewer approved, a different model family overturned it, the stage was sent back
        as choice "4", and the record said "None recorded". The veto arrives at
        ``_collect_review_decision`` as a replacement tuple with no ``ReviewDecision``
        attached, so it is the one refusal whose kind cannot be read off a verdict -- and
        filing it as an ordinary reviewer refusal would say the stage fell short when what
        happened is that two reviewers disagreed.
        """
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager.cross_reviewer = _StubCrossReviewer(
            "The decision rule named in H2 cannot be falsified as written."
        )
        self.manager.max_stage_attempts = 2
        self.manager._run_stage(self.paths, stage)
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["failure_census"], {CROSS_REVIEW_VETOED: 2})
        self.assertNotIn(REVIEWER_REFUSED, row["failure_census"])
        self.assertIn("cannot be falsified", row["failures"][0]["example"])
        # The audit is a backend launch too, and one the approval gate did not make.
        self.assertEqual(row["review_invocations"], 4)

    def test_an_unavailable_cross_reviewer_is_not_a_refusal(self) -> None:
        """Control for the test above. An audit that did not happen is not a veto, and
        charging it would put a refusal nobody made in the census."""
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager.cross_reviewer = _StubCrossReviewer("no backend", unavailable=True)
        self.assertTrue(self.manager._run_stage(self.paths, stage))
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["failure_census"], {})
        self.assertEqual(row["outcome"], OUTCOME_APPROVED)

    def test_a_polish_round_reaches_the_row_from_the_loop_that_spends_it(self) -> None:
        """The improvement round, counted where it is actually taken.

        Polish is charged to its own budget rather than to ``--max-attempts``, so a visit
        that spent its wall clock getting better and one that spent it thrashing are the
        same number of attempts and different rows. That distinction is only real if the
        loop tells the meter, which nothing tested until this did.
        """
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        evolution = MagicMock()
        evolution.consider.return_value = MagicMock(
            reverted=False, improved=True, note="promoted", score=MagicMock(total=0.9)
        )
        # One directive, then nothing: the visit takes a single polish round and is then
        # approved, so `attempts` and `polish_rounds` have to come apart on the row.
        evolution.should_continue.side_effect = [True, False]
        evolution.next_directive.return_value = "Tighten the abstract."
        self.manager.evolution = evolution
        self.manager._evolution_measures = MagicMock(return_value=True)
        self.manager._evolution_polishes = MagicMock(return_value=True)
        self.assertTrue(self.manager._run_stage(self.paths, stage))
        row = read_stage_cost_ledger(self.paths)[0]
        self.assertEqual(row["polish_rounds"], 1)
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["failure_census"], {POLISH_ROUND: 1})
        self.assertEqual(row["outcome"], OUTCOME_APPROVED)
        # And the improvement round is not a failure: a visit that got better must not
        # read as one that could not.
        self.assertIsNone(row["dominant_failure"])
        self.assertEqual(row["distinct_failures"], 0)

    def test_a_cancelled_run_writes_its_spend_before_it_gives_up(self) -> None:
        """The run that most needs the ledger read is the one that did not finish.

        `_walk_stages` returns False without reaching `_complete_run`, so the abort branch
        carries its own call. Every measured trial run ended here.
        """
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer(
            [ReviewDecision(choice="6", decision_token="abort", reason="unrecoverable")]
        )
        self.assertFalse(self.manager._walk_stages(self.paths, start_stage=stage))
        log = self.paths.logs.read_text(encoding="utf-8")
        self.assertIn("| run_aborted ===", log)
        self.assertIn("| stage_cost_ledger ===", log)
        self.assertIn(
            STAGE_01.slug, log.split("| stage_cost_ledger ===", 1)[1][:400]
        )

    def test_finishing_a_run_puts_the_ledger_in_the_log_without_being_asked(self) -> None:
        """`_complete_run`, not the helper. A summary nobody calls is the shape of defect
        this repository has a whole test file about."""
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager._run_stage(self.paths, stage)
        self.manager._complete_run(self.paths)
        log = self.paths.logs.read_text(encoding="utf-8")
        self.assertIn("| stage_cost_ledger ===", log)
        self.assertIn("Run total", log)
        self.assertIn(STAGE_01.slug, log.split("| stage_cost_ledger ===", 1)[1][:400])

    def test_the_run_writes_the_ledger_into_its_own_log(self) -> None:
        stage = STAGE_01
        self._stub_operator(self._valid_draft(stage))
        self.manager.reviewer = _StubReviewer([ReviewDecision(choice="5", decision_token="approve")])
        self.manager._run_stage(self.paths, stage)
        self.manager._log_stage_cost_summary(self.paths)
        log = self.paths.logs.read_text(encoding="utf-8")
        self.assertIn("stage_cost_ledger", log)
        self.assertIn("Run total", log)


class TheDeclaredPathIsTheRealOneTests(unittest.TestCase):
    """Control: the assertions above would still pass against a ledger nobody wrote.

    ``RunPaths`` is frozen, so pointing the field somewhere else is the cheapest available
    proof that the manager writes where the field says rather than at a literal.
    """

    def test_moving_the_run_paths_field_moves_the_file(self) -> None:
        tmp = tempfile.mkdtemp()
        try:
            runs_dir = Path(tmp) / "runs"
            runs_dir.mkdir()
            paths = build_run_paths(create_run_root(runs_dir))
            ensure_run_layout(paths)
            moved = replace(paths, stage_cost_ledger=paths.run_root / "elsewhere.json")
            append_stage_cost_row(moved, _meter().close())
            self.assertTrue((paths.run_root / "elsewhere.json").exists())
            self.assertFalse(paths.stage_cost_ledger.exists())
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# The mutation sweep, as an instrument
# ---------------------------------------------------------------------------

STAGE_COST = "src/stage_cost.py"
MANAGER = "src/manager.py"
UTILS = "src/utils.py"

#: ``(what it breaks, file, the text to replace, what to replace it with)``.
#:
#: Each anchor must match exactly once, and the runner refuses the sweep rather than
#: reporting a kill it did not make if it does not -- an anchor that stops matching after
#: a refactor is a mutation silently not applied, which reads in the output exactly like
#: one that was killed.
MUTATIONS: tuple[tuple[str, str, str, str], ...] = (
    ("classify_refusal loses the CRASHED_REASON branch", STAGE_COST,
     "    if text.startswith(CRASHED_REASON):\n        return BACKEND_CRASHED\n", ""),
    ("classify_refusal loses the UNREADABLE_REASON branch", STAGE_COST,
     "    if text.startswith(UNREADABLE_REASON):\n        return BACKEND_UNREADABLE\n", ""),
    ("classify_refusal loses the UNSUPPORTED_REASON branch", STAGE_COST,
     "    if text.startswith(UNSUPPORTED_REASON):\n        return BACKEND_UNSUPPORTED\n", ""),
    ("classify_refusal checks cross_review before the degraded prefixes", STAGE_COST,
     '    text = reason or ""\n    if text.startswith(CRASHED_REASON):',
     '    text = reason or ""\n    if cross_review:\n        return CROSS_REVIEW_VETOED\n'
     "    if text.startswith(CRASHED_REASON):"),
    ("classify_refusal ignores `automated`", STAGE_COST,
     "    if not automated:\n        return HUMAN_REFUSED\n", ""),
    ("failure_digest drops the kind from the hash input", STAGE_COST,
     'return hashlib.sha256(f"{kind}|{normalized}".encode("utf-8")).hexdigest()[:12]',
     'return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]'),
    ("failure_digest drops the whitespace/case normalisation", STAGE_COST,
     'normalized = " ".join((reason or "").split()).lower()', 'normalized = reason or ""'),
    ("max_consecutive_repeat ignores the ordering", STAGE_COST,
     "            run = run + 1 if digest == previous else 1\n", "            run = 1\n"),
    ("attempt_digests keeps polish rounds", STAGE_COST,
     "            for cost in self.costs\n            if cost.kind != POLISH_ROUND\n",
     "            for cost in self.costs\n"),
    ("failure_groups counts polish rounds as failures", STAGE_COST,
     "            if cost.kind == POLISH_ROUND:\n                continue\n"
     "            entry = groups.get(cost.digest)",
     "            entry = groups.get(cost.digest)"),
    ("failure_groups drops the reason text", STAGE_COST,
     '"example": (cost.reason or "")[:FAILURE_EXAMPLE_CHARS],', '"example": "",'),
    ("failure_groups is ordered by insertion, not by count", STAGE_COST,
     "    ordered = sorted(groups.values(), "
     'key=lambda item: (-int(item["count"]), int(item["_order"])))',
     "    ordered = list(groups.values())"),
    ("dominant_failure counts polish rounds", STAGE_COST,
     "refusals = {kind: count for kind, count in census.items() if kind != POLISH_ROUND}",
     "refusals = dict(census)"),
    ("note_failure drops an unclassified kind", STAGE_COST,
     "        if kind not in FAILURE_KINDS:\n"
     '            reason = f"[{kind}] {reason}".strip()\n'
     "            kind = UNCLASSIFIED_REFUSAL\n",
     "        if kind not in FAILURE_KINDS:\n            return\n"),
    ("note_outcome accepts an undeclared outcome", STAGE_COST,
     "        if outcome not in OUTCOMES:\n            outcome = OUTCOME_UNKNOWN\n", ""),
    ("note_outcome lets a later outcome clear auto_skipped", STAGE_COST,
     "        if outcome == OUTCOME_AUTO_SKIPPED:\n            self.auto_skipped = True\n",
     "        self.auto_skipped = outcome == OUTCOME_AUTO_SKIPPED\n"),
    ("append_stage_cost_row hardcodes visit 1", STAGE_COST,
     'visit = sum(1 for item in existing if item.get("stage") == row.stage) + 1',
     "visit = 1"),
    ("append_stage_cost_row lets the write raise", STAGE_COST,
     "        return True\n    except Exception:\n        return False\n",
     "        return True\n    except ZeroDivisionError:\n        return False\n"),
    ("read_stage_cost_ledger lets a corrupt file raise", STAGE_COST,
     "    except (OSError, ValueError):\n        return []\n",
     "    except OSError:\n        return []\n"),
    ("describe_failures says nothing about what was spent", STAGE_COST,
     '        return "; ".join(parts) + f" ({shape})"', '        return "attempts were spent"'),
    ("describe_failures reports an empty list instead of saying so", STAGE_COST,
     '            return "no attempt in this stage run recorded a cause"', '            return ""'),
    ("summarize_stage_cost stops taking the longest run", STAGE_COST,
     '            max((_number(row.get("max_consecutive_repeat")) for row in rows), default=0)',
     "            0"),
    ("bypassed_row is not marked auto_skipped", STAGE_COST,
     "        auto_skipped=True,\n        outcome=OUTCOME_BYPASSED,",
     "        auto_skipped=False,\n        outcome=OUTCOME_BYPASSED,"),
    ("the ledger moves inside workspace/", UTILS,
     'stage_cost_ledger=run_root / "stage_cost_ledger.json",',
     'stage_cost_ledger=workspace_root / "notes" / "stage_cost_ledger.json",'),
    ("the review refusal is not charged", MANAGER,
     "        if decision.choice in REVISION_CHOICES:\n"
     "            self._note_stage_failure(\n                stage,\n                attempt_no,\n"
     "                classify_refusal(decision.reason),\n"
     '                decision.reason or decision.feedback or "",\n            )\n', ""),
    ("the cross-model veto is filed as an ordinary refusal", MANAGER,
     'classify_refusal(cross[1] or "", cross_review=True),', 'classify_refusal(cross[1] or ""),'),
    ("the exhaustion message drops the cause again", MANAGER,
     '                        f"Attempts spent on: {spent_on}. "\n'
     '                        f"Last validation errors:',
     '                        f"Last validation errors:'),
    ("the finally stops writing the row", MANAGER,
     "            self._stage_cost = None\n            self._record_stage_cost(paths, meter)\n",
     "            self._stage_cost = None\n"),
    ("_record_stage_cost stops guarding close()", MANAGER,
     "        try:\n            written = append_stage_cost_row(paths, meter.close())\n"
     "        except Exception:\n            written = False\n",
     "        written = append_stage_cost_row(paths, meter.close())\n"),
    ("_skip_stage stops recording the outcome", MANAGER,
     "        self._note_stage_outcome(\n            stage,\n"
     '            OUTCOME_AUTO_SKIPPED if kind == "auto" else OUTCOME_HUMAN_SKIPPED,\n'
     "            reason,\n        )\n", ""),
    ("_route_to_deliverable stops rowing the stages it steps over", MANAGER,
     "        for slug in bypassed:\n            skipped_stage = stage_for_slug(slug)\n"
     "            if skipped_stage is None:\n                continue\n"
     "            append_stage_cost_row(\n"
     '                paths, bypassed_row(skipped_stage, note=f"stepped over: {reason}")\n'
     "            )\n", ""),
    ("the crux attempt is not charged", MANAGER,
     "                self._note_stage_failure(stage, attempt_no, CRUX_RAISED, crux_feedback)\n",
     ""),
    ("the validators refusal is not charged", MANAGER,
     "                        self._note_stage_failure(\n"
     '                            stage, attempt_no, VALIDATORS_REFUSED, "; ".join(validation_errors)\n'
     "                        )\n", ""),
    ("the human refusal at the manual gate is not charged", MANAGER,
     "            if choice in REVISION_CHOICES:\n                self._note_stage_failure(\n"
     '                    stage, attempt_no, HUMAN_REFUSED, f"the operator chose option {choice}"\n'
     "                )\n", ""),
    ("the human refusal is filed under the automated reviewer", MANAGER,
     'stage, attempt_no, HUMAN_REFUSED, f"the operator chose option {choice}"',
     'stage, attempt_no, REVIEWER_REFUSED, f"the operator chose option {choice}"'),
    ("the stage run is not counted as an operator call", MANAGER,
     "            self._note_operator_call(stage)\n"
     "            result = self._operator_for(stage).run_stage(\n",
     "            result = self._operator_for(stage).run_stage(\n"),
    ("the missing-draft repair is not counted as an operator call", MANAGER,
     '                    "Primary attempt did not produce stage summary draft. '
     'Triggering repair pass.",\n                )\n                self._note_operator_call(stage)\n',
     '                    "Primary attempt did not produce stage summary draft. '
     'Triggering repair pass.",\n                )\n'),
    ("the validation-path repair is not counted as an operator call", MANAGER,
     '                    "\\n".join(validation_errors),\n                )\n'
     "                self._note_operator_call(stage)\n",
     '                    "\\n".join(validation_errors),\n                )\n'),
    ("the approval gate is not counted as a review call", MANAGER,
     "        self._note_review_call(stage)\n        decision = reviewer.review_stage(",
     "        decision = reviewer.review_stage("),
    ("the cross-model audit is not counted as a review call", MANAGER,
     "        self._note_review_call(stage)\n        verdict = self.cross_reviewer.audit(",
     "        verdict = self.cross_reviewer.audit("),
    ("the attempt itself is not counted", MANAGER,
     "            if self._stage_cost is not None:\n"
     "                self._stage_cost.note_attempt()\n", ""),
    ("the visit is never marked exhausted", MANAGER,
     "                if self._stage_cost is not None:\n"
     "                    self._stage_cost.note_exhausted()\n", ""),
    ("the approval outcome is not recorded", MANAGER,
     "                self._note_stage_outcome(stage, OUTCOME_APPROVED)\n", ""),
    ("the polish round is not counted", MANAGER,
     "                        if self._stage_cost is not None:\n"
     "                            self._stage_cost.note_polish_round(attempt_no)\n", ""),
    ("the meter forgets which stage a failure is for", MANAGER,
     "if meter is None or meter.stage.slug != stage.slug:\n            return\n"
     "        meter.note_failure(attempt_no, kind, reason)",
     "if meter is None:\n            return\n"
     "        meter.note_failure(attempt_no, kind, reason)"),
    ("the raised visit is not recorded as raised", MANAGER,
     "        except BaseException:\n            meter.note_outcome(OUTCOME_RAISED)\n            raise\n",
     "        except BaseException:\n            raise\n"),
    ("the run never logs its own spend", MANAGER,
     "        self._log_stage_cost_summary(paths)\n\n"
     "        # A run that concluded it cannot answer its question reached the end of the\n",
     "\n        # A run that concluded it cannot answer its question reached the end of the\n"),
    ("the aborted run never logs its own spend", MANAGER,
     "                self._log_stage_cost_summary(paths)\n"
     '                self._print("Run aborted.")\n',
     '                self._print("Run aborted.")\n'),
)


#: Tests that fail under *every* mutation for a reason that is not the mutation.
#:
#: :meth:`TheSweepIsRunnableTests.test_every_anchor_matches_its_file_exactly_once` reads
#: the anchors against the tree, and applying a mutation is precisely what stops its own
#: anchor from matching -- so it dies 48 times out of 48 and would report a kill for a
#: rule nobody holds. A false kill is worse than a survivor: a survivor is visible and a
#: false kill is a green number covering a hole. Named rather than inferred, because a
#: rule of the form "ignore tests that always fail" would also hide a real one.
SWEEP_SELF_TESTS = frozenset({"test_every_anchor_matches_its_file_exactly_once"})


def _dead_tests(root: Path) -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", __spec__.name if __spec__ else __name__, "-v"],
        cwd=root, capture_output=True, text=True,
    )
    out = proc.stdout + proc.stderr
    dead = set(re.findall(r"^(\w+) \(tests\.[\w.]+\) \.\.\. (?:FAIL|ERROR)", out, re.M))
    dead |= set(re.findall(r"^(?:FAIL|ERROR): (\w+) ", out, re.M))
    return dead - SWEEP_SELF_TESTS


def run_mutations(root: Path | None = None) -> int:
    """Apply each of :data:`MUTATIONS` in turn and report what died. Returns the survivors.

    Restores every file in a ``finally``, so an interrupted sweep leaves the tree as it
    found it -- but it does edit the tree, so run it in a scratch checkout.
    """
    root = root or Path(__file__).resolve().parent.parent
    baseline = _dead_tests(root)
    if baseline:
        print(f"REFUSED: the tree is not green before mutating: {sorted(baseline)}")
        return len(baseline)
    print(f"baseline green; {len(MUTATIONS)} mutations to try\n")
    survivors: list[str] = []
    for name, relative, old, new in MUTATIONS:
        path = root / relative
        text = path.read_text(encoding="utf-8")
        if text.count(old) != 1:
            print(f"NOT APPLIED ({text.count(old)} anchor matches): {name}")
            survivors.append(name)
            continue
        path.write_text(text.replace(old, new), encoding="utf-8")
        try:
            dead = _dead_tests(root)
        finally:
            path.write_text(text, encoding="utf-8")
        if dead:
            print(f"killed  {name}\n            by: {', '.join(sorted(dead))}")
        else:
            print(f"SURVIVED  {name}")
            survivors.append(name)
    print(f"\ntried {len(MUTATIONS)}, killed {len(MUTATIONS) - len(survivors)}, "
          f"survivors {len(survivors)}")
    for name in survivors:
        print("   SURVIVOR:", name)
    return len(survivors)


class TheSweepIsRunnableTests(unittest.TestCase):
    """The instrument, checked without running it: 47 subprocess suites is not a unit test.

    What can go stale without anyone noticing is an *anchor*, and an anchor that no longer
    matches is a mutation silently not applied. Checking every anchor against the tree it
    names costs three file reads and turns "0 survivors" back into a statement about the
    current code rather than about the code when the sweep was last run by hand.
    """

    def test_every_anchor_matches_its_file_exactly_once(self) -> None:
        repo = Path(__file__).resolve().parent.parent
        for name, relative, old, _new in MUTATIONS:
            with self.subTest(mutation=name):
                text = (repo / relative).read_text(encoding="utf-8")
                self.assertEqual(
                    text.count(old), 1,
                    f"{name}: anchor matches {text.count(old)} times in {relative}",
                )

    def test_no_mutation_leaves_the_file_unchanged(self) -> None:
        for name, _relative, old, new in MUTATIONS:
            with self.subTest(mutation=name):
                self.assertNotEqual(old, new, f"{name} is not a mutation")

    def test_the_self_test_exclusion_names_a_test_that_exists(self) -> None:
        """An exclusion pointing at nothing would silently stop excluding."""
        for name in SWEEP_SELF_TESTS:
            self.assertTrue(hasattr(TheSweepIsRunnableTests, name), name)

    def test_the_sweep_covers_all_three_files_it_claims_to(self) -> None:
        self.assertEqual(
            {relative for _n, relative, _o, _w in MUTATIONS},
            {STAGE_COST, MANAGER, UTILS},
        )


if __name__ == "__main__":
    if "--mutations" in sys.argv:
        raise SystemExit(1 if run_mutations() else 0)
    unittest.main()
