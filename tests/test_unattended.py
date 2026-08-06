from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

import main as autor_main
from src.manager import ResearchManager
from src.manifest import load_run_manifest, mark_stage_skipped_manifest
from src.terminal_ui import TerminalUI, UnattendedInputError
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text


class AlwaysTTY(io.StringIO):
    """A stream that claims to be a terminal, like the stdin a harness inherits."""

    def isatty(self) -> bool:
        return True


class UnattendedTerminalUITest(unittest.TestCase):
    def test_read_line_raises_instead_of_blocking(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY("y\n"), interactive=False)
        with self.assertRaises(UnattendedInputError):
            ui.ask_yes_no("Do you have existing resources to include?")

    def test_error_message_names_the_prompt_without_ansi(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY(), interactive=False)
        with self.assertRaises(UnattendedInputError) as caught:
            ui.read_single_line("Recovery choice [1/2/3]: ")
        message = str(caught.exception)
        self.assertIn("Recovery choice [1/2/3]:", message)
        self.assertNotIn("\x1b", message)

    def test_menu_selection_does_not_consume_a_tty(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY("1\n"), interactive=False)
        self.assertFalse(ui._interactive_input_available())
        with self.assertRaises(UnattendedInputError):
            ui.choose_action(["a", "b", "c"])

    def test_interactive_ui_still_reads_input(self) -> None:
        ui = TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY("n\n"), interactive=True)
        self.assertFalse(ui.ask_yes_no("Add resources?", default=True))


class UnattendedArgResolutionTest(unittest.TestCase):
    def _args(self, argv: list[str]):
        import sys
        from unittest.mock import patch

        with patch.object(sys, "argv", ["main.py", *argv]):
            return autor_main.parse_args()

    def test_full_auto_implies_unattended(self) -> None:
        self.assertTrue(autor_main.resolve_unattended(self._args(["--full-auto", "--goal", "g"])))

    def test_agent_approval_mode_implies_unattended(self) -> None:
        args = self._args(["--approval-mode", "agent", "--goal", "g"])
        self.assertTrue(autor_main.resolve_unattended(args))

    def test_manual_default_stays_interactive(self) -> None:
        self.assertFalse(autor_main.resolve_unattended(self._args(["--goal", "g"])))

    def test_unattended_run_refuses_to_prompt_for_a_goal(self) -> None:
        with self.assertRaises(ValueError) as caught:
            autor_main.resolve_goal(self._args(["--full-auto"]), unattended=True)
        self.assertIn("--goal", str(caught.exception))

    def test_goal_file_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            goal_file = Path(tmp) / "goal.txt"
            goal_file.write_text("Study the provided dataset.\n", encoding="utf-8")
            args = self._args(["--full-auto", "--goal-file", str(goal_file)])
            self.assertEqual(autor_main.resolve_goal(args, unattended=True), "Study the provided dataset.")

    def test_goal_and_goal_file_are_mutually_exclusive(self) -> None:
        args = self._args(["--goal", "a", "--goal-file", "b.txt"])
        with self.assertRaises(ValueError):
            autor_main.resolve_goal(args, unattended=False)


class StubOperator:
    model = "stub-model"
    backend_name = "claude"


class UnattendedExhaustionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.run_root = self.root / "runs" / "run_0001"
        self.paths = build_run_paths(self.run_root)
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")
        self.addCleanup(self._tmp.cleanup)

    def _manager(self, *, unattended: bool, max_auto_skips: int = 3) -> ResearchManager:
        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.root / "runs",
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), input_stream=AlwaysTTY(), interactive=not unattended),
            unattended=unattended,
            max_auto_skips=max_auto_skips,
        )

    def test_exhausted_stage_is_auto_skipped_and_the_run_continues(self) -> None:
        manager = self._manager(unattended=True)
        stage = STAGES[1]

        proceeded = manager._handle_stage_exhaustion(
            paths=self.paths,
            stage=stage,
            attempt_no=5,
            last_validation_errors=["Missing 'Key Results' section"],
        )

        self.assertTrue(proceeded)
        self.assertEqual(manager.auto_skipped_stages, [stage.slug])
        self.assertTrue(self.paths.stage_file(stage).exists())
        self.assertIn("unattended_auto_skip", read_text(self.paths.logs))

    def test_auto_skip_budget_is_enforced(self) -> None:
        manager = self._manager(unattended=True, max_auto_skips=2)

        for stage in STAGES[:2]:
            self.assertTrue(
                manager._handle_stage_exhaustion(
                    paths=self.paths, stage=stage, attempt_no=5, last_validation_errors=[]
                )
            )

        self.assertFalse(
            manager._handle_stage_exhaustion(
                paths=self.paths, stage=STAGES[2], attempt_no=5, last_validation_errors=[]
            )
        )
        self.assertEqual(len(manager.auto_skipped_stages), 2)
        self.assertIn("unattended_abort", read_text(self.paths.logs))

    def test_the_skip_summary_says_it_was_skipped(self) -> None:
        manager = self._manager(unattended=True)
        stage = STAGES[0]
        manager._handle_stage_exhaustion(
            paths=self.paths, stage=stage, attempt_no=3, last_validation_errors=[]
        )
        summary = read_text(self.paths.stage_file(stage))
        self.assertIn("skip", summary.lower())

    def test_an_auto_skipped_stage_is_not_recorded_as_approved(self) -> None:
        """The manifest is the machine-readable record of what happened.

        An auto-skip means the retry budget ran out and nobody looked at the
        stage. Recording that as ``approved`` leaves every downstream reader
        (resume, Studio, the writing manifest) unable to tell reviewed work
        from work that was never done.
        """
        manager = self._manager(unattended=True)
        stage = STAGES[1]

        manager._handle_stage_exhaustion(
            paths=self.paths,
            stage=stage,
            attempt_no=5,
            last_validation_errors=["Missing 'Key Results' section"],
        )

        manifest = load_run_manifest(self.paths.run_manifest)
        assert manifest is not None
        entry = next(item for item in manifest.stages if item.slug == stage.slug)
        self.assertEqual(entry.status, "skipped")
        self.assertFalse(entry.approved)
        self.assertIsNone(entry.approved_at)
        self.assertTrue(entry.skipped)
        self.assertEqual(entry.skip_kind, "auto")
        self.assertIn("unattended", (entry.skip_reason or "").lower())
        # ...but the run still advances past it.
        self.assertTrue(entry.settled)
        self.assertNotIn(stage, manager._select_stages_for_run(self.paths, None))

    def test_an_auto_skip_does_not_claim_a_human_directed_it(self) -> None:
        manager = self._manager(unattended=True)
        stage = STAGES[1]

        manager._handle_stage_exhaustion(
            paths=self.paths, stage=stage, attempt_no=5, last_validation_errors=[]
        )

        summary = read_text(self.paths.stage_file(stage))
        self.assertNotIn("human direction", summary)
        self.assertNotIn("human-directed", summary)
        self.assertIn("no human in the loop", summary)
        self.assertIn("No human reviewed or directed this skip.", summary)
        self.assertNotIn(
            "human-directed skip summary", read_text(self.paths.logs)
        )

    def test_a_human_skip_is_distinguishable_from_an_auto_skip(self) -> None:
        manager = self._manager(unattended=True)
        auto_stage, human_stage = STAGES[1], STAGES[2]

        manager._handle_stage_exhaustion(
            paths=self.paths, stage=auto_stage, attempt_no=5, last_validation_errors=[]
        )
        manager._skip_stage(
            paths=self.paths,
            stage=human_stage,
            attempt_no=1,
            reason="Human operator skipped this stage via /skip.",
            kind="human",
        )

        manifest = load_run_manifest(self.paths.run_manifest)
        assert manifest is not None
        kinds = {
            item.slug: item.skip_kind for item in manifest.stages if item.skipped
        }
        self.assertEqual(kinds, {auto_stage.slug: "auto", human_stage.slug: "human"})

    def test_a_skip_kind_outside_the_two_known_values_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            mark_stage_skipped_manifest(
                self.paths, STAGES[0], 1, [], reason="whatever", kind="probably"
            )

    def test_attended_mode_on_a_tty_still_asks_a_human(self) -> None:
        manager = self._manager(unattended=False)
        # The stub TTY has no input queued, so the read fails rather than silently proceeding.
        with self.assertRaises(EOFError):
            manager._handle_stage_exhaustion(
                paths=self.paths, stage=STAGES[1], attempt_no=5, last_validation_errors=[]
            )
        self.assertEqual(manager.auto_skipped_stages, [])


if __name__ == "__main__":
    unittest.main()
