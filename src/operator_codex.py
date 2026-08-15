from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path
from typing import TextIO

from .operator import ClaudeOperator
from .terminal_ui import TerminalUI
from .utils import CODEX_SANDBOX_CHOICES, DEFAULT_CODEX_SANDBOX, RunPaths, read_text


class CodexOperator(ClaudeOperator):
    backend_name = "codex"

    def __init__(
        self,
        command: str = "codex",
        model: str = "default",
        codex_sandbox: str = DEFAULT_CODEX_SANDBOX,
        fake_mode: bool = False,
        output_stream: TextIO | None = None,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        web_search: bool = False,
    ) -> None:
        normalized_sandbox = codex_sandbox.strip() if codex_sandbox.strip() else DEFAULT_CODEX_SANDBOX
        if normalized_sandbox not in CODEX_SANDBOX_CHOICES:
            raise ValueError(
                "Unsupported Codex sandbox mode: "
                f"{codex_sandbox}. Expected one of: {', '.join(sorted(CODEX_SANDBOX_CHOICES))}."
            )
        super().__init__(
            command=command,
            model=model,
            fake_mode=fake_mode,
            output_stream=output_stream if output_stream is not None else sys.stdout,
            ui=ui,
            stage_timeout=stage_timeout,
        )
        self.codex_sandbox = normalized_sandbox
        self.web_search = web_search

    def _prepare_invocation(
        self,
        prompt_path: Path,
        session_id: str,
        *,
        paths: RunPaths,
        resume: bool,
        tools: str | None = None,
    ) -> tuple[list[str], Path, str | None]:
        del tools
        workspace_alias = self._ensure_workspace_alias(paths)
        stdin_text = self._rewrite_prompt_for_alias(prompt_path, paths, workspace_alias)
        command = [
            self.command,
            "-C",
            str(workspace_alias),
        ]
        if self.web_search:
            # Before `exec`, not after: `--search` is a top-level codex flag, and `codex
            # exec --search` exits 2 with "unexpected argument". That mistake cost a full
            # 40-task round -- every run died in 15 seconds, AutoR wrote its fallback
            # report, and the arm scored 2.28 with 31 zeros, a number about argument order
            # rather than about the model.
            #
            # Codex's own `web_search` tool, served by the Responses API rather than by a
            # local subprocess. That distinction is why it is here: `workspace-write` blocks
            # outbound network, so a search running locally cannot reach anything, while
            # asking the provider to search leaves the sandbox exactly as strict.
            command.append("--search")
        command += [
            "exec",
            "--json",
            "--sandbox",
            self.codex_sandbox,
            "--skip-git-repo-check",
        ]
        if self.model and self.model != "default":
            command.extend(["-m", self.model])
        if resume:
            command.extend(["resume", session_id])
        command.append("-")
        return command, Path(tempfile.gettempdir()), stdin_text

    def _ensure_workspace_alias(self, paths: RunPaths) -> Path:
        alias_root = Path(tempfile.gettempdir()) / "autor_codex_workspaces"
        alias_root.mkdir(parents=True, exist_ok=True)

        target = paths.run_root.resolve()
        run_name = "".join(char if char.isascii() and char.isalnum() else "_" for char in paths.run_root.name)
        run_name = run_name.strip("_") or "run"
        digest = hashlib.sha1(str(target).encode("utf-8")).hexdigest()[:12]

        for index in range(10):
            suffix = "" if index == 0 else f"_{index}"
            alias = alias_root / f"{run_name}_{digest}{suffix}"
            if alias.is_symlink():
                try:
                    if alias.resolve() == target:
                        return alias
                except OSError:
                    pass
            if not alias.exists():
                alias.symlink_to(target, target_is_directory=True)
                return alias

        return target

    def _rewrite_prompt_for_alias(self, prompt_path: Path, paths: RunPaths, workspace_alias: Path) -> str:
        prompt = read_text(prompt_path)
        actual_root = str(paths.run_root.resolve())
        alias_root = str(workspace_alias)
        return prompt.replace(actual_root, alias_root)

    def _select_effective_session_id(
        self,
        *,
        requested_session_id: str | None,
        observed_session_id: str | None,
        success: bool,
    ) -> str | None:
        del success
        return observed_session_id or requested_session_id
