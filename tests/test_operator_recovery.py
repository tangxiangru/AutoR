from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.operator import ClaudeOperator
from src.utils import (
    STAGES,
    read_text,
    build_run_paths,
    ensure_run_layout,
    initialize_memory,
    read_attempt_count,
    write_attempt_count,
    write_text,
)


STAGE_01 = next(stage for stage in STAGES if stage.slug == "01_literature_survey")
STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")


class OperatorRecoveryTests(unittest.TestCase):
    def _session_id_from_command(self, command: list[str]) -> str:
        if "--session-id" in command:
            return command[command.index("--session-id") + 1]
        if "--resume" in command:
            return command[command.index("--resume") + 1]
        self.fail(f"No session flag found in command: {command}")

    def test_claude_start_persists_requested_session_not_observed_result_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Observed session id mismatch")
            initialize_memory(paths, "Observed session id mismatch")

            operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
            stage = STAGES[0]
            requested_ids: list[str] = []

            def fake_stream(*args, **kwargs):
                requested_ids.append(self._session_id_from_command(kwargs["command"]))
                write_text(paths.stage_tmp_file(stage), "# Stage 01: Literature Survey\n")
                return (
                    0,
                    "completed",
                    "",
                    "observed-but-not-resumable",
                    {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0},
                )

            with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
                operator,
                "_run_streaming_command",
                side_effect=fake_stream,
            ):
                result = operator._run_real(stage, "prompt", paths, attempt_no=1, continue_session=False)

            self.assertTrue(result.success)
            self.assertEqual(result.session_id, requested_ids[0])
            self.assertNotEqual(result.session_id, "observed-but-not-resumable")
            self.assertEqual(paths.stage_session_file(stage).read_text(encoding="utf-8").strip(), requested_ids[0])

    def test_resume_failure_falls_back_to_new_session_and_records_attempt_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Operator recovery goal")
            initialize_memory(paths, "Operator recovery goal")

            operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
            stage = STAGES[0]
            old_session_id = "old-session-id"
            operator._persist_stage_session_id(paths, stage, old_session_id)

            call_count = {"value": 0}
            fallback_requested_ids: list[str] = []

            def fake_stream(*args, **kwargs):
                call_count["value"] += 1
                if call_count["value"] == 1:
                    return (
                        1,
                        "No conversation found with session id old-session-id",
                        "",
                        None,
                        {"raw_line_count": 1, "non_json_line_count": 1, "malformed_json_count": 1},
                    )

                fallback_requested_ids.append(self._session_id_from_command(kwargs["command"]))
                stage_tmp_path = paths.stage_tmp_file(stage)
                write_text(
                    stage_tmp_path,
                    (
                        "# Stage 01: Literature Survey\n\n"
                        "## Objective\nRecovered.\n\n"
                        "## Previously Approved Stage Summaries\n_None yet._\n\n"
                        "## What I Did\nRecovered session.\n\n"
                        "## Key Results\nRecovered stage summary.\n\n"
                        "## Files Produced\n- `stages/01_literature_survey.tmp.md`\n\n"
                        "## Suggestions for Refinement\n"
                        "1. Refine one.\n2. Refine two.\n3. Refine three.\n\n"
                        "## Your Options\n"
                        "1. Use suggestion 1\n2. Use suggestion 2\n3. Use suggestion 3\n4. Refine with your own feedback\n5. Approve and continue\n6. Abort\n"
                    ),
                )
                return (
                    0,
                    "Recovered successfully.",
                    "",
                    "new-session-id",
                    {"raw_line_count": 2, "non_json_line_count": 0, "malformed_json_count": 0},
                )

            with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
                operator,
                "_run_streaming_command",
                side_effect=fake_stream,
            ):
                result = operator._run_real(
                    stage=stage,
                    prompt="prompt",
                    paths=paths,
                    attempt_no=1,
                    continue_session=True,
                )

            self.assertTrue(result.success)
            self.assertEqual(result.session_id, fallback_requested_ids[0])
            self.assertEqual(call_count["value"], 2)
            self.assertEqual(paths.stage_session_file(stage).read_text(encoding="utf-8").strip(), result.session_id)

            attempt_state = json.loads(paths.stage_attempt_state_file(stage, 1).read_text(encoding="utf-8"))
            self.assertEqual(attempt_state["status"], "completed")
            self.assertEqual(attempt_state["mode"], "resume")
            self.assertEqual(attempt_state["session_id"], result.session_id)

    def test_resume_failure_falls_back_even_when_previous_draft_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Resume failure with stale draft")
            initialize_memory(paths, "Resume failure with stale draft")

            operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
            stage = STAGES[0]
            old_session_id = "old-session-id"
            operator._persist_stage_session_id(paths, stage, old_session_id)
            write_text(paths.stage_tmp_file(stage), "stale draft from previous attempt")

            call_count = {"value": 0}
            fallback_requested_ids: list[str] = []

            def fake_stream(*args, **kwargs):
                call_count["value"] += 1
                command = kwargs["command"]
                if call_count["value"] == 1:
                    self.assertIn("--resume", command)
                    return (
                        1,
                        json.dumps(
                            {
                                "type": "result",
                                "subtype": "error_during_execution",
                                "session_id": "error-payload-session-id",
                                "errors": [
                                    "No conversation found with session ID: old-session-id",
                                ],
                            }
                        ),
                        "",
                        "error-payload-session-id",
                        {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0},
                    )

                self.assertIn("--session-id", command)
                fallback_requested_ids.append(self._session_id_from_command(command))
                write_text(paths.stage_tmp_file(stage), "# Stage 01: Literature Survey\nRecovered draft.\n")
                return (
                    0,
                    "Recovered successfully.",
                    "",
                    "observed-but-not-resumable",
                    {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0},
                )

            with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
                operator,
                "_run_streaming_command",
                side_effect=fake_stream,
            ):
                result = operator._run_real(stage, "prompt", paths, attempt_no=2, continue_session=True)

            self.assertTrue(result.success)
            self.assertEqual(call_count["value"], 2)
            self.assertEqual(result.session_id, fallback_requested_ids[0])
            self.assertNotEqual(result.session_id, "error-payload-session-id")
            self.assertNotEqual(result.session_id, "observed-but-not-resumable")
            self.assertEqual(paths.stage_session_file(stage).read_text(encoding="utf-8").strip(), result.session_id)

    def test_broken_session_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Broken session test")
            initialize_memory(paths, "Broken session test")

            operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
            stage = STAGES[0]
            write_text(
                paths.stage_session_state_file(stage),
                json.dumps(
                    {
                        "session_id": "broken-session-id",
                        "broken": True,
                    },
                    indent=2,
                ),
            )

            resolved = operator._resolve_stage_session_id(paths, stage, continue_session=False)
            self.assertIsNotNone(resolved)
            self.assertNotEqual(resolved, "broken-session-id")

    def test_broken_session_file_is_not_reused_for_repair_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_root = Path(tmp_dir) / "run"
            paths = build_run_paths(run_root)
            ensure_run_layout(paths)
            write_text(paths.user_input, "Broken session file test")
            initialize_memory(paths, "Broken session file test")

            operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
            stage = STAGES[0]
            write_text(paths.stage_session_file(stage), "broken-session-id")
            write_text(
                paths.stage_session_state_file(stage),
                json.dumps(
                    {
                        "session_id": "broken-session-id",
                        "broken": True,
                    },
                    indent=2,
                ),
            )

            resolved = operator._resolve_stage_session_id(
                paths,
                stage,
                continue_session=True,
                allow_create=False,
            )

            self.assertIsNone(resolved)


