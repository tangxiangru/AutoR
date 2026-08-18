"""Tests for bounded automatic recovery (Issue #35).

Validates that:
- MAX_STAGE_ATTEMPTS is enforced on all retry loops.
- Recovery context is injected into continuation prompts after repeated failures.
- Normal first-attempt prompts do not include recovery context.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.evolution import EvolutionConfig
from src.manager import ResearchManager
from src.manifest import load_run_manifest
from src.operator import ClaudeOperator
from src.terminal_ui import TerminalUI
from src.utils import (
    MAX_STAGE_ATTEMPTS,
    attempts_exhausted,
    STAGES,
    build_continuation_prompt,
    build_run_paths,
    create_run_root,
    ensure_run_layout,
    format_stage_template,
    initialize_memory,
    initialize_run_config,
    load_prompt_template,
    write_text,
)


class TestMaxStageAttemptsConstant(unittest.TestCase):
    """The default is no ceiling, and the sentinel is not a number.

    It was 5. Exhausting it does not stop a run -- it auto-skips the stage and carries
    on -- so the ceiling's real effect was to turn "this stage is taking a while" into
    "this stage did not happen", inside an artifact that still reads as a finished run.
    A live ResearchClawBench run skipped its literature survey and its hypothesis
    generation exactly that way.
    """

    def test_the_default_is_no_ceiling(self):
        self.assertIsNone(MAX_STAGE_ATTEMPTS)
        self.assertFalse(attempts_exhausted(10_000, MAX_STAGE_ATTEMPTS))

    def test_the_sentinel_is_none_and_not_zero(self):
        # Zero already meant something: allow no attempts, fail at once. It is how a test
        # forces the skip path. Overloading it would turn that lever into its opposite and
        # hang the run instead of failing it.
        self.assertTrue(attempts_exhausted(1, 0))

    def test_an_integer_ceiling_still_caps(self):
        self.assertFalse(attempts_exhausted(5, 5))
        self.assertTrue(attempts_exhausted(6, 5))


class TestRecoveryContextInContinuationPrompt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmp) / "runs"
        self.runs_dir.mkdir()
        self.run_root = create_run_root(self.runs_dir)
        self.paths = build_run_paths(self.run_root)
        ensure_run_layout(self.paths)
        initialize_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "Test goal")
        write_text(self.paths.user_input, "Test goal")

        self.stage = STAGES[0]
        repo_root = Path(__file__).resolve().parent.parent
        prompt_dir = repo_root / "src" / "prompts"
        template = load_prompt_template(prompt_dir, self.stage)
        self.stage_template = format_stage_template(template, self.stage, self.paths)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_no_recovery_context_on_first_attempt(self):
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=1,
            previous_validation_errors=["missing ## Key Results"],
        )
        self.assertNotIn("# Recovery Context", prompt)

    def test_no_recovery_context_on_second_attempt(self):
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=2,
            previous_validation_errors=["missing ## Key Results"],
        )
        self.assertNotIn("# Recovery Context", prompt)

    def test_recovery_context_on_third_attempt(self):
        errors = ["missing ## Key Results", "missing ## Files Produced"]
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=3,
            previous_validation_errors=errors,
        )
        self.assertIn("# Recovery Context", prompt)
        self.assertIn("attempt 3", prompt)
        self.assertIn("missing ## Key Results", prompt)
        self.assertIn("missing ## Files Produced", prompt)

    def test_recovery_context_mentions_human_reviewer(self):
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=4,
            previous_validation_errors=["missing section"],
        )
        self.assertIn("human reviewer", prompt)

    def test_no_recovery_context_without_errors(self):
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=5,
            previous_validation_errors=None,
        )
        self.assertNotIn("# Recovery Context", prompt)

    def test_no_recovery_context_with_empty_errors(self):
        prompt = build_continuation_prompt(
            self.stage, self.stage_template, self.paths,
            handoff_context="", revision_feedback=None,
            attempt_no=5,
            previous_validation_errors=[],
        )
        self.assertNotIn("# Recovery Context", prompt)


class TestRunStageMaxAttempts(unittest.TestCase):
    """Test that _run_stage stops after MAX_STAGE_ATTEMPTS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.runs_dir = Path(self.tmp) / "runs"
        self.runs_dir.mkdir()
        self.run_root = create_run_root(self.runs_dir)
        self.paths = build_run_paths(self.run_root)
        ensure_run_layout(self.paths)
        initialize_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "Test goal")
        write_text(self.paths.user_input, "Test goal")

        self.repo_root = Path(__file__).resolve().parent.parent
        self.ui = TerminalUI()
        self.operator = ClaudeOperator(
            model="sonnet", fake_mode=True, ui=self.ui,
        )
        self.manager = ResearchManager(
            project_root=self.repo_root,
            runs_dir=self.runs_dir,
            operator=self.operator,
            ui=self.ui,
            # Improvement rounds off: this file measures the retry window and the
            # recovery path, and a polish round is an operator call that is neither.
            evolution=EvolutionConfig(rounds=0),
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_valid_stage_draft(self, stage) -> Path:
        produced = self.paths.notes_dir / f"{stage.slug}_note.md"
        produced.parent.mkdir(parents=True, exist_ok=True)
        produced.write_text("note", encoding="utf-8")
        draft_path = self.paths.stage_tmp_file(stage)
        draft_path.write_text(
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
        return draft_path

    def test_run_stage_uses_fresh_window_despite_historical_attempt_count(self):
        from src.utils import write_attempt_count
        stage = STAGES[0]
        write_attempt_count(self.paths, stage, MAX_STAGE_ATTEMPTS)
        draft_path = self._write_valid_stage_draft(stage)
        self.operator.run_stage = MagicMock(
            return_value=MagicMock(
                success=True,
                exit_code=0,
                session_id="session-1",
                stage_file_path=draft_path,
                stdout="",
                stderr="",
            )
        )
        self.manager._display_stage_output = MagicMock()
        self.manager._ask_choice = MagicMock(return_value="5")

        result = self.manager._run_stage(self.paths, stage)
        self.assertTrue(result)
        self.operator.run_stage.assert_called_once()
        self.assertTrue(self.paths.stage_file(stage).exists())

    def test_the_attempt_ceiling_defaults_to_no_limit_and_can_be_set(self):
        from src.manager import ResearchManager

        default = ResearchManager(
            project_root=self.repo_root,
            runs_dir=self.runs_dir,
            operator=self.operator,
            ui=self.ui,
        )
        self.assertEqual(default.max_stage_attempts, MAX_STAGE_ATTEMPTS)
        self.assertIsNone(default.max_stage_attempts)

        # A caller with time to spend can buy more retries, which is the whole point: each one
        # re-runs the stage with the previous attempt's validation errors attached.
        raised = ResearchManager(
            project_root=self.repo_root,
            runs_dir=self.runs_dir,
            operator=self.operator,
            ui=self.ui,
            max_stage_attempts=9,
        )
        self.assertEqual(raised.max_stage_attempts, 9)

    def test_the_recorded_ceiling_is_the_instance_value_not_a_constant(self):
        # Pinning a value other than 0 is what proves the loop reads self.max_stage_attempts:
        # a hardcoded constant would report 5 here, and the old module-level patch would too.
        stage = STAGES[0]
        self.manager.max_stage_attempts = 2
        self.manager._ask_choice = MagicMock(return_value="3")

        from src.utils import write_attempt_count

        write_attempt_count(self.paths, stage, 2)

        self.manager._run_stage(self.paths, stage)

        manifest = load_run_manifest(self.paths.run_manifest)
        self.assertIsNotNone(manifest)
        entry = next(item for item in manifest.stages if item.slug == stage.slug)
        self.assertIn("Exceeded 2 attempts", entry.last_error or "")

    def test_run_stage_marks_manifest_failed_when_attempt_window_is_exhausted(self):
        stage = STAGES[0]

        # The ceiling is per-manager, not a module global: patching the constant would no
        # longer reach the loop that reads it.
        self.manager.max_stage_attempts = 0
        result = self.manager._run_stage(self.paths, stage)

        self.assertFalse(result)
        manifest = load_run_manifest(self.paths.run_manifest)
        self.assertIsNotNone(manifest)
        stage_entry = next(entry for entry in manifest.stages if entry.slug == stage.slug)
        self.assertEqual(stage_entry.status, "failed")
        self.assertIn("Exceeded 0 attempts", stage_entry.last_error or "")


if __name__ == "__main__":
    unittest.main()


class TheGoalSurvivesARetryTest(unittest.TestCase):
    """The one input the whole stage is judged against was an agent-pull with an opt-out.

    `build_continuation_prompt` said "read the original user goal from <path> if needed".
    Approved memory stays a pointer beside it on purpose -- p90 132 KB over 197 archived
    prompts, against the goal's 16.7 KB maximum -- but the goal itself is the cheapest
    block in the prompt and the first thing a long-horizon harness must not lose.
    """

    def _paths(self, tmp: str, goal: str):
        from src.utils import build_run_paths, ensure_run_layout, write_text

        paths = build_run_paths(Path(tmp) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, goal)
        return paths

    def test_the_goal_is_in_the_retry_prompt(self) -> None:
        from src.utils import STAGES, build_continuation_prompt

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "Derive the coupling limit and report it in GeV^-1.")
            prompt = build_continuation_prompt(
                STAGES[2], "template", paths, handoff_context="", revision_feedback=None
            )
            self.assertIn("# Original User Request", prompt)
            self.assertIn("Derive the coupling limit", prompt)

    def test_memory_is_still_a_pointer(self) -> None:
        """The control on the trade: inlining the goal is not inlining everything."""
        from src.utils import STAGES, build_continuation_prompt

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "goal")
            prompt = build_continuation_prompt(
                STAGES[2], "template", paths, handoff_context="", revision_feedback=None
            )
            self.assertIn("Read approved memory from", prompt)

    def test_a_pathological_goal_is_clipped_to_the_declared_budget(self) -> None:
        from src.utils import MAX_RETRY_GOAL_CHARS, STAGES, build_continuation_prompt

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "g" * (MAX_RETRY_GOAL_CHARS * 2))
            prompt = build_continuation_prompt(
                STAGES[2], "template", paths, handoff_context="", revision_feedback=None
            )
            self.assertLess(prompt.count("g"), MAX_RETRY_GOAL_CHARS + 100)

    def test_the_premise_no_longer_claims_a_conversation(self) -> None:
        """Only the operator knows whether the earlier turns are in context."""
        from src.utils import STAGES, build_continuation_prompt

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "goal")
            prompt = build_continuation_prompt(
                STAGES[2], "template", paths, handoff_context="", revision_feedback=None
            )
            self.assertNotIn("same AutoR conversation", prompt)
            self.assertIn("existing draft", prompt)

    def test_the_discipline_list_numbers_each_item_once(self) -> None:
        """It had two items numbered 4, which is how a list nobody counts reads."""
        import re

        from src.utils import STAGES, build_continuation_prompt

        with tempfile.TemporaryDirectory() as tmp:
            paths = self._paths(tmp, "goal")
            prompt = build_continuation_prompt(
                STAGES[2], "template", paths, handoff_context="", revision_feedback=None
            )
            block = prompt.split("# Continuation Discipline", 1)[1].split("\n# ", 1)[0]
            numbers = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", block, re.M)]
            self.assertEqual(numbers, list(range(1, len(numbers) + 1)))
