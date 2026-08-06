from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .operator import ClaudeOperator
from .review_policy import format_policy_for_prompt, load_policy
from .operator_codex import CodexOperator
from .terminal_ui import TerminalUI
from .utils import (
    RunPaths,
    StageSpec,
    append_jsonl,
    extract_stream_text_fragments,
    read_text,
    truncate_text,
    write_text,
)


DECISION_TO_CHOICE = {
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
    "suggestion_1": "1",
    "suggestion_2": "2",
    "suggestion_3": "3",
    "custom_feedback": "4",
    "approve": "5",
    "abort": "6",
    "approve_and_continue": "5",
    "use_suggestion_1": "1",
    "use_suggestion_2": "2",
    "use_suggestion_3": "3",
    "refine_with_custom_feedback": "4",
}


def _try_load_json(text: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def extract_json_payload(raw_response: str) -> dict[str, Any] | None:
    """Recover a JSON object from whatever a backend actually printed.

    Shared with :mod:`src.router`, which asks a backend for a decision on the same
    terms. Two copies of this would drift on the day one backend starts wrapping
    its output differently, and the copy that was not updated would silently fall
    back to its refusal path instead of reading a decision that was right there.
    """
    candidate = raw_response.strip()
    if not candidate:
        return None

    direct = _try_load_json(candidate)
    if direct is not None:
        return direct

    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, flags=re.DOTALL)
    if fence_match:
        fenced = _try_load_json(fence_match.group(1))
        if fenced is not None:
            return fenced

    brace_match = re.search(r"(\{.*\})", candidate, flags=re.DOTALL)
    if brace_match:
        extracted = _try_load_json(brace_match.group(1))
        if extracted is not None:
            return extracted

    fragments = extract_stream_text_fragments(candidate)
    for fragment in reversed(fragments):
        extracted = _try_load_json(fragment)
        if extracted is not None:
            return extracted

    return None


@dataclass(frozen=True)
class ReviewDecision:
    choice: str
    decision_token: str
    reason: str = ""
    feedback: str = ""
    raw_response: str = ""