class AFreshSessionIsNotAContinuationTests(unittest.TestCase):
    """The resume fallback used to replay a document that asserted a history it had lost.

    `build_continuation_prompt` opens by telling the agent it is continuing this stage's
    conversation. When a resume is refused the operator starts a *new* session and, until
    now, sent it that same file -- so an empty session was told it was mid-conversation,
    on exactly the path where that is false.

    Whether the earlier turns are in context is a fact about the invocation, and this is
    the only place that knows it. The prompt now speaks about the work; this speaks about
    the session.
    """

    def _run_with_a_refused_resume(self, tmp_dir: str):
        paths = build_run_paths(Path(tmp_dir) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Resume refused")
        initialize_memory(paths, "Resume refused")
        operator = ClaudeOperator(fake_mode=False, output_stream=io.StringIO())
        stage = STAGES[0]
        sent: list[str] = []

        def fake_stream(*args, **kwargs):
            command = kwargs["command"]
            sent.append(read_text(Path(command[command.index("-p") + 1].lstrip("@"))))
            if len(sent) == 1:
                return (1, "", "No conversation found with session id abc", None,
                        {"raw_line_count": 0, "non_json_line_count": 0, "malformed_json_count": 0})
            write_text(paths.stage_tmp_file(stage), "# Stage 01: Literature Survey\n")
            return (0, "done", "", None,
                    {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0})

        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            operator, "_run_streaming_command", side_effect=fake_stream
        ):
            operator._run_real(
                stage, "You are continuing work on Stage 01.", paths,
                attempt_no=1, continue_session=True,
            )
        return paths, stage, sent

    def test_the_restart_is_told_its_history_is_gone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _paths, _stage, sent = self._run_with_a_refused_resume(tmp_dir)
            self.assertEqual(len(sent), 2, "the fallback ran")
            self.assertNotIn("Earlier Turns Of This Conversation Are Gone", sent[0])
            self.assertIn("Earlier Turns Of This Conversation Are Gone", sent[1])

    def test_the_restart_keeps_everything_the_original_said(self) -> None:
        """It is an addition, not a replacement: the work premise is still true."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            _paths, _stage, sent = self._run_with_a_refused_resume(tmp_dir)
            self.assertIn(sent[0].strip(), sent[1])

    def test_the_original_prompt_file_is_left_alone(self) -> None:
        """`prompt_cache/` is the record of what actually ran. Overwriting the file would
        leave the resumed attempt and its restart indistinguishable in it."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths, stage, _sent = self._run_with_a_refused_resume(tmp_dir)
            original = paths.prompt_cache_dir / f"{stage.slug}_attempt_01.prompt.md"
            restart = paths.prompt_cache_dir / f"{stage.slug}_attempt_01_restart.prompt.md"
            self.assertTrue(original.is_file() and restart.is_file())
            self.assertNotIn("Are Gone", read_text(original))


