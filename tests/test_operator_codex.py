from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from src.operator_codex import CodexOperator
from src.utils import build_run_paths, ensure_run_layout, initialize_memory, write_text


class CodexOperatorTests(unittest.TestCase):
    def _build_paths(self) -> object:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        write_text(paths.user_input, "codex operator test")
        initialize_memory(paths, "codex operator test")
        return paths

    def test_prepare_invocation_uses_ascii_workspace_alias_and_stdin_prompt(self) -> None:
        paths = self._build_paths()
        prompt_path = paths.prompt_cache_dir / "01_literature_survey_attempt_01.prompt.md"
        write_text(prompt_path, f"Write output under {paths.run_root.resolve()}/stages.\n")
        operator = CodexOperator(fake_mode=False, output_stream=io.StringIO())

        command, cwd, stdin_text = operator._prepare_invocation(
            prompt_path,
            "unused-session",
            paths=paths,
            resume=False,
        )

        self.assertEqual(cwd, Path(tempfile.gettempdir()))
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[1], "-C")
        alias_path = Path(command[2])
        self.assertTrue(alias_path.exists())
        self.assertIn("exec", command)
        self.assertIn("--json", command)
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)
        self.assertNotIn("--full-auto", command)
        self.assertEqual(command[-1], "-")
        assert stdin_text is not None
        self.assertIn(str(alias_path), stdin_text)
        self.assertNotIn(str(paths.run_root.resolve()), stdin_text)

    def test_prepare_invocation_uses_resume_subcommand(self) -> None:
        paths = self._build_paths()
        prompt_path = paths.prompt_cache_dir / "01_literature_survey_attempt_02.prompt.md"
        write_text(prompt_path, "Continue.\n")
        operator = CodexOperator(fake_mode=False, output_stream=io.StringIO())

        command, _, _ = operator._prepare_invocation(
            prompt_path,
            "thread-123",
            paths=paths,
            resume=True,
        )

        self.assertIn("resume", command)
        self.assertIn("thread-123", command)
        self.assertLess(command.index("--sandbox"), command.index("resume"))
        self.assertLess(command.index("--skip-git-repo-check"), command.index("resume"))
        self.assertLess(command.index("--json"), command.index("resume"))
        self.assertEqual(command[-2:], ["thread-123", "-"])

    def test_prepare_invocation_uses_configured_sandbox(self) -> None:
        paths = self._build_paths()
        prompt_path = paths.prompt_cache_dir / "01_literature_survey_attempt_01.prompt.md"
        write_text(prompt_path, "Run remote experiment.\n")
        operator = CodexOperator(
            codex_sandbox="danger-full-access",
            fake_mode=False,
            output_stream=io.StringIO(),
        )

        command, _, _ = operator._prepare_invocation(
            prompt_path,
            "unused-session",
            paths=paths,
            resume=False,
        )

        self.assertEqual(command[command.index("--sandbox") + 1], "danger-full-access")

    def test_invalid_sandbox_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CodexOperator(codex_sandbox="network-magic", output_stream=io.StringIO())


if __name__ == "__main__":
    unittest.main()
