"""A crux asked twice is one crux.

A live run put the identical question to the panel on two consecutive stage attempts. Both
escalations were byte-for-byte the same string, both spent four voice calls, and the ledger
recorded ``cruxes_raised: 2`` -- inflating the one number that is supposed to say how much
deliberation the run actually needed.

The cause is structural rather than a model quirk. A stage that fails its gate is sent back
with the same state it had before, regenerates its escalation from that state, and asks the
same thing again. With ``--max-deliberations 3`` the budget is exhausted after three attempts
of a single stage, and a genuinely new crux in Stage 04 is then refused.

The threshold is calibrated in ``REPEAT_THRESHOLD``'s comment against questions from that run.
"""

from __future__ import annotations

import tempfile
import unittest
import json
from pathlib import Path

from src.deliberation import (
    REPEAT_THRESHOLD,
    CruxRequest,
    Position,
    Resolution,
    read_ledger,
    record_resolution,
    settled_answer,
)
from src.ideation_panel import similarity
from src.utils import build_run_paths, resolve_stage

QUESTION = (
    "For a three-way comparison of LASSO, ridge and elastic net on selection stability, what "
    "should count as 'variable j was selected' for ridge, which never sets a coefficient to "
    "zero? Specifically: should the primary estimand be (a) top-k support with k matched "
    "per-resample to the lasso's cardinality, (b) rank agreement only, with no notion of a "
    "selected set, or (c) an absolute threshold on |beta-hat|?"
)
FOLLOW_UP = (
    "We settled on matched-cardinality top-k for ridge. Should k be matched per-resample to "
    "the lasso, or fixed at the full-sample lasso cardinality?"
)
UNRELATED = (
    "How should the penalty parameter be chosen for each regularizer -- one nested CV per "
    "bootstrap resample, or a single penalty fixed on the full sample and reused?"
)


def _entry(question: str, *, answer: str) -> dict:
    return {"request": {"question": question}, "answer": answer}


class SettledAnswerTest(unittest.TestCase):
    def test_the_verbatim_repeat_from_the_live_run_is_recognised(self) -> None:
        found = settled_answer(
            [_entry(QUESTION, answer="Use matched-cardinality top-k.")],
            CruxRequest(question=QUESTION),
        )
        self.assertIsNotNone(found)
        self.assertEqual(found["answer"], "Use matched-cardinality top-k.")

    def test_an_unanswered_earlier_attempt_does_not_block_a_retry(self) -> None:
        # The live run's two entries both had an empty answer because every voice failed.
        # A panel that could not be reached last time may be reachable now; suppressing the
        # retry would mean one outage permanently silences a crux.
        self.assertIsNone(
            settled_answer([_entry(QUESTION, answer="")], CruxRequest(question=QUESTION))
        )

    def test_a_whitespace_only_answer_is_not_an_answer(self) -> None:
        self.assertIsNone(
            settled_answer([_entry(QUESTION, answer="   \n ")], CruxRequest(question=QUESTION))
        )

    def test_a_different_crux_from_the_same_stage_is_not_a_repeat(self) -> None:
        self.assertIsNone(
            settled_answer([_entry(QUESTION, answer="an answer")], CruxRequest(question=UNRELATED))
        )

    def test_a_narrowed_follow_up_is_a_new_question_not_a_repeat(self) -> None:
        # The boundary that matters. A follow-up that builds on the answer shares vocabulary
        # with the original but asks something the original did not settle. Treating it as a
        # repeat would hand back an answer that does not address it.
        self.assertIsNone(
            settled_answer([_entry(QUESTION, answer="an answer")], CruxRequest(question=FOLLOW_UP))
        )

    def test_the_threshold_sits_above_the_follow_up_with_room(self) -> None:
        # Pins the calibration rather than the number: the rule only holds while the
        # follow-up scores clearly below the threshold.
        self.assertLess(similarity(QUESTION, FOLLOW_UP) + 0.2, REPEAT_THRESHOLD)
        self.assertGreaterEqual(similarity(QUESTION, QUESTION), REPEAT_THRESHOLD)

    def test_the_most_recent_settled_answer_wins(self) -> None:
        found = settled_answer(
            [_entry(QUESTION, answer="first"), _entry(QUESTION, answer="second")],
            CruxRequest(question=QUESTION),
        )
        self.assertEqual(found["answer"], "second")

    def test_a_malformed_entry_is_skipped_not_raised(self) -> None:
        self.assertIsNone(
            settled_answer(
                [{"request": "not a dict", "answer": "x"}, {"answer": "y"}],
                CruxRequest(question=QUESTION),
            )
        )

    def test_an_empty_ledger_settles_nothing(self) -> None:
        self.assertIsNone(settled_answer([], CruxRequest(question=QUESTION)))


