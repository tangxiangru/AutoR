"""The state goes back and the evidence does not, asserted both ways.

The pair of tests that carry the design are
:meth:`TheEvidenceOutlivesTheStateTests.test_the_workspace_goes_back_and_the_record_stays`
and
:meth:`TheEvidenceOutlivesTheStateTests.test_a_second_withdrawal_cannot_erase_the_first`.
Either one alone permits the failure the split exists to prevent: a recovery so complete
that the run cannot tell a withdrawn attempt from an attempt never made, and so tries the
same thing again.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.information_flow import CHANNELS
from src.manifest import ensure_run_manifest, mark_stage_approved_manifest, rollback_to_stage
from src.provenance import observe
from src.stage_graph import REVISIT_EDGES
from src.utils import INTAKE_STAGE, STAGES, build_run_paths, ensure_run_layout, write_text
from src.withdrawal_ledger import (
    PROMPT_WITHDRAWAL_LIMIT,
    WithdrawalRecord,
    append_withdrawal,
    format_withdrawal_history_for_prompt,
    ledger_path,
    load_withdrawals,
    summarise,
    withdrawals_for_stage,
)

STAGE_02, STAGE_03, STAGE_04, STAGE_05, STAGE_08 = (
    STAGES[1],
    STAGES[2],
    STAGES[3],
    STAGES[4],
    STAGES[7],
)


class LedgerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)


class RecordTests(LedgerTestCase):
    def test_a_row_survives_a_round_trip(self) -> None:
        append_withdrawal(
            self.paths,
            WithdrawalRecord(
                at="2026-01-01T00:00:00",
                target_stage=STAGE_04.slug,
                reason="the implementation did not match the design",
                deleted=3,
                rewound=1,
                invalidated=(STAGE_04.slug, STAGE_05.slug),
                drifted=("02_hypothesis_generation: research_rounds (from 06_analysis)",),
                emissions_discarded=2,
            ),
        )

        loaded = load_withdrawals(self.paths)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].deleted, 3)
        self.assertEqual(loaded[0].invalidated, (STAGE_04.slug, STAGE_05.slug))

    def test_the_ledger_is_append_only(self) -> None:
        for index in range(3):
            append_withdrawal(
                self.paths,
                WithdrawalRecord(at=f"t{index}", target_stage=STAGE_04.slug, reason=f"r{index}"),
            )

        self.assertEqual([record.reason for record in load_withdrawals(self.paths)], ["r0", "r1", "r2"])
        self.assertEqual(len(ledger_path(self.paths).read_text(encoding="utf-8").splitlines()), 3)

    def test_an_unreadable_row_does_not_take_the_rest_with_it(self) -> None:
        append_withdrawal(self.paths, WithdrawalRecord(at="t0", target_stage=STAGE_04.slug, reason="r0"))
        with ledger_path(self.paths).open("a", encoding="utf-8") as handle:
            handle.write("{ not json\n")
        append_withdrawal(self.paths, WithdrawalRecord(at="t1", target_stage=STAGE_04.slug, reason="r1"))

        self.assertEqual([record.reason for record in load_withdrawals(self.paths)], ["r0", "r1"])

    def test_rows_can_be_read_back_per_stage(self) -> None:
        append_withdrawal(self.paths, WithdrawalRecord(at="t0", target_stage=STAGE_04.slug, reason="a"))
        append_withdrawal(self.paths, WithdrawalRecord(at="t1", target_stage=STAGE_02.slug, reason="b"))

        self.assertEqual([r.reason for r in withdrawals_for_stage(self.paths, STAGE_04)], ["a"])
        self.assertIn("x1", summarise(load_withdrawals(self.paths)))


class TheEvidenceOutlivesTheStateTests(LedgerTestCase):
    def test_the_workspace_goes_back_and_the_record_stays(self) -> None:
        write_text(self.paths.data_dir / "wrong_design.csv", "arm,n\ncontrol,30\n")
        observe(self.paths, STAGE_04)

        rollback_to_stage(self.paths, STAGE_03, "the design answered a different question")

        self.assertFalse(
            (self.paths.data_dir / "wrong_design.csv").exists(),
            "the state is supposed to leave no trace",
        )
        records = load_withdrawals(self.paths)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].target_stage, STAGE_03.slug)
        self.assertIn("answered a different question", records[0].reason)
        self.assertEqual(records[0].deleted, 1)

    def test_a_second_withdrawal_cannot_erase_the_first(self) -> None:
        """The ledger is outside every recovery path, by placement rather than exclusion."""

        rollback_to_stage(self.paths, STAGE_03, "first attempt was wrong")
        rollback_to_stage(self.paths, STAGE_02, "so was the hypothesis")

        reasons = [record.reason for record in load_withdrawals(self.paths)]
        self.assertEqual(len(reasons), 2)
        self.assertIn("first attempt was wrong", reasons[0])

    def test_the_ledger_is_outside_the_workspace(self) -> None:
        """So no withdrawal reaches it by construction, not by an exclusion list."""

        append_withdrawal(self.paths, WithdrawalRecord(at="t", target_stage=STAGE_03.slug, reason="r"))

        self.assertNotIn(
            self.paths.workspace_root, ledger_path(self.paths).parents
        )

    def test_a_withdrawal_records_the_approvals_it_retired(self) -> None:
        write_text(self.paths.data_dir / "late.csv", "id\n1\n")
        observe(self.paths, STAGE_05)
        mark_stage_approved_manifest(self.paths, STAGE_05, 1, [])

        rollback_to_stage(self.paths, STAGE_03, "the design was wrong")

        record = load_withdrawals(self.paths)[0]
        self.assertIn(STAGE_05.slug, record.invalidated)

    def test_a_withdrawal_records_a_drifted_approval_separately(self) -> None:
        """The interesting half: approvals a stage-number rule would have kept."""

        write_text(
            self.paths.research_rounds,
            json.dumps({"rounds": [{"round": 1, "decision": "refine_design", "rationale": "x"}]}) + "\n",
        )
        mark_stage_approved_manifest(self.paths, STAGE_02, 1, [])
        write_text(
            self.paths.research_rounds,
            json.dumps({"rounds": [{"round": 1, "decision": "abandon", "rationale": "y"}]}) + "\n",
        )

        rollback_to_stage(self.paths, STAGE_03, "the design was wrong")

        record = load_withdrawals(self.paths)[0]
        self.assertTrue(any("research_rounds" in item for item in record.drifted))


class ItReachesTheStageThatCouldRepeatItTests(LedgerTestCase):
    def test_the_readership_is_every_stage_a_backward_edge_can_land_on(self) -> None:
        """Derived from the graph, so a new backward edge brings its target with it."""

        channel = next(item for item in CHANNELS if item.key == "withdrawal_history")
        self.assertEqual(channel.consumed_by, frozenset(edge.target for edge in REVISIT_EDGES))
        self.assertNotIn(INTAKE_STAGE.slug, channel.consumed_by)
        self.assertNotIn(STAGE_08.slug, channel.consumed_by)

    def test_a_clean_run_carries_no_block(self) -> None:
        self.assertIsNone(format_withdrawal_history_for_prompt(self.paths, STAGE_04))

    def test_a_re_entered_stage_is_told_what_was_taken_back_from_it(self) -> None:
        rollback_to_stage(self.paths, STAGE_04, "the implementation did not match the design")

        block = format_withdrawal_history_for_prompt(self.paths, STAGE_04)
        assert block is not None
        self.assertIn("This stage has been withdrawn 1 time(s)", block)
        self.assertIn("did not match the design", block)

    def test_another_stage_sees_it_as_context_rather_than_as_its_own(self) -> None:
        rollback_to_stage(self.paths, STAGE_04, "the implementation was wrong")

        block = format_withdrawal_history_for_prompt(self.paths, STAGE_02)
        assert block is not None
        self.assertNotIn("This stage has been withdrawn", block)
        self.assertIn("Other withdrawals in this run:", block)

    def test_the_block_is_bounded(self) -> None:
        """An unbounded history would crowd out the work the stage is being asked to do."""

        for index in range(PROMPT_WITHDRAWAL_LIMIT + 4):
            append_withdrawal(
                self.paths,
                WithdrawalRecord(at=f"t{index}", target_stage=STAGE_04.slug, reason=f"reason-{index}"),
            )

        block = format_withdrawal_history_for_prompt(self.paths, STAGE_04)
        assert block is not None
        self.assertNotIn("reason-0", block)
        self.assertIn(f"reason-{PROMPT_WITHDRAWAL_LIMIT + 3}", block)
        self.assertIn(f"withdrawn {PROMPT_WITHDRAWAL_LIMIT + 4} time(s)", block)


if __name__ == "__main__":
    unittest.main()
