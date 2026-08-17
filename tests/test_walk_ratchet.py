"""A backward move that made the run worse is itself taken back.

Two halves. :class:`SnapshotTests` covers the mechanism the rewind is built on — version
pointers into the blob store, cheap enough to take at every departure. :class:`RatchetTests`
covers the judgement: an excursion is compared on the score of the stage it left and
returned to, and only a drop is acted on.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.effects import apply_withdrawal
from src.provenance import load_ledger, observe, plan_restore, snapshot, trim_to_snapshot
from src.stage_graph import GraphState, Visit
from src.utils import STAGES, build_run_paths, ensure_run_layout, write_text
from src.walk_ratchet import (
    MAX_REWINDS_PER_STAGE,
    RATCHET_MARGIN,
    begin,
    last_score_for,
    open_excursion,
    outcomes,
    rewinds_so_far,
    settle,
    summarise,
)

STAGE_03, STAGE_04, STAGE_05, STAGE_06 = STAGES[2], STAGES[3], STAGES[4], STAGES[5]


class RatchetTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)

    def visited(self, *pairs: tuple[str, float | None]) -> GraphState:
        state = GraphState()
        for slug, score in pairs:
            state.path.append(Visit(stage=slug, entered_at="t", score_total=score))
        return state


class SnapshotTests(RatchetTestCase):
    def test_a_snapshot_is_pointers_rather_than_a_copy(self) -> None:
        write_text(self.paths.data_dir / "counts.csv", "one\n")
        observe(self.paths, STAGE_03)

        marks = snapshot(self.paths)
        self.assertEqual(list(marks), ["data/counts.csv"])
        self.assertEqual(marks["data/counts.csv"], load_ledger(self.paths).entries["data/counts.csv"].version_uid)

    def test_an_unchanged_file_is_not_in_the_restore_plan(self) -> None:
        write_text(self.paths.data_dir / "counts.csv", "one\n")
        observe(self.paths, STAGE_03)
        marks = snapshot(self.paths)

        self.assertEqual(plan_restore(self.paths, marks), [])

    def test_a_file_created_after_the_snapshot_is_planned_for_deletion(self) -> None:
        marks = snapshot(self.paths)
        write_text(self.paths.data_dir / "later.csv", "later\n")
        observe(self.paths, STAGE_05)

        plan = plan_restore(self.paths, marks)
        self.assertEqual([item.rel_path for item in plan], ["data/later.csv"])
        self.assertTrue(plan[0].deletes)

    def test_a_file_changed_after_the_snapshot_is_rewound_to_the_marked_version(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "before\n")
        observe(self.paths, STAGE_03)
        marks = snapshot(self.paths)
        write_text(target, "after\n")
        observe(self.paths, STAGE_05)

        apply_withdrawal(self.paths, plan_restore(self.paths, marks))

        self.assertEqual(target.read_text(encoding="utf-8"), "before\n")

    def test_trimming_leaves_the_ledger_describing_what_the_restore_left(self) -> None:
        target = self.paths.data_dir / "counts.csv"
        write_text(target, "before\n")
        observe(self.paths, STAGE_03)
        marks = snapshot(self.paths)
        write_text(target, "after\n")
        observe(self.paths, STAGE_05)

        apply_withdrawal(self.paths, plan_restore(self.paths, marks))
        trim_to_snapshot(self.paths, marks)

        entry = load_ledger(self.paths).entries["data/counts.csv"]
        self.assertEqual(entry.version_uid, marks["data/counts.csv"])
        self.assertEqual(entry.last_written_by_stage, STAGE_03.slug)
        self.assertEqual(
            entry.content_hash,
            load_ledger(self.paths).entries["data/counts.csv"].content_hash,
        )

    def test_a_uid_is_still_never_reissued_after_a_rewind(self) -> None:
        """The counter is monotone across a rewind, or a consumer could not tell the
        rewound state from the state it was rewound out of."""

        target = self.paths.data_dir / "counts.csv"
        write_text(target, "before\n")
        observe(self.paths, STAGE_03)
        marks = snapshot(self.paths)
        write_text(target, "after\n")
        observe(self.paths, STAGE_05)
        before_uid = load_ledger(self.paths).next_uid

        apply_withdrawal(self.paths, plan_restore(self.paths, marks))
        trim_to_snapshot(self.paths, marks)

        self.assertEqual(load_ledger(self.paths).next_uid, before_uid)
        write_text(target, "third\n")
        observe(self.paths, STAGE_03)
        self.assertGreaterEqual(load_ledger(self.paths).next_uid, before_uid + 1)


class ExcursionLifecycleTests(RatchetTestCase):
    def test_a_backward_move_opens_an_excursion_with_the_departing_score(self) -> None:
        state = self.visited((STAGE_06.slug, 71.0))

        excursion = begin(self.paths, state, STAGE_06, STAGE_03, "the design was wrong")

        assert excursion is not None
        self.assertEqual(excursion.baseline, 71.0)
        self.assertEqual(excursion.from_stage, STAGE_06.slug)
        self.assertEqual(open_excursion(self.paths).from_stage, STAGE_06.slug)

    def test_a_second_backward_move_extends_the_outer_one_rather_than_nesting(self) -> None:
        """Judging an inner excursion against a state that is itself under review would
        let two bad moves ratify each other."""

        state = self.visited((STAGE_06.slug, 71.0), (STAGE_05.slug, 60.0))
        begin(self.paths, state, STAGE_06, STAGE_03, "first")

        self.assertIsNone(begin(self.paths, state, STAGE_05, STAGE_04, "second"))
        self.assertEqual(open_excursion(self.paths).from_stage, STAGE_06.slug)

    def test_the_excursion_does_not_close_before_the_ground_is_recovered(self) -> None:
        state = self.visited((STAGE_06.slug, 71.0))
        begin(self.paths, state, STAGE_06, STAGE_03, "the design was wrong")

        self.assertIsNone(settle(self.paths, state, STAGE_04, 50.0))
        self.assertIsNotNone(open_excursion(self.paths))

    def test_settle_is_a_no_op_with_no_excursion_open(self) -> None:
        self.assertIsNone(settle(self.paths, self.visited(), STAGE_06, 71.0))

    def test_the_closing_score_falls_back_to_the_last_one_recorded(self) -> None:
        """The rollback paths leave with no score; both ends must be read the same way."""

        state = self.visited((STAGE_06.slug, 71.0))
        begin(self.paths, state, STAGE_06, STAGE_03, "x")
        state.path.append(Visit(stage=STAGE_06.slug, entered_at="t", score_total=80.0))

        outcome = settle(self.paths, state, STAGE_06, None)

        assert outcome is not None
        self.assertEqual(outcome.closed_at_score, 80.0)
        self.assertEqual(last_score_for(state, STAGE_06.slug), 80.0)


class RatchetTests(RatchetTestCase):
    def _excursion_scoring(self, before: float | None, after: float | None):
        state = self.visited((STAGE_06.slug, before))
        write_text(self.paths.data_dir / "kept.csv", "before\n")
        observe(self.paths, STAGE_06)
        begin(self.paths, state, STAGE_06, STAGE_03, "the design was wrong")
        write_text(self.paths.data_dir / "excursion.csv", "made during the excursion\n")
        observe(self.paths, STAGE_04)
        return state, settle(self.paths, state, STAGE_06, after)

    def test_an_excursion_that_improved_is_kept(self) -> None:
        _, outcome = self._excursion_scoring(71.0, 78.0)

        assert outcome is not None
        self.assertEqual(outcome.verdict, "improved")
        self.assertTrue((self.paths.data_dir / "excursion.csv").exists())

    def test_an_excursion_that_held_is_kept(self) -> None:
        _, outcome = self._excursion_scoring(71.0, 71.0)

        assert outcome is not None
        self.assertEqual(outcome.verdict, "held")
        self.assertTrue((self.paths.data_dir / "excursion.csv").exists())

    def test_an_excursion_that_made_the_run_worse_is_taken_back(self) -> None:
        """The whole point: a backward move is not exempt from the ordering it exists to fix."""

        _, outcome = self._excursion_scoring(71.0, 64.0)

        assert outcome is not None
        self.assertEqual(outcome.verdict, "rewound")
        self.assertFalse((self.paths.data_dir / "excursion.csv").exists())
        self.assertTrue((self.paths.data_dir / "kept.csv").exists())

    def test_an_unscored_end_is_recorded_rather_than_judged(self) -> None:
        _, outcome = self._excursion_scoring(None, 64.0)

        assert outcome is not None
        self.assertEqual(outcome.verdict, "unjudgeable")
        self.assertTrue((self.paths.data_dir / "excursion.csv").exists())

    def test_the_margin_is_zero_because_the_rubric_is_mechanical(self) -> None:
        """Named so that swapping in a judged score is a change to an argued value."""

        self.assertEqual(RATCHET_MARGIN, 0.0)

    def test_the_ratchet_overrules_one_stage_only_so_many_times(self) -> None:
        """A rewind restores the state that made the move look attractive; uncapped, that
        is the loop the ratchet exists to detect."""

        for _ in range(MAX_REWINDS_PER_STAGE):
            self._excursion_scoring(71.0, 64.0)
        self.assertEqual(rewinds_so_far(self.paths, STAGE_06.slug), MAX_REWINDS_PER_STAGE)

        _, outcome = self._excursion_scoring(71.0, 64.0)

        assert outcome is not None
        self.assertEqual(outcome.verdict, "worse_but_capped")
        self.assertTrue((self.paths.data_dir / "excursion.csv").exists())

    def test_every_closed_excursion_is_on_the_record(self) -> None:
        self._excursion_scoring(71.0, 78.0)
        self._excursion_scoring(71.0, 64.0)

        self.assertEqual([item.verdict for item in outcomes(self.paths)], ["improved", "rewound"])
        block = summarise(self.paths)
        self.assertIn("2 backward move(s) closed", block)
        self.assertIn("improved x1", block)

    def test_a_run_with_no_backward_move_says_so(self) -> None:
        self.assertIn("No backward move has closed", summarise(self.paths))


if __name__ == "__main__":
    unittest.main()