class ReadLedgerTest(unittest.TestCase):
    def test_a_missing_ledger_is_empty_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(read_ledger(build_run_paths(Path(tmp))), [])

    def test_a_corrupt_ledger_is_empty_not_an_error(self) -> None:
        # A run must not die because a JSON file it writes for its own bookkeeping got
        # truncated. Losing the dedup is the correct cost.
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp))
            paths.reviews_dir.mkdir(parents=True, exist_ok=True)
            (paths.reviews_dir / "deliberations.json").write_text("{not json")
            self.assertEqual(read_ledger(paths), [])

    def test_a_ledger_with_a_non_list_body_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp))
            paths.reviews_dir.mkdir(parents=True, exist_ok=True)
            (paths.reviews_dir / "deliberations.json").write_text('{"deliberations": "nope"}')
            self.assertEqual(read_ledger(paths), [])

    def test_a_recorded_resolution_round_trips_and_short_circuits_the_repeat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp))
            paths.reviews_dir.mkdir(parents=True, exist_ok=True)
            stage = resolve_stage("01")
            record_resolution(
                paths,
                stage,
                Resolution(
                    request=CruxRequest(question=QUESTION, stage_slug=stage.slug),
                    positions=[Position(voice="theorist", title="T", backend="claude",
                                        model="sonnet", answer="top-k")],
                    answer="Use matched-cardinality top-k.",
                    voice_calls=4,
                ),
            )
            entries = read_ledger(paths)
            self.assertEqual(len(entries), 1)
            self.assertIsNotNone(settled_answer(entries, CruxRequest(question=QUESTION)))


if __name__ == "__main__":
    unittest.main()


class ManagerReusesASettledCruxTest(unittest.TestCase):
    """The behaviour change: the panel is not reconvened, and the budget is not touched."""

    def _manager(self):
        import io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI
        from src.utils import ensure_run_config, ensure_run_layout, write_text

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        runs_dir = Path(tmp.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")
        operator = MagicMock()
        operator.model, operator.backend_name = "sonnet", "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        panel = MagicMock()
        panel.budget_left = 3
        manager.crux_panel = panel
        return manager, paths, panel

    def _raise_crux(self, paths, question: str) -> None:
        from src.deliberation import REQUEST_FILENAME
        from src.utils import write_text

        write_text(
            paths.notes_dir / REQUEST_FILENAME,
            json.dumps({"question": question, "working_answer": "my best guess"}),
        )

    def _settle(self, paths, answer: str) -> None:
        record_resolution(
            paths,
            resolve_stage("01"),
            Resolution(request=CruxRequest(question=QUESTION), answer=answer, voice_calls=4),
        )

    def test_the_panel_is_not_reconvened_for_a_question_already_answered(self) -> None:
        manager, paths, panel = self._manager()
        self._settle(paths, "Use matched-cardinality top-k.")
        self._raise_crux(paths, QUESTION)

        feedback = manager._settle_cruxes(paths, resolve_stage("01"), 2)

        panel.deliberate.assert_not_called()
        self.assertIsNotNone(feedback)
        self.assertEqual(len(manager._crux_resolutions), 1)
        self.assertEqual(
            manager._crux_resolutions[0].answer, "Use matched-cardinality top-k."
        )

    def test_the_reused_answer_does_not_add_a_second_crux_to_the_ledger(self) -> None:
        # The count the live run inflated. Reusing must not look like more deliberation.
        manager, paths, panel = self._manager()
        self._settle(paths, "Use matched-cardinality top-k.")
        self._raise_crux(paths, QUESTION)

        manager._settle_cruxes(paths, resolve_stage("01"), 2)

        self.assertEqual(len(read_ledger(paths)), 1)

    def test_a_new_question_still_reaches_the_panel(self) -> None:
        manager, paths, panel = self._manager()
        self._settle(paths, "Use matched-cardinality top-k.")
        self._raise_crux(paths, UNRELATED)
        panel.deliberate.return_value = None

        manager._settle_cruxes(paths, resolve_stage("01"), 2)

        panel.deliberate.assert_called_once()

    def test_an_unanswered_earlier_crux_still_reaches_the_panel(self) -> None:
        manager, paths, panel = self._manager()
        self._settle(paths, "")
        self._raise_crux(paths, QUESTION)
        panel.deliberate.return_value = None

        manager._settle_cruxes(paths, resolve_stage("01"), 2)

        panel.deliberate.assert_called_once()