class SecondEntryToAStageTests(unittest.TestCase):
    """A session id is spent once, and a stage is entered more than once.

    `--session-id` accepts a uuid the first time and answers `Error: Session ID <uuid>
    is already in use.` the second. That string matches none of the four patterns in
    `_looks_like_resume_failure`, so the fallback in `_run_real` never fires and the
    attempt burns with nothing written. Every entry to a stage other than Studio's
    pending-feedback path starts the attempt loop at `continue_session = False` and
    builds a fresh prompt, so a revisit edge, `--redo-stage` and `--resume-run` into an
    unapproved stage all reached the CLI with an id it had already seen.
    """

    def _session_flag(self, command: list[str]) -> tuple[str, str]:
        for flag in ("--session-id", "--resume"):
            if flag in command:
                return flag, command[command.index(flag) + 1]
        self.fail(f"No session flag found in command: {command}")

    def _operator_and_paths(self, tmp_dir: str):
        paths = build_run_paths(Path(tmp_dir) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Second entry")
        initialize_memory(paths, "Second entry")
        return ClaudeOperator(fake_mode=False, output_stream=io.StringIO()), paths

    def _run(self, operator, paths, stage, *, continue_session: bool, seen: list) -> None:
        def fake_stream(*args, **kwargs):
            seen.append(self._session_flag(kwargs["command"]))
            write_text(paths.stage_tmp_file(stage), "# Stage 01: Literature Survey\n")
            return (0, "completed", "", None,
                    {"raw_line_count": 1, "non_json_line_count": 0, "malformed_json_count": 0})

        with patch("src.operator.shutil.which", return_value="/usr/bin/claude"), patch.object(
            operator, "_run_streaming_command", side_effect=fake_stream
        ):
            operator._run_real(stage, "prompt", paths, attempt_no=1, continue_session=continue_session)

    def test_a_second_entry_does_not_replay_the_first_entrys_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            operator, paths = self._operator_and_paths(tmp_dir)
            seen: list[tuple[str, str]] = []
            self._run(operator, paths, STAGE_01, continue_session=False, seen=seen)
            self._run(operator, paths, STAGE_01, continue_session=False, seen=seen)

            self.assertEqual([flag for flag, _ in seen], ["--session-id", "--session-id"])
            self.assertNotEqual(seen[0][1], seen[1][1])

    def test_a_continuation_still_resumes_the_id_the_entry_persisted(self) -> None:
        """The control. Fixing the entry must not stop a retry continuing its session."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            operator, paths = self._operator_and_paths(tmp_dir)
            seen: list[tuple[str, str]] = []
            self._run(operator, paths, STAGE_01, continue_session=False, seen=seen)
            self._run(operator, paths, STAGE_01, continue_session=True, seen=seen)

            self.assertEqual([flag for flag, _ in seen], ["--session-id", "--resume"])
            self.assertEqual(seen[0][1], seen[1][1])

    def test_two_stages_never_share_one_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            operator, paths = self._operator_and_paths(tmp_dir)
            seen: list[tuple[str, str]] = []
            self._run(operator, paths, STAGE_01, continue_session=False, seen=seen)
            self._run(operator, paths, STAGE_05, continue_session=False, seen=seen)
            self.assertNotEqual(seen[0][1], seen[1][1])


class TestResumeFailureDetection(unittest.TestCase):
    def setUp(self) -> None:
        self.op = ClaudeOperator(fake_mode=True)

    def test_exact_message_detected(self) -> None:
        self.assertTrue(
            self.op._looks_like_resume_failure(
                "Error: No conversation found with session id abc-123", ""
            )
        )

    def test_resume_not_found_detected(self) -> None:
        self.assertTrue(
            self.op._looks_like_resume_failure(
                "Could not resume: session not found", ""
            )
        )

    def test_unrelated_resume_word_not_false_positive(self) -> None:
        self.assertFalse(
            self.op._looks_like_resume_failure(
                "Please resume the experiment from checkpoint 5", ""
            )
        )

    def test_empty_output(self) -> None:
        self.assertFalse(self.op._looks_like_resume_failure("", ""))

    def test_stderr_detected(self) -> None:
        self.assertTrue(
            self.op._looks_like_resume_failure(
                "", "No conversation found with session id xyz"
            )
        )

    def test_codex_thread_resume_not_found_detected(self) -> None:
        self.assertTrue(
            self.op._looks_like_resume_failure(
                "thread/resume failed: no rollout found for thread id abc", ""
            )
        )

    def test_operator_precedence_fix(self) -> None:
        # Before the fix, this would incorrectly return True because
        # `"resume" in combined and "not found" in combined` was evaluated
        # before `or`, and both words appear in the text.
        # After the fix, "resume" + "not found" together should still match.
        self.assertTrue(
            self.op._looks_like_resume_failure(
                "Failed to resume session: not found in store", ""
            )
        )
        # But "resume" alone without "not found" should NOT match.
        self.assertFalse(
            self.op._looks_like_resume_failure(
                "Will resume processing after delay", ""
            )
        )


class TestAttemptCountPersistence(unittest.TestCase):
    def test_read_returns_zero_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            self.assertEqual(read_attempt_count(paths, STAGE_01), 0)

    def test_write_and_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_attempt_count(paths, STAGE_05, 3)
            self.assertEqual(read_attempt_count(paths, STAGE_05), 3)

    def test_increments_across_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            for i in range(1, 6):
                write_attempt_count(paths, STAGE_01, i)
            self.assertEqual(read_attempt_count(paths, STAGE_01), 5)

    def test_different_stages_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_attempt_count(paths, STAGE_01, 3)
            write_attempt_count(paths, STAGE_05, 7)
            self.assertEqual(read_attempt_count(paths, STAGE_01), 3)
            self.assertEqual(read_attempt_count(paths, STAGE_05), 7)


class TestStageTimeout(unittest.TestCase):
    def test_default_timeout_is_4_hours(self) -> None:
        op = ClaudeOperator(fake_mode=True)
        self.assertEqual(op.stage_timeout, 14400)

    def test_custom_timeout(self) -> None:
        op = ClaudeOperator(fake_mode=True, stage_timeout=7200)
        self.assertEqual(op.stage_timeout, 7200)

    def test_streaming_command_timeout_returns_consistent_tuple(self) -> None:
        class FakeStdout:
            def __iter__(self):
                return self

            def __next__(self):
                raise StopIteration

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self) -> None:
                self.stdout = FakeStdout()
                self.stdin = None

            def terminate(self) -> None:
                return None

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                return None

        class ImmediateTimer:
            def __init__(self, timeout, fn) -> None:
                self.fn = fn
                self.daemon = False

            def start(self) -> None:
                self.fn()

            def cancel(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "timeout goal")
            initialize_memory(paths, "timeout goal")
            output = io.StringIO()
            op = ClaudeOperator(fake_mode=False, output_stream=output, stage_timeout=1)

            with patch("src.operator.subprocess.Popen", return_value=FakeProcess()), patch(
                "src.operator.threading.Timer",
                ImmediateTimer,
            ):
                exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = op._run_streaming_command(
                    command=["claude"],
                    cwd=paths.run_root,
                    stage=STAGE_01,
                    attempt_no=1,
                    paths=paths,
                    mode="real_start",
                )

            self.assertEqual(exit_code, -1)
            self.assertEqual(stdout_text, "")
            self.assertEqual(stderr_text, "Stage timed out")
            self.assertIsNone(observed_session_id)
            self.assertTrue(stream_meta["timed_out"])
            self.assertEqual(stream_meta["raw_line_count"], 0)


class TestStreamingRendering(unittest.TestCase):
    def test_json_stream_is_rendered_without_raw_json_dump(self) -> None:
        class FakeStdout:
            def __init__(self, lines: list[str]) -> None:
                self._lines = iter(lines)

            def __iter__(self):
                return self

            def __next__(self) -> str:
                return next(self._lines)

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self, lines: list[str]) -> None:
                self.stdout = FakeStdout(lines)
                self.stdin = None

            def terminate(self) -> None:
                return None

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                return None

        class NoopTimer:
            def __init__(self, timeout, fn) -> None:
                self.daemon = False

            def start(self) -> None:
                return None

            def cancel(self) -> None:
                return None

        class RecordingUI:
            def __init__(self) -> None:
                self.events: list[tuple[dict[str, object], dict[str, str]]] = []
                self.raw_lines: list[str] = []

            def show_stream_event(self, payload, tool_names) -> None:
                self.events.append((payload, dict(tool_names)))

            def show_raw_stream_line(self, line: str) -> None:
                self.raw_lines.append(line)

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "json stream goal")
            initialize_memory(paths, "json stream goal")
            output = io.StringIO()
            ui = RecordingUI()
            op = ClaudeOperator(fake_mode=False, output_stream=output, ui=ui)
            lines = [
                '{"type":"assistant","message":{"content":[{"type":"text","text":"hello from claude"}]}}\n'
            ]

            with patch("src.operator.subprocess.Popen", return_value=FakeProcess(lines)), patch(
                "src.operator.threading.Timer",
                NoopTimer,
            ):
                exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = op._run_streaming_command(
                    command=["claude"],
                    cwd=paths.run_root,
                    stage=STAGE_01,
                    attempt_no=1,
                    paths=paths,
                    mode="real_start",
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr_text, "")
            self.assertIsNone(observed_session_id)
            self.assertIn("hello from claude", stdout_text)
            self.assertEqual(stream_meta["malformed_json_count"], 0)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(ui.raw_lines, [])
            self.assertEqual(len(ui.events), 1)

    def test_codex_json_stream_is_rendered_without_raw_json_dump(self) -> None:
        class FakeStdout:
            def __init__(self, lines: list[str]) -> None:
                self._lines = iter(lines)

            def __iter__(self):
                return self

            def __next__(self) -> str:
                return next(self._lines)

            def close(self) -> None:
                return None

        class FakeProcess:
            def __init__(self, lines: list[str]) -> None:
                self.stdout = FakeStdout(lines)
                self.stdin = None

            def terminate(self) -> None:
                return None

            def wait(self, timeout=None) -> int:
                return 0

            def kill(self) -> None:
                return None

        class NoopTimer:
            def __init__(self, timeout, fn) -> None:
                self.daemon = False

            def start(self) -> None:
                return None

            def cancel(self) -> None:
                return None

        class RecordingUI:
            def __init__(self) -> None:
                self.events: list[tuple[dict[str, object], dict[str, str]]] = []
                self.raw_lines: list[str] = []

            def show_stream_event(self, payload, tool_names) -> None:
                self.events.append((payload, dict(tool_names)))

            def show_raw_stream_line(self, line: str) -> None:
                self.raw_lines.append(line)

        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "codex json stream goal")
            initialize_memory(paths, "codex json stream goal")
            output = io.StringIO()
            ui = RecordingUI()
            op = ClaudeOperator(fake_mode=False, output_stream=output, ui=ui)
            lines = [
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"hello from codex"}}\n',
                '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}\n',
            ]

            with patch("src.operator.subprocess.Popen", return_value=FakeProcess(lines)), patch(
                "src.operator.threading.Timer",
                NoopTimer,
            ):
                exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = op._run_streaming_command(
                    command=["codex"],
                    cwd=paths.run_root,
                    stage=STAGE_01,
                    attempt_no=1,
                    paths=paths,
                    mode="real_start",
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr_text, "")
            self.assertEqual(observed_session_id, "thread-1")
            self.assertIn("hello from codex", stdout_text)
            self.assertEqual(stream_meta["malformed_json_count"], 0)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(ui.raw_lines, [])
            self.assertEqual(len(ui.events), 3)


class TestFakeOperatorAttemptContinuity(unittest.TestCase):
    def test_attempt_no_continues_after_resume(self) -> None:
        """Simulate: run stage 01 (attempt 1) -> abort -> resume -> attempt should be 2."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = build_run_paths(Path(tmp) / "run")
            ensure_run_layout(paths)
            write_text(paths.user_input, "test goal")
            initialize_memory(paths, "test goal")

            # First attempt
            attempt_no = read_attempt_count(paths, STAGE_01) + 1
            self.assertEqual(attempt_no, 1)
            write_attempt_count(paths, STAGE_01, attempt_no)

            # Simulate abort and resume
            attempt_no = read_attempt_count(paths, STAGE_01) + 1
            self.assertEqual(attempt_no, 2)
            write_attempt_count(paths, STAGE_01, attempt_no)

            # Another resume
            attempt_no = read_attempt_count(paths, STAGE_01) + 1
            self.assertEqual(attempt_no, 3)


if __name__ == "__main__":
    unittest.main()
