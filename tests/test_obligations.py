from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.approval_agent import AutomatedReviewer, ReviewDecision
from src.manager import ResearchManager
from src.obligations import (
    DISCHARGED,
    MAX_OBLIGATIONS,
    MIN_OBLIGATION_CHARS,
    OPEN,
    ObligationLedger,
    discharge_obligations,
    format_for_review_prompt,
    format_for_stage_prompt,
    ledger_path,
    ledger_summary,
    load_ledger,
    normalize_stage_slug,
    note_deferrals,
    record_obligations,
)
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text


STAGE_01, STAGE_03, STAGE_05 = STAGES[0], STAGES[2], STAGES[4]
DEBT = "State a power analysis and justify the sample size before running any experiment."
OTHER = "Report a confidence interval for every metric, computed from the raw measurements."


class LedgerTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")


class RecordTest(LedgerTestBase):
    def test_an_approval_can_leave_a_debt(self) -> None:
        added = record_obligations(
            self.paths, stage=STAGE_01,
            entries=[{"obligation": DEBT, "target_stage": "03_study_design"}],
        )
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0].target_stage, STAGE_03.slug)
        self.assertEqual(added[0].status, OPEN)

    def test_the_ledger_is_an_auditable_artifact(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        payload = json.loads(ledger_path(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(payload["obligations"][0]["origin_stage"], STAGE_01.slug)

    def test_a_bare_string_is_accepted(self) -> None:
        self.assertEqual(len(record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])), 1)

    def test_a_target_stage_may_be_a_number(self) -> None:
        added = record_obligations(self.paths, stage=STAGE_01, entries=[{"obligation": DEBT, "target_stage": "5"}])
        self.assertEqual(added[0].target_stage, STAGE_05.slug)

    def test_an_unrecognised_target_becomes_any_later_stage(self) -> None:
        added = record_obligations(self.paths, stage=STAGE_01, entries=[{"obligation": DEBT, "target_stage": "nonsense"}])
        self.assertIsNone(added[0].target_stage)

    def test_a_thin_obligation_is_refused(self) -> None:
        self.assertEqual(record_obligations(self.paths, stage=STAGE_01, entries=["do better", ""]), [])

    def test_the_length_floor_holds_at_the_boundary(self) -> None:
        self.assertEqual(record_obligations(self.paths, stage=STAGE_01, entries=["x" * (MIN_OBLIGATION_CHARS - 1)]), [])
        self.assertEqual(len(record_obligations(self.paths, stage=STAGE_01, entries=["y" * MIN_OBLIGATION_CHARS])), 1)

    def test_a_restatement_is_not_a_second_debt(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        self.assertEqual(record_obligations(self.paths, stage=STAGE_03, entries=["  " + DEBT.upper() + " "]), [])

    def test_the_ledger_is_bounded(self) -> None:
        record_obligations(
            self.paths, stage=STAGE_01,
            entries=[f"Distinct carried obligation number {i} long enough to be checkable." for i in range(MAX_OBLIGATIONS + 8)],
        )
        self.assertEqual(len(load_ledger(self.paths).obligations), MAX_OBLIGATIONS)

    def test_a_corrupt_ledger_does_not_take_the_run_down(self) -> None:
        ledger_path(self.paths).write_text("nonsense", encoding="utf-8")
        self.assertEqual(load_ledger(self.paths).obligations, [])
        self.assertEqual(len(record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])), 1)


