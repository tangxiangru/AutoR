from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .operator import ClaudeOperator
from .obligations import format_for_review_prompt, load_ledger
from .review_policy import format_policy_for_prompt, load_policy
from .operator_codex import CodexOperator
from .stage_comments import parse_comments
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
    # A reviewer asked to choose between "custom_feedback" and "abort" writes "revise". Three
    # of five benchmark runs died on exactly that: the word was not in this map, so an ordinary
    # request for changes was read as an unsupported token and ended the run. AutoR's own
    # unreadable-verdict fallback emits `decision_token="revise"`, so the vocabulary did not
    # even agree with itself. Only unambiguous synonyms are added -- "reject" is deliberately
    # absent, because it reads as both "send back" and "stop".
    "revise": "4",
    "refine": "4",
    "revision": "4",
    "request_changes": "4",
    "changes_requested": "4",
    "revise_with_feedback": "4",
}


#: Prefix that marks "the reviewer answered but we could not read it", as distinct from
#: "the reviewer refused". The two are told apart by `AutomatedReviewer._is_unreadable`.
UNREADABLE_REASON = "Automated reviewer did not return valid JSON."
UNSUPPORTED_REASON = "Automated reviewer returned an unsupported decision token."
CRASHED_REASON = "Automated reviewer failed to run."


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
    #: What a later stage still owes, attached when approving. This is where most of a
    #: review's value lives: an approval used to discard everything the reviewer noticed.
    carry_forward: list[Any] = field(default_factory=list)
    #: Inherited obligation ids this stage actually discharged.
    discharged: list[str] = field(default_factory=list)
    #: Comments anchored to quoted passages of the draft. When present, a refusal is local:
    #: the revision is asked to change these spans and leave the rest alone, and the next
    #: draft is diffed against them.
    comments: list[Any] = field(default_factory=list)