class AutomatedReviewer:
    def __init__(
        self,
        backend_name: str,
        *,
        model: str,
        fake_mode: bool = False,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
    ) -> None:
        normalized_backend = backend_name.strip().lower() if backend_name.strip() else "claude"
        if normalized_backend == "codex":
            self._operator = CodexOperator(model=model, fake_mode=fake_mode, ui=ui, stage_timeout=stage_timeout)
        else:
            normalized_backend = "claude"
            self._operator = ClaudeOperator(model=model, fake_mode=fake_mode, ui=ui, stage_timeout=stage_timeout)
        self.backend_name = normalized_backend
        self.model = model
        self.fake_mode = fake_mode
        self.ui = ui or TerminalUI()

    def review_stage(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
    ) -> ReviewDecision:
        if self.fake_mode:
            return ReviewDecision(
                choice="5",
                decision_token="approve",
                reason="Fake reviewer mode auto-approved this stage for smoke validation.",
                raw_response='{"decision":"approve","reason":"fake reviewer"}',
            )

        prompt = self._build_review_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            stage_markdown=stage_markdown,
            suggestions=suggestions,
        )
        exit_code, stdout_text, stderr_text = self.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=prompt,
            label="review",
        )

        if exit_code != 0:
            return ReviewDecision(
                choice="6",
                decision_token="abort",
                reason=(
                    f"Automated reviewer failed with exit code {exit_code}. "
                    "AutoR stopped instead of approving blindly."
                ),
                raw_response=stdout_text or stderr_text,
            )

        return self._parse_decision(stdout_text)

    def run_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        prompt: str,
        label: str,
    ) -> tuple[int, str, str]:
        """Run one reviewer-style prompt through this backend and return its raw output.

        Split out from :meth:`review_stage` so a deliberating panel can reuse the invocation,
        logging and transcript plumbing for a member's own prompt rather than reimplementing
        it, and so every panel member is recorded on the same path a solo reviewer is.
        """
        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_{label}_attempt_{attempt_no:02d}.prompt.md"
        write_text(prompt_path, prompt)

        session_id = str(uuid.uuid4())
        command, invocation_cwd, stdin_text = self._operator._prepare_invocation(  # noqa: SLF001
            prompt_path,
            session_id,
            paths=paths,
            resume=False,
        )
        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": f"{label}_start",
                    "review_backend": self.backend_name,
                    "review_model": self.model,
                    "command": command,
                    "prompt_path": str(prompt_path),
                    "session_id": session_id,
                }
            },
        )
        exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._operator._run_streaming_command(  # noqa: SLF001
            command=command,
            cwd=invocation_cwd,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode=label,
            stdin_text=stdin_text,
        )

        record = {
            "backend": self.backend_name,
            "model": self.model,
            "attempt": attempt_no,
            "stage": stage.slug,
            "label": label,
            "prompt_path": str(prompt_path),
            "exit_code": exit_code,
            "session_id": observed_session_id or session_id,
            "stdout_excerpt": stdout_text[-4000:] if stdout_text else "",
            "stderr_excerpt": stderr_text[-1000:] if stderr_text else "",
            "stream_meta": stream_meta,
        }
        record_path = paths.operator_state_dir / f"{stage.slug}.{label}_attempt_{attempt_no:02d}.json"
        write_text(record_path, json.dumps(record, indent=2, ensure_ascii=False))
        return exit_code, stdout_text, stderr_text

    def parse_decision(self, raw_response: str) -> ReviewDecision:
        """Public alias: panel members parse the same decision grammar."""
        return self._parse_decision(raw_response)

    def _build_review_prompt(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        stage_markdown: str,
        suggestions: list[str],
    ) -> str:
        return (
            f"# AutoR Reviewer Task\n\n"
            f"You are a strict simulated human reviewer for {stage.stage_title}.\n\n"
            "You are not the execution agent. You are the approval gate.\n"
            "Human direction stays in control; execution is delegated to the research operator.\n\n"
            "Review policy:\n"
            "- Approve only if this stage is materially complete for its current milestone.\n"
            "- Prefer refinement if the work looks toy, generic, weakly justified, unverifiable, or missing concrete files.\n"
            "- Do not demand final-paper quality from early stages, but do demand real progress and real artifacts.\n"
            "- Do not edit files. Inspect and judge.\n"
            "- If one of the built-in suggestions already matches the right next move, select it.\n"
            "- Otherwise choose custom_feedback and write concrete reviewer instructions.\n"
            "- Use abort only if the run is blocked badly enough that automatic continuation would be irresponsible.\n\n"
            "Return JSON only, with no prose outside the JSON object:\n"
            '{"decision":"approve|suggestion_1|suggestion_2|suggestion_3|custom_feedback|abort","feedback":"","reason":""}\n\n'
            "Rules for JSON fields:\n"
            "- `decision` is required.\n"
            "- `feedback` must be non-empty when `decision` is `custom_feedback`.\n"
            "- `reason` should be concise and specific.\n\n"
            "# Run Context\n\n"
            f"- run root: `{paths.run_root.resolve()}`\n"
            f"- current attempt: {attempt_no}\n"
            f"- review backend: {self.backend_name}\n"
            f"- review model: {self.model}\n"
            f"- run config: `{paths.run_config.resolve()}`\n"
            f"- run manifest: `{paths.run_manifest.resolve()}`\n"
            f"- artifact index: `{paths.artifact_index.resolve()}`\n"
            f"- experiment manifest: `{paths.experiment_manifest.resolve()}`\n"
            f"- stage draft under review: `{paths.stage_tmp_file(stage).resolve()}`\n"
            f"- approved stage path: `{paths.stage_file(stage).resolve()}`\n\n"
            + self._standing_rules_block(paths)
            + "# Suggested Refinements\n\n"
            f"1. {suggestions[0]}\n"
            f"2. {suggestions[1]}\n"
            f"3. {suggestions[2]}\n\n"
            "# Original Goal\n\n"
            f"{self._read_excerpt(paths.user_input, max_chars=3000)}\n\n"
            "# Approved Memory\n\n"
            f"{self._read_excerpt(paths.memory, max_chars=12000)}\n\n"
            "# Current Stage Summary\n\n"
            f"{truncate_text(stage_markdown, max_chars=16000)}\n\n"
            "# Run Manifest Excerpt\n\n"
            f"{self._read_excerpt(paths.run_manifest, max_chars=6000)}\n\n"
            "# Artifact Index Excerpt\n\n"
            f"{self._read_excerpt(paths.artifact_index, max_chars=6000)}\n\n"
            "# Experiment Manifest Excerpt\n\n"
            f"{self._read_excerpt(paths.experiment_manifest, max_chars=6000)}\n\n"
            "# Recent Log Excerpt\n\n"
            f"{self._read_excerpt(paths.logs, max_chars=5000, tail=True)}\n"
        )

    def _standing_rules_block(self, paths: RunPaths) -> str:
        """Render the rules earlier reviews produced, so this review inherits them.

        This is what makes the gate strictly harder as a run proceeds: a correction demanded
        once is checked on every stage after it.
        """
        rendered = format_policy_for_prompt(load_policy(paths))
        if not rendered:
            return ""
        return "# Standing Review Rules (learned earlier in this run)\n\n" + rendered + "\n\n"

    def _read_excerpt(self, path: Path, *, max_chars: int, tail: bool = False) -> str:
        if not path.exists():
            return "(missing)"
        text = read_text(path).strip()
        if not text:
            return "(empty)"
        if len(text) <= max_chars:
            return text
        if tail:
            return "..." + text[-(max_chars - 3):].lstrip()
        return truncate_text(text, max_chars=max_chars)

    def _parse_decision(self, raw_response: str) -> ReviewDecision:
        payload = self._extract_json_payload(raw_response)
        if payload is None:
            return ReviewDecision(
                choice="6",
                decision_token="abort",
                reason="Automated reviewer did not return valid JSON. AutoR stopped instead of approving blindly.",
                raw_response=raw_response,
            )

        token = self._normalize_decision_token(payload.get("decision"))
        choice = DECISION_TO_CHOICE.get(token)
        if choice is None:
            return ReviewDecision(
                choice="6",
                decision_token=token or "abort",
                reason="Automated reviewer returned an unsupported decision token.",
                raw_response=raw_response,
            )

        feedback = str(payload.get("feedback") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if choice == "4" and not feedback:
            feedback = reason or "The stage is not ready. Revise it with concrete, artifact-backed improvements before continuing."

        return ReviewDecision(
            choice=choice,
            decision_token=token,
            reason=reason,
            feedback=feedback,
            raw_response=raw_response,
        )

    def _extract_json_payload(self, raw_response: str) -> dict[str, Any] | None:
        return extract_json_payload(raw_response)

    def _try_load_json(self, text: str) -> dict[str, Any] | None:
        return _try_load_json(text)

    def _normalize_decision_token(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