class TargetingTest(LedgerTestBase):
    def test_a_targeted_obligation_reaches_only_its_stage(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[{"obligation": DEBT, "target_stage": "03_study_design"}])
        ledger = load_ledger(self.paths)
        self.assertEqual(len(ledger.open_for(STAGE_03)), 1)
        self.assertEqual(ledger.open_for(STAGE_05), [])

    def test_an_untargeted_obligation_reaches_every_later_stage(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        ledger = load_ledger(self.paths)
        self.assertEqual(len(ledger.open_for(STAGE_03)), 1)
        self.assertEqual(len(ledger.open_for(STAGE_05)), 1)

    def test_an_obligation_never_applies_to_the_stage_that_raised_it(self) -> None:
        record_obligations(self.paths, stage=STAGE_03, entries=[DEBT])
        self.assertEqual(load_ledger(self.paths).open_for(STAGE_03), [])

    def test_it_does_not_apply_to_earlier_stages(self) -> None:
        record_obligations(self.paths, stage=STAGE_03, entries=[DEBT])
        self.assertEqual(load_ledger(self.paths).open_for(STAGE_01), [])

    def test_normalize_accepts_every_spelling_a_reviewer_reaches_for(self) -> None:
        # The display-name forms come from a live model, which returned "Study Design".
        for spelling in ("03_study_design", "3", "03", "Study Design", "study design",
                         "Stage 03: Study Design", "stage03", "Stage 3"):
            self.assertEqual(normalize_stage_slug(spelling), STAGE_03.slug, spelling)

    def test_normalize_still_rejects_a_non_stage(self) -> None:
        for junk in ("nonsense", "", None, "   ", "Stage 99"):
            self.assertIsNone(normalize_stage_slug(junk), junk)


class DischargeTest(LedgerTestBase):
    def setUp(self) -> None:
        super().setUp()
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT, OTHER])

    def test_a_discharged_obligation_stops_being_carried(self) -> None:
        closed = discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["O001"], note="done")
        self.assertEqual(len(closed), 1)
        ledger = load_ledger(self.paths)
        self.assertEqual(ledger.by_id("O001").status, DISCHARGED)
        self.assertEqual(ledger.by_id("O001").discharged_by, STAGE_03.slug)
        self.assertEqual([o.obligation_id for o in ledger.open_for(STAGE_05)], ["O002"])

    def test_discharging_the_same_one_twice_is_a_no_op(self) -> None:
        discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["O001"])
        self.assertEqual(discharge_obligations(self.paths, stage=STAGE_05, obligation_ids=["O001"]), [])

    def test_an_unknown_id_is_ignored(self) -> None:
        self.assertEqual(discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["O999", ""]), [])

    def test_ids_are_matched_case_insensitively(self) -> None:
        self.assertEqual(len(discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["o001"])), 1)