class AutomatedReviewer:
    def __init__(
        self,
        backend_name: str,
        *,
        model: str,
        fake_mode: bool = False,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        unattended: bool = False,
    ) -> None:
        # Unattended runs cannot ask a human what the reviewer meant, and aborting a
        # multi-hour run because a verdict was unreadable throws away work the reviewer
        # may well have been about to approve. See _unreadable_verdict.
        self.unattended = unattended
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
            # A crashed backend is not a refusal to approve. Attended, aborting is right --
            # a human is there. Unattended it forfeits the task: Information_001 lost a run
            # holding four approved stages to `exit code -1`, a signal kill with nothing
            # wrong with the research. The backend is deliberately *not* re-asked, because a
            # process that died is not one attempt away from a usable verdict; the stage is
            # sent back instead, bounded by its own attempt budget.
            if not self.unattended:
                return ReviewDecision(
                    choice="6",
                    decision_token="abort",
                    reason=(
                        f"Automated reviewer failed with exit code {exit_code}. "
                        "AutoR stopped instead of approving blindly."
                    ),
                    raw_response=stdout_text or stderr_text,
                )
            return ReviewDecision(
                choice="4",
                decision_token="revise",
                reason=(
                    f"{CRASHED_REASON} It exited {exit_code}. Unattended, so the stage was "
                    "sent back for another pass rather than approved or aborted."
                ),
                feedback=(
                    "The automated reviewer could not be run, so this stage was not "
                    "approved. Re-examine the draft against the stage contract and the "
                    "artifacts it claims, strengthen whatever is weakest, and restate the "
                    "summary."
                ),
                raw_response=stdout_text or stderr_text,
            )

        return self.parse_with_retry(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            raw_response=stdout_text,
            markdown=stage_markdown,
        )

    def parse_with_retry(
        self,
        *,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        raw_response: str,
        markdown: str = "",
        label: str = "review_verdict",
        on_unreadable: "Callable[[str], ReviewDecision] | None" = None,
    ) -> ReviewDecision:
        """Read a verdict, re-ask once if it cannot be read, then fall back.

        Split out of :meth:`review_stage` so a deliberating panel's chair goes through
        the same path. It did not: the chair's reply was parsed with a bare
        `parse_decision`, so one unparseable synthesis cancelled the whole run —
        `run_status: cancelled`, Stage 01 stuck in review — where the solo reviewer on
        the identical reply retries and continues.

        ``on_unreadable`` lets a caller supply a better fallback than this one. The
        panel has an obvious one: the seats already stated their objections, so their
        dissent is a more informative answer than a generic re-run request.
        """
        decision = self._parse_decision(raw_response, markdown=markdown)
        if not self._is_unreadable(decision):
            return decision

        # The reviewer answered, we just could not read it. Ask once more for the verdict
        # alone: a reviewer that has already inspected the artifacts and then narrated its
        # findings in prose is one re-ask away from a usable answer, and that is far
        # cheaper than discarding the stage.
        retry = self.run_prompt(
            paths=paths,
            stage=stage,
            attempt_no=attempt_no,
            prompt=self._build_verdict_only_prompt(stage=stage, previous=raw_response),
            label=label,
        )
        if retry[0] == 0:
            retried = self._parse_decision(retry[1], markdown=markdown)
            if not self._is_unreadable(retried):
                return retried

        if on_unreadable is not None and self.unattended:
            return on_unreadable(raw_response)
        return self._unreadable_verdict(raw_response)

    @staticmethod
    def _is_unreadable(decision: ReviewDecision) -> bool:
        """Whether the reviewer failed to answer, as distinct from answering "abort".

        Matched on the reason, not the token: an unsupported token keeps whatever word the
        model wrote, so a token check misses it -- and it is still a verdict nobody can act
        on. Both kinds get the re-ask and, unattended, the send-back.
        """
        return decision.reason.startswith((UNREADABLE_REASON, UNSUPPORTED_REASON))

    def _unreadable_verdict(self, raw_response: str) -> ReviewDecision:
        """What to do when the reviewer's answer cannot be read, twice.

        Attended: abort, unchanged -- a human is there, and guessing at a verdict is the
        one thing the approval gate exists to prevent.

        Unattended: send the stage back for another pass instead. An unreadable verdict is
        not a refusal to approve, it is a failure to read the answer, and the two deserve
        different outcomes. Revising is bounded by the stage's own attempt budget, so this
        cannot loop; aborting, by contrast, discards the entire run at whatever stage the
        parse happened to fail -- in practice Stage 01, hours of real work gone over a
        formatting slip.
        """
        if not self.unattended:
            return ReviewDecision(
                choice="6",
                decision_token="abort",
                reason=UNREADABLE_REASON + " AutoR stopped instead of approving blindly.",
                raw_response=raw_response,
            )
        return ReviewDecision(
            choice="4",
            decision_token="revise",
            reason=(
                UNREADABLE_REASON
                + " Unattended, so the stage was sent back for another pass rather than "
                "approved or aborted."
            ),
            feedback=(
                "The automated reviewer's verdict could not be parsed, so this stage was "
                "not approved. Re-examine the draft against the stage contract and the "
                "artifacts it claims, fix whatever is weakest, and restate the summary."
            ),
            raw_response=raw_response,
        )

    def _build_verdict_only_prompt(self, *, stage: StageSpec, previous: str) -> str:
        return (
            f"You were asked to review {stage.stage_title} and your reply could not be "
            "parsed as a decision.\n\n"
            "Do not inspect anything further. Do not call any tool. Reply with a single "
            "JSON object and nothing else, on one line:\n\n"
            '{"decision": "approve" | "revise" | "abort", "reason": "<one sentence>"}\n\n'
            "Use the same judgement you already reached. Your previous reply ended:\n\n"
            + previous.strip()[-2000:]
        )

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

    def parse_decision(self, raw_response: str, markdown: str = "") -> ReviewDecision:
        """Public alias: panel members parse the same decision grammar.

        *markdown* is the draft under review, needed to anchor quoted comments to it.
        """
        return self._parse_decision(raw_response, markdown=markdown)

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
            "## Preferred: comment on specific passages\n\n"
            "If your objections are to particular passages rather than to the stage as a whole, "
            "return them as `comments`, each quoting the exact text you object to. A quoted "
            "objection sends back only that passage; a bare `feedback` string re-runs the whole "
            "stage and rerolls work nobody objected to.\n\n"
            "Quote verbatim from the draft, long enough to be unambiguous (at least a full "
            "clause). Do not quote text that is not there — a comment whose quote cannot be "
            "found is recorded as unanchored and reaches nobody.\n\n"
            "Return JSON only, with no prose outside the JSON object:\n"
            '{"decision":"approve|suggestion_1|suggestion_2|suggestion_3|custom_feedback|abort",'
            '"feedback":"","reason":"",'
            '"carry_forward":[{"obligation":"","target_stage":""}],"discharged":[]}\n\n'
            "Rules for JSON fields:\n"
            "- `decision` is required.\n"
            "- `carry_forward` is how you approve without letting go. When you approve but "
            "something still needs doing, record it here instead of only mentioning it in "
            "`reason`: each entry is injected into the prompt of the stage it targets and "
            "into that stage's review, so it will actually be checked. `target_stage` is a "
            "stage slug or number and may be omitted to mean 'any later stage'. Use it for "
            "real debts, not for wishes.\n"
            "- `discharged` lists the ids of inherited obligations this stage genuinely met. "
            "Discharge on work present in this stage, never on a promise or a restatement.\n"
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
            + self._obligations_block(paths, stage)
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

    def _obligations_block(self, paths: RunPaths, stage: StageSpec) -> str:
        """Ask this review whether the debts it inherited were actually paid."""
        rendered = format_for_review_prompt(load_ledger(paths), stage)
        if not rendered:
            return ""
        return "# Inherited Obligations\n\n" + rendered + "\n\n"

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

    def _parse_decision(self, raw_response: str, markdown: str = "") -> ReviewDecision:
        payload = self._extract_json_payload(raw_response)
        if payload is None:
            return ReviewDecision(
                choice="6",
                decision_token="abort",
                reason=UNREADABLE_REASON + " AutoR stopped instead of approving blindly.",
                raw_response=raw_response,
            )

        token = self._normalize_decision_token(payload.get("decision"))
        choice = DECISION_TO_CHOICE.get(token)
        if choice is None:
            return ReviewDecision(
                choice="6",
                decision_token=token or "abort",
                reason=UNSUPPORTED_REASON,
                raw_response=raw_response,
            )

        feedback = str(payload.get("feedback") or "").strip()
        reason = str(payload.get("reason") or "").strip()
        if choice == "4" and not feedback:
            feedback = reason or "The stage is not ready. Revise it with concrete, artifact-backed improvements before continuing."

        carry_forward = payload.get("carry_forward")
        discharged = payload.get("discharged")
        comments = parse_comments(payload, author=self.backend_name, markdown=markdown) if markdown else []
        if choice == "5":
            # An approval does not send anything back, so a comment attached to one would be an
            # instruction nobody will ever act on.
            comments = []
        return ReviewDecision(
            choice=choice,
            decision_token=token,
            reason=reason,
            feedback=feedback,
            raw_response=raw_response,
            carry_forward=list(carry_forward) if isinstance(carry_forward, list) else [],
            discharged=[str(item) for item in discharged] if isinstance(discharged, list) else [],
            comments=comments,
        )

    def _extract_json_payload(self, raw_response: str) -> dict[str, Any] | None:
        return extract_json_payload(raw_response)

    def _try_load_json(self, text: str) -> dict[str, Any] | None:
        return _try_load_json(text)

    def _normalize_decision_token(self, value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