class DeferralTest(LedgerTestBase):
    def test_a_deferral_is_counted_not_silent(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        note_deferrals(self.paths, stage=STAGE_03)
        note_deferrals(self.paths, stage=STAGE_05)
        self.assertEqual(load_ledger(self.paths).by_id("O001").deferrals, 2)

    def test_the_deferral_count_is_shown_to_later_reviewers(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        note_deferrals(self.paths, stage=STAGE_03)
        self.assertIn("already deferred 1x", format_for_review_prompt(load_ledger(self.paths), STAGE_05))

    def test_a_discharged_obligation_is_not_deferred(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["O001"])
        self.assertEqual(note_deferrals(self.paths, stage=STAGE_05), 0)


class RenderingTest(LedgerTestBase):
    def test_an_empty_ledger_renders_nothing(self) -> None:
        self.assertEqual(format_for_stage_prompt(ObligationLedger(), STAGE_03), "")
        self.assertEqual(format_for_review_prompt(ObligationLedger(), STAGE_03), "")

    def test_the_stage_prompt_says_ignoring_one_is_grounds_for_rejection(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        rendered = format_for_stage_prompt(load_ledger(self.paths), STAGE_03)
        self.assertIn(DEBT, rendered)
        self.assertIn("grounds for this stage to be rejected", rendered)

    def test_the_review_prompt_forbids_discharging_on_a_promise(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        rendered = format_for_review_prompt(load_ledger(self.paths), STAGE_03)
        self.assertIn("not on a promise", rendered.replace("Do not discharge one on a promise", "not on a promise"))
        self.assertIn("grounds to refuse", rendered)

    def test_summary_counts_open_versus_total(self) -> None:
        self.assertIn("no carried-forward", ledger_summary(ObligationLedger()))
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT, OTHER])
        discharge_obligations(self.paths, stage=STAGE_03, obligation_ids=["O001"])
        self.assertIn("1 open / 2 total", ledger_summary(load_ledger(self.paths)))


class ReviewSchemaTest(LedgerTestBase):
    def _reviewer(self) -> AutomatedReviewer:
        return AutomatedReviewer("claude", model="opus", fake_mode=True,
                                 ui=TerminalUI(output_stream=io.StringIO(), interactive=False))

    def test_the_prompt_asks_for_carry_forward_on_approval(self) -> None:
        prompt = self._reviewer()._build_review_prompt(
            paths=self.paths, stage=STAGE_01, attempt_no=1,
            stage_markdown="# Stage 01: Literature Survey\n", suggestions=["a", "b", "c"],
        )
        self.assertIn("carry_forward", prompt)
        self.assertIn("approve without letting go", prompt)

    def test_inherited_obligations_reach_the_next_review(self) -> None:
        record_obligations(self.paths, stage=STAGE_01, entries=[DEBT])
        prompt = self._reviewer()._build_review_prompt(
            paths=self.paths, stage=STAGE_03, attempt_no=1,
            stage_markdown="# Stage 03: Study Design\n", suggestions=["a", "b", "c"],
        )
        self.assertIn("Inherited Obligations", prompt)
        self.assertIn(DEBT, prompt)

    def test_carry_forward_and_discharged_are_parsed(self) -> None:
        raw = json.dumps({
            "decision": "approve", "reason": "ok",
            "carry_forward": [{"obligation": DEBT, "target_stage": "03"}],
            "discharged": ["O001"],
        })
        decision = self._reviewer()._parse_decision(raw)
        self.assertEqual(decision.choice, "5")
        self.assertEqual(decision.discharged, ["O001"])
        self.assertEqual(decision.carry_forward[0]["obligation"], DEBT)

    def test_a_decision_without_the_new_fields_still_parses(self) -> None:
        decision = self._reviewer()._parse_decision('{"decision":"approve","reason":"ok"}')
        self.assertEqual(decision.carry_forward, [])
        self.assertEqual(decision.discharged, [])

    def test_malformed_new_fields_are_ignored_not_fatal(self) -> None:
        decision = self._reviewer()._parse_decision(
            '{"decision":"approve","reason":"ok","carry_forward":"nope","discharged":5}'
        )
        self.assertEqual(decision.carry_forward, [])
        self.assertEqual(decision.discharged, [])


class StubOperator:
    model = "opus"
    backend_name = "claude"


class ManagerSettlementTest(LedgerTestBase):
    """The loop only closes if the real decision funnel settles the ledger."""

    def _manager(self) -> ResearchManager:
        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.paths.run_root.parent,
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )

    def _settle(self, stage, choice, *, carry=None, discharged=None):
        self._manager()._settle_obligations(
            paths=self.paths, stage=stage, attempt_no=1,
            decision=ReviewDecision(choice=choice, decision_token="t", reason="r",
                                    carry_forward=carry or [], discharged=discharged or []),
        )
        return load_ledger(self.paths)

    def test_an_approval_records_its_obligations(self) -> None:
        ledger = self._settle(STAGE_01, "5", carry=[{"obligation": DEBT, "target_stage": "03"}])
        self.assertEqual(len(ledger.obligations), 1)
        self.assertIn("obligation_recorded", read_text(self.paths.logs))

    def test_a_later_approval_discharges_and_logs(self) -> None:
        self._settle(STAGE_01, "5", carry=[DEBT])
        ledger = self._settle(STAGE_03, "5", discharged=["O001"])
        self.assertEqual(ledger.by_id("O001").status, DISCHARGED)
        self.assertIn("obligation_discharged", read_text(self.paths.logs))

    def test_an_undischarged_obligation_is_recorded_as_deferred(self) -> None:
        self._settle(STAGE_01, "5", carry=[DEBT])
        ledger = self._settle(STAGE_03, "5")
        self.assertEqual(ledger.by_id("O001").deferrals, 1)
        self.assertIn("obligations_deferred", read_text(self.paths.logs))

    def test_a_refusal_does_not_defer(self) -> None:
        """A refused stage gets another attempt; it has not carried anything past itself."""
        self._settle(STAGE_01, "5", carry=[DEBT])
        ledger = self._settle(STAGE_03, "4")
        self.assertEqual(ledger.by_id("O001").deferrals, 0)

    def test_settling_in_one_decision_does_not_defer_what_it_just_raised(self) -> None:
        self._settle(STAGE_01, "5", carry=[DEBT])
        ledger = self._settle(STAGE_03, "5", discharged=["O001"], carry=[OTHER])
        self.assertEqual(ledger.by_id("O001").status, DISCHARGED)
        self.assertEqual(ledger.by_id("O002").deferrals, 0)


if __name__ == "__main__":
    unittest.main()
