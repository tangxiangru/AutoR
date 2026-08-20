from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Sequence, TextIO

from .call_cost import CallCost, RECORD_FIELD, cost_from_stream_meta, is_result_event
from .terminal_ui import TerminalUI
from .utils import (
    DEFAULT_REFINEMENT_SUGGESTIONS,
    FIXED_STAGE_OPTIONS,
    OperatorResult,
    RunPaths,
    StageSpec,
    append_jsonl,
    approved_stage_summaries,
    extract_stream_text_fragments,
    read_text,
    task_statement,
    relative_to_run,
    write_text,
)


def _head(text: str, max_chars: int) -> str:
    """The opening of *text*, saying how much it dropped. ``(empty)`` for nothing."""

    body = (text or "").strip()
    if not body:
        return "(empty)"
    if len(body) <= max_chars:
        return body
    return body[:max_chars].rstrip() + f"\n\n[... {len(body) - max_chars} character(s) dropped from the end]"


def _tail(text: str, max_chars: int) -> str:
    """The end of *text*, saying how much it dropped. ``(empty)`` for nothing."""

    body = (text or "").strip()
    if not body:
        return "(empty)"
    if len(body) <= max_chars:
        return body
    return f"[... {len(body) - max_chars} character(s) dropped from the start ...]\n\n" + body[-max_chars:].lstrip()


#: What a repair may be told about the attempt it is repairing.
#:
#: The repair prompt is the narrowest task in the system -- "overwrite this one markdown
#: file, do not browse, do not continue the workflow" -- and it was handed the largest
#: prompt. Measured over 2,166 archived repair prompts, it runs to a median of 354 KB
#: against the attempt prompt's 156 KB: **1.84x its own attempt at the median, 6.55x at
#: p90**, and a third of all repairs exceed 500 KB where 0.14% of attempt prompts do.
#:
#: Two blocks are all of it. The whole original prompt (median 147 KB, max 3.17 MB) and
#: the whole original stdout (median 93 KB, p90 907 KB). The objects the task actually
#: rewrites are small -- the draft is 17 KB at the median and the promoted file 10 bytes
#: -- and stderr is 8 bytes, so those three stay whole and a ceiling on them would be a
#: mechanism with nothing to do.
#:
#: **Nothing measurable is lost.** Repair success over 2,157 recorded outcomes is flat
#: across two orders of magnitude of prompt size: 98.1% below 150 KB, 100% at 150-300 KB,
#: 98.6%, 98.2%, 98.9% above. The 645 repairs that already got a small prompt are the
#: control group, and they succeed at the same rate as the ones given a megabyte.
#:
#: The directions differ because the blocks differ. The prompt is kept from the head:
#: `# Stage Instructions` is its first section and is what a rewrite needs, while the
#: accumulated channels and memory at the end are what it does not. 80,000 is above that
#: section's own p90 of 78.6 KB, so a typical repair still sees the whole instruction set.
#: The stdout is kept from the *tail*: what matters is what the attempt ended up doing,
#: which is also why `_write_attempt_state` records `stdout_text[-2000:]` rather than the
#: first 2,000 characters. 40,000 is twenty times that excerpt.
REPAIR_PROMPT_EXCERPT_CHARS = 80_000
REPAIR_STDOUT_EXCERPT_CHARS = 40_000


def _assistant_text_blocks(payload: Any) -> list[str]:
    """The text the assistant itself wrote in one stream event, and nothing else.

    `extract_stream_text_fragments` harvests every string under `text`, `content`,
    `message`, `delta`, `summary` or `result`, wherever it sits. That is the right rule for
    a caller that parses a delimited section out of the whole text and the wrong one for a
    caller that keeps the reply, because a `tool_result` block is text under `content` too:
    the output of a shell command the model ran lands in the reply beside the reply.

    Measured on the sixty-task written-answer trial of 2026-08-19 -- that benchmark's adapter
    has since been removed from this repository, the measurement has not -- where its `direct`
    arm is the caller that keeps the reply. Six of twenty-eight of its answers began with a
    directory listing the model had run for itself, the whole answer still present underneath
    -- one of them 62,491 characters ending in a complete chemistry conclusion. The same shape
    appeared in three of sixty answers on the previous trial and was scored normally, so the
    behaviour is not new; what is new is that a content-refusal clause now reads the top of
    the file and refuses the run. The answer was never the problem. The capture was.

    So this reads only `assistant` events, and inside them only `text` blocks. Tool calls,
    tool results, system events and the terminal result restatement are all somebody else's
    text. It is additive: `stdout_text` is composed exactly as before, so stages and the
    sibling benchmark's report path see no change at all.
    """
    if not isinstance(payload, dict) or payload.get("type") != "assistant":
        return []
    message = payload.get("message")
    if not isinstance(message, dict):
        return []
    blocks: list[str] = []
    for block in message.get("content") or []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            blocks.append(text.strip())
    return blocks


#: Process-wide default for :attr:`ClaudeOperator.isolate_auto_memory`.
#:
#: An isolation that reaches one seat is not an isolation. Threading the flag through the
#: front end's own operator left **every reviewer unisolated**, because
#: `AutomatedReviewer` builds a second `ClaudeOperator` of its own and `ReviewPanel` builds
#: one per role. Measured on the topology ablation on 2026-08-19, 9.5 hours in: of 4,513
#: recorded CLI invocations, 2,752 carried the flag and 1,761 did not, and the 1,761 were
#: *exactly* the reviewer calls -- every `review_start` and `review_verdict_start`, none of
#: the stage calls. Their `init` events reported the shared store; the flagged ones had no
#: `memory_paths` key. All 80 workspaces of both arms reached the store, and the traffic
#: was one-directional: the adaptive arm wrote 10 times, the linear arm 0.
#:
#: So the default lives here rather than in a parameter each seat has to remember to
#: forward. A front end that is running a measurement sets it once with
#: :func:`isolate_auto_memory_by_default`; every operator built anywhere in that process
#: inherits it, including ones constructed inside a reviewer, a panel role or the validity
#: review. The per-instance argument still wins where it is passed explicitly.
_AUTO_MEMORY_ISOLATED_BY_DEFAULT = False


def isolate_auto_memory_by_default(value: bool = True) -> None:
    """Cut every Claude Code seat built after this call off from the memory store.

    For a benchmark front end, called once before anything is constructed. Not for
    AutoR's ordinary use: a researcher's own project wants notes carried between
    sessions, and only a measurement needs every run to start from the same state.
    """
    global _AUTO_MEMORY_ISOLATED_BY_DEFAULT
    _AUTO_MEMORY_ISOLATED_BY_DEFAULT = bool(value)


def auto_memory_isolated_by_default() -> bool:
    """What a seat built with no explicit choice will do. Readable so a test can pin it."""
    return _AUTO_MEMORY_ISOLATED_BY_DEFAULT


class ClaudeOperator:
    backend_name = "claude"

    def __init__(
        self,
        command: str = "claude",
        model: str = "sonnet",
        fake_mode: bool = False,
        output_stream: TextIO = sys.stdout,
        ui: TerminalUI | None = None,
        stage_timeout: int = 14400,
        web_search_mcp: bool = False,
        disallowed_tools: Sequence[str] | None = None,
        isolate_auto_memory: bool | None = None,
    ) -> None:
        self.command = command
        self.model = model
        self.fake_mode = fake_mode
        self.output_stream = output_stream
        self.ui = ui or TerminalUI(output_stream=output_stream)
        self.stage_timeout = stage_timeout
        # Whether to hand the agent a real `web_search` tool over MCP. Claude Code on
        # Vertex has the built-in WebSearch disabled, and a tool in the tool list is both
        # more reliably reached for than a prompt paragraph and legible in the trace as a
        # named call rather than an opaque shell command.
        self.web_search_mcp = web_search_mcp
        # Built-in tools this operator's stages may not call. Empty on every existing
        # path, and the default has to stay empty: withholding a tool the stage contract
        # assumes is available fails the stage, not the tool. `src.web_search`'s
        # `disallowed_tools_for` is the only thing that fills it today, for a run whose
        # protocol says it must not browse.
        self.disallowed_tools = tuple(disallowed_tools or ())
        # Whether to cut the agent off from Claude Code's cross-session memory store.
        #
        # The store is keyed on an ancestor of the run's working directory, not on the run:
        # measured on this box, a probe in `/rmeng_data/robtang/memprobe` and a stage whose
        # cwd was `/rmeng_data/robtang/fs-trial-skills/workspaces/fs024_.../.autor/<ts>`
        # both reported the same `memory_paths.auto`. Every run under one benchmark's
        # results directory therefore shares one store, and its `MEMORY.md` index is loaded
        # into each agent's context at session start.
        #
        # That is a channel between runs of a benchmark, and it is used. It was measured on
        # the sixty-task trial of 2026-08-19, whose adapter has since been removed from this
        # tree; the store it measured is Claude Code's and is still there. The two most-read
        # files in a 1,456-file store were notes an earlier run had written about how that
        # harness chose the answer it published -- 92 and 56 reads -- and in the chemistry block
        # the read was the *first* tool call of the run, in both arms, before the agent
        # looked at the problem. It is also asymmetric: 32 of 37 pipeline runs reached the
        # store against 8 of 37 direct ones, so it does not cancel out of a paired
        # comparison.
        #
        # Default off, and deliberately. AutoR's ordinary use is a researcher's own project
        # where carrying notes between sessions is the feature working as intended; only a
        # measurement wants each run to start from the same state as every other. A benchmark
        # front end opts in; the front end that used to is gone, and `rcb_agent.py` opts in
        # here instead, so the flag has a caller again.
        #
        # Nothing records which way it was set, and that is a gap rather than a decision.
        # The removed front end read the flag back off the operator that ran the stages --
        # not off the flags that built it, because `CodexOperator` subclasses
        # `ClaudeOperator` and inherits the attribute, so a plain read asserts "the store
        # was reachable" of a run that never started Claude Code -- and wrote it into that
        # run's metadata. The front end that opts in next owes its metadata the same field,
        # so a run can say whether the channel was open rather than leaving a reader assume.
        self.isolate_auto_memory = (
            auto_memory_isolated_by_default()
            if isolate_auto_memory is None
            else bool(isolate_auto_memory)
        )

    def run_stage(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        if self.fake_mode:
            return self._run_fake(stage, prompt, paths, attempt_no, continue_session=continue_session)
        return self._run_real(stage, prompt, paths, attempt_no, continue_session=continue_session)

    def _run_real(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        if shutil.which(self.command) is None:
            raise FileNotFoundError(
                f"{self._agent_label()} CLI not found: {self.command}. Install it or use --fake-operator."
            )

        prompt_path = paths.prompt_cache_dir / f"{stage.slug}_attempt_{attempt_no:02d}.prompt.md"
        write_text(prompt_path, prompt)
        session_id = self._resolve_stage_session_id(paths, stage, continue_session)
        command, invocation_cwd, stdin_text = self._prepare_invocation(
            prompt_path,
            session_id,
            paths=paths,
            resume=continue_session,
        )
        active_command = command
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "starting",
                "mode": "resume" if continue_session else "start",
                "session_id": session_id,
                "prompt_path": str(prompt_path),
                "command": command,
                "started_at": self._now(),
            },
        )

        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "real_continue" if continue_session else "real_start",
                    "command": command,
                    "prompt_path": str(prompt_path),
                    "session_id": session_id,
                }
            },
        )

        exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
            command=command,
            cwd=invocation_cwd,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode="real_continue" if continue_session else "real_start",
            stdin_text=stdin_text,
        )
        # Accumulated rather than read off the last `stream_meta`, because the resume
        # fallback below rebinds that name. A resume that failed and was retried from a
        # fresh session made two backend calls and the run paid for both; charging only the
        # second would lose whatever the failed resume had already spent before it broke.
        call_cost = cost_from_stream_meta(stream_meta)
        stage_file = paths.stage_tmp_file(stage)

        if (
            continue_session
            and exit_code != 0
            and self._looks_like_resume_failure(stdout_text, stderr_text)
        ):
            fallback_session_id = str(uuid.uuid4())
            # A different file, carrying one sentence the original cannot: the earlier
            # turns are gone.
            #
            # Whether a stage's conversation is in context is a fact about the
            # invocation, and this is the only place that knows it -- `build_continuation_prompt`
            # is written before anyone asks the CLI to resume, and it used to assert the
            # continuation outright. Replaying it here handed a brand-new, empty session
            # a document telling it that it was mid-conversation. The prompt now speaks
            # about the work and this speaks about the session, so neither has to guess
            # at the other's half.
            #
            # Written beside the original rather than over it: `prompt_cache/` is the
            # audit trail of what actually ran, and overwriting the file would leave the
            # resumed attempt and its restart indistinguishable in it.
            fallback_prompt_path = prompt_path.with_name(
                prompt_path.name.replace(".prompt.md", "_restart.prompt.md")
            )
            write_text(
                fallback_prompt_path,
                read_text(prompt_path)
                + "\n\n# The Earlier Turns Of This Conversation Are Gone\n\n"
                "This stage's session could not be resumed, so this is a new one and "
                "nothing before this message is in context. Everything the sections above "
                "point at is still on disk and still correct; read what you need rather "
                "than relying on having seen it.\n",
            )
            fallback_command, fallback_cwd, fallback_stdin_text = self._prepare_invocation(
                fallback_prompt_path,
                fallback_session_id,
                paths=paths,
                resume=False,
            )
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": "real_continue_fallback_start",
                        "previous_session_id": session_id,
                        "fallback_session_id": fallback_session_id,
                        "command": fallback_command,
                        "prompt_path": str(fallback_prompt_path),
                    }
                },
            )
            self._mark_session_broken(paths, stage, session_id, reason="resume_failure")
            exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
                command=fallback_command,
                cwd=fallback_cwd,
                stage=stage,
                attempt_no=attempt_no,
                paths=paths,
                mode="real_continue_fallback_start",
                stdin_text=fallback_stdin_text,
            )
            call_cost = call_cost + cost_from_stream_meta(stream_meta)
            session_id = fallback_session_id
            active_command = fallback_command

        success = exit_code == 0 and stage_file.exists()
        effective_session_id = self._select_effective_session_id(
            requested_session_id=session_id,
            observed_session_id=observed_session_id,
            success=success,
        )
        self._persist_stage_session_id(paths, stage, effective_session_id)
        self._update_session_state(
            paths,
            stage,
            effective_session_id,
            {
                "broken": not success and continue_session,
                "last_exit_code": exit_code,
                "last_mode": "resume" if continue_session else "start",
                "updated_at": self._now(),
            },
        )
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "completed" if success else "failed",
                "mode": "resume" if continue_session else "start",
                "session_id": effective_session_id,
                "prompt_path": str(prompt_path),
                "command": active_command,
                "exit_code": exit_code,
                "stdout_excerpt": stdout_text[-2000:] if stdout_text else "",
                "stderr_excerpt": stderr_text[-1000:] if stderr_text else "",
                "stream_meta": stream_meta,
                RECORD_FIELD: call_cost.to_dict(),
                "finished_at": self._now(),
            },
        )

        return OperatorResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            stage_file_path=stage_file,
            session_id=effective_session_id,
            call_cost=call_cost,
        )

    def repair_stage_summary(
        self,
        stage: StageSpec,
        original_prompt: str,
        original_result: OperatorResult,
        paths: RunPaths,
        attempt_no: int,
    ) -> OperatorResult:
        if self.fake_mode:
            return self._run_fake(stage, original_prompt, paths, attempt_no, continue_session=False)

        stage_file = paths.stage_tmp_file(stage)
        current_draft_text = read_text(stage_file) if stage_file.exists() else "(missing)"
        current_final_path = paths.stage_file(stage)
        current_final_text = read_text(current_final_path) if current_final_path.exists() else "(missing)"
        recovery_prompt = f"""
You are performing failure recovery for {stage.stage_title}.

The previous attempt either failed before producing a valid stage summary file, or produced a file with missing required sections.
Your only task now is to overwrite the stage summary file at:
{stage_file}

Rules:
- Do not browse the web.
- Do not use WebSearch or WebFetch.
- Do not try to continue the full research workflow.
- Use only the information already available in the prompt below and the run directory if needed.
- If the earlier attempt failed or produced incomplete evidence, state that clearly in the summary.
- You must still produce a valid markdown file in the required format.
- Treat `{stage_file}` as the final deliverable, not as a scratchpad.
- Do not write half-finished, placeholder, outline-only, pending, or in-progress content to `{stage_file}`.
- If you need scratch notes while repairing, write them somewhere else in the run directory, not to `{stage_file}`.
- Do not describe, summarize, or comment on the repair prompt itself.
- Do not ask the user what to do next.
- Do not say that the stage "already completed successfully" unless the written stage file itself contains the full required structure.
- You must directly write the repaired markdown file, then stop.

Required markdown structure:
# Stage X: <name>
## Objective
## What I Did
## Key Results
## Files Produced
## Decision Ledger
## Suggestions for Refinement
1. {DEFAULT_REFINEMENT_SUGGESTIONS[0]}
2. {DEFAULT_REFINEMENT_SUGGESTIONS[1]}
3. {DEFAULT_REFINEMENT_SUGGESTIONS[2]}
## Your Options
{chr(10).join(FIXED_STAGE_OPTIONS)}

Required completion behavior:
1. Read the current stage file if it exists.
2. Overwrite it with a complete markdown document in the exact structure above.
3. Ensure `## Your Options` is present and matches the fixed six lines exactly.
4. Ensure there is no `[In progress]`, `[Pending]`, `[TODO]`, `[TBD]`, or similar unfinished marker anywhere in the file.
5. After writing, respond only with a short confirmation that you rewrote the file.

Current draft stage file contents:
{current_draft_text}

Current promoted stage file contents:
{current_final_text}

Original prompt:
{_head(original_prompt, REPAIR_PROMPT_EXCERPT_CHARS)}

Original stdout:
{_tail(original_result.stdout, REPAIR_STDOUT_EXCERPT_CHARS)}

Original stderr:
{original_result.stderr or "(empty)"}
""".strip()

        recovery_prompt_path = paths.prompt_cache_dir / f"{stage.slug}_attempt_{attempt_no:02d}_repair.prompt.md"
        write_text(recovery_prompt_path, recovery_prompt)
        session_id = self._resolve_stage_session_id(paths, stage, continue_session=True, allow_create=False)
        if session_id:
            command, invocation_cwd, stdin_text = self._prepare_invocation(
                recovery_prompt_path,
                session_id,
                paths=paths,
                resume=True,
                tools="Skill,Write,Read,Glob,Grep",
            )
        else:
            session_id = self._resolve_stage_session_id(paths, stage, continue_session=False)
            command, invocation_cwd, stdin_text = self._prepare_invocation(
                recovery_prompt_path,
                session_id,
                paths=paths,
                resume=False,
                tools="Skill,Write,Read,Glob,Grep",
            )

        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "repair",
                    "command": command,
                    "prompt_path": str(recovery_prompt_path),
                    "session_id": session_id,
                }
            },
        )

        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "repair_starting",
                "mode": "repair",
                "session_id": session_id,
                "prompt_path": str(recovery_prompt_path),
                "command": command,
                "started_at": self._now(),
            },
        )

        exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
            command=command,
            cwd=invocation_cwd,
            stage=stage,
            attempt_no=attempt_no,
            paths=paths,
            mode="repair",
            stdin_text=stdin_text,
        )
        # Same accumulation as `_run_real`, for the same reason: the repair path has its
        # own resume fallback and rebinds `stream_meta` when it takes it.
        call_cost = cost_from_stream_meta(stream_meta)
        if (
            session_id
            and exit_code != 0
            and self._looks_like_resume_failure(stdout_text, stderr_text)
        ):
            fallback_session_id = str(uuid.uuid4())
            fallback_command, fallback_cwd, fallback_stdin_text = self._prepare_invocation(
                recovery_prompt_path,
                fallback_session_id,
                paths=paths,
                resume=False,
                tools="Skill,Write,Read,Glob,Grep",
            )
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": "repair_fallback_start",
                        "previous_session_id": session_id,
                        "fallback_session_id": fallback_session_id,
                        "command": fallback_command,
                        "prompt_path": str(recovery_prompt_path),
                    }
                },
            )
            self._mark_session_broken(paths, stage, session_id, reason="repair_resume_failure")
            exit_code, stdout_text, stderr_text, observed_session_id, stream_meta = self._run_streaming_command(
                command=fallback_command,
                cwd=fallback_cwd,
                stage=stage,
                attempt_no=attempt_no,
                paths=paths,
                mode="repair_fallback_start",
                stdin_text=fallback_stdin_text,
            )
            call_cost = call_cost + cost_from_stream_meta(stream_meta)
            session_id = fallback_session_id
            command = fallback_command

        success = exit_code == 0 and stage_file.exists()
        effective_session_id = self._select_effective_session_id(
            requested_session_id=session_id,
            observed_session_id=observed_session_id,
            success=success,
        )
        self._persist_stage_session_id(paths, stage, effective_session_id)
        self._update_session_state(
            paths,
            stage,
            effective_session_id,
            {
                "broken": not success,
                "last_exit_code": exit_code,
                "last_mode": "repair",
                "updated_at": self._now(),
            },
        )
        self._write_attempt_state(
            paths,
            stage,
            attempt_no,
            {
                "status": "repair_completed" if exit_code == 0 and stage_file.exists() else "repair_failed",
                "mode": "repair",
                "session_id": effective_session_id,
                "prompt_path": str(recovery_prompt_path),
                "command": command,
                "exit_code": exit_code,
                "stdout_excerpt": stdout_text[-2000:] if stdout_text else "",
                "stderr_excerpt": stderr_text[-1000:] if stderr_text else "",
                "stream_meta": stream_meta,
                RECORD_FIELD: call_cost.to_dict(),
                "finished_at": self._now(),
            },
        )

        return OperatorResult(
            success=success,
            exit_code=exit_code,
            stdout=stdout_text,
            stderr=stderr_text,
            stage_file_path=stage_file,
            session_id=effective_session_id,
            call_cost=call_cost,
        )

    def _run_streaming_command(
        self,
        command: list[str],
        cwd: Path,
        stage: StageSpec,
        attempt_no: int,
        paths: RunPaths,
        mode: str,
        stdin_text: str | None = None,
    ) -> tuple[int, str, str, str | None, dict[str, object]]:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdin=subprocess.PIPE if stdin_text is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        if process.stdout is None:
            raise RuntimeError(f"Failed to capture {self._agent_label()} output stream.")
        stdin_thread: threading.Thread | None = None
        if stdin_text is not None and process.stdin is not None:
            def _feed_stdin() -> None:
                try:
                    process.stdin.write(stdin_text)
                except BrokenPipeError:
                    pass
                finally:
                    try:
                        process.stdin.close()
                    except BrokenPipeError:
                        pass

            stdin_thread = threading.Thread(target=_feed_stdin, daemon=True)
            stdin_thread.start()

        extracted_fragments: list[str] = []
        # The terminal result event's text, kept apart from the turn's own. See
        # `_compose_stdout_text` for why it is a fallback rather than more content.
        terminal_fragments: list[str] = []
        raw_lines: list[str] = []
        non_json_lines: list[str] = []
        # The assistant's own words, kept apart from everything else in the stream. A caller
        # that keeps a *reply* wants these; a caller that parses a delimited section out of
        # the whole text does not care and still gets `stdout_text` unchanged. Collected here
        # rather than reconstructed from `logs_raw.jsonl` afterwards, so the two cannot drift.
        assistant_blocks: list[str] = []
        ended_with_newline = True
        observed_session_id: str | None = None
        tool_names: dict[str, str] = {}
        malformed_json_count = 0
        # The backend's own account of what this invocation cost, accumulated as the stream
        # arrives rather than reconstructed from `logs_raw.jsonl` afterwards. Summed over
        # result events because `total_cost_usd` is a per-call charge; see
        # `src/call_cost.py` for the measurement that settles that, and for why the count
        # of result events is not the count of invocations.
        spend = CallCost()
        timed_out = threading.Event()
        start_time = time.monotonic()

        def _on_timeout() -> None:
            timed_out.set()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        timer = threading.Timer(self.stage_timeout, _on_timeout)
        timer.daemon = True
        timer.start()

        try:
            for raw_line in process.stdout:
                if timed_out.is_set():
                    break

                ended_with_newline = raw_line.endswith("\n")
                line = raw_line.rstrip("\n")
                raw_lines.append(line)
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError:
                    malformed_json_count += 1
                    append_jsonl(
                        paths.logs_raw,
                        {
                            "_meta": {
                                "stage": stage.slug,
                                "attempt": attempt_no,
                                "mode": mode,
                                "non_json_output": stripped,
                            }
                        },
                    )
                    non_json_lines.append(stripped)
                    self.ui.show_raw_stream_line(stripped)
                    continue

                append_jsonl(paths.logs_raw, payload)
                if is_result_event(payload):
                    spend = spend + CallCost.from_result_event(payload)
                if observed_session_id is None:
                    observed_session_id = self._extract_session_id(payload)
                if is_result_event(payload):
                    terminal_fragments.extend(extract_stream_text_fragments(payload))
                else:
                    extracted_fragments.extend(extract_stream_text_fragments(payload))
                assistant_blocks.extend(_assistant_text_blocks(payload))
                self.ui.show_stream_event(payload, tool_names)
        except KeyboardInterrupt:
            elapsed = time.monotonic() - start_time
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": mode,
                        "event": "keyboard_interrupt",
                        "elapsed_seconds": round(elapsed, 1),
                    }
                },
            )
            raise
        finally:
            timer.cancel()
            if stdin_thread is not None:
                stdin_thread.join(timeout=1)
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            process.stdout.close()

        if timed_out.is_set():
            elapsed = time.monotonic() - start_time
            append_jsonl(
                paths.logs_raw,
                {
                    "_meta": {
                        "stage": stage.slug,
                        "attempt": attempt_no,
                        "mode": mode,
                        "event": "stage_timeout",
                        "timeout_seconds": self.stage_timeout,
                        "elapsed_seconds": round(elapsed, 1),
                    }
                },
            )
            stdout_text = self._compose_stdout_text(
                extracted_fragments=extracted_fragments,
                terminal_fragments=terminal_fragments,
                non_json_lines=non_json_lines,
                raw_lines=raw_lines,
            )
            # The cost rides out on the timeout path too. A stage that ran for four hours
            # and was killed is the invocation whose bill matters most, and an earlier
            # shape of this that only reported spend on the clean return would have
            # recorded exactly nothing for it.
            return -1, stdout_text, "Stage timed out", observed_session_id, {
                "raw_line_count": len(raw_lines),
                "non_json_line_count": len(non_json_lines),
                "malformed_json_count": malformed_json_count,
                "observed_session_id": observed_session_id,
                "assistant_text": "\n\n".join(assistant_blocks).strip(),
                "timed_out": True,
                RECORD_FIELD: spend.to_dict(),
            }

        exit_code = process.wait()
        if raw_lines and not ended_with_newline:
            self.output_stream.write("\n")
            self.output_stream.flush()

        stdout_text = self._compose_stdout_text(
            extracted_fragments=extracted_fragments,
            terminal_fragments=terminal_fragments,
            non_json_lines=non_json_lines,
            raw_lines=raw_lines,
        )
        return exit_code, stdout_text, "", observed_session_id, {
            "raw_line_count": len(raw_lines),
            "non_json_line_count": len(non_json_lines),
            "malformed_json_count": malformed_json_count,
            "observed_session_id": observed_session_id,
            "assistant_text": "\n\n".join(assistant_blocks).strip(),
            RECORD_FIELD: spend.to_dict(),
        }

    def _compose_stdout_text(
        self,
        extracted_fragments: list[str],
        terminal_fragments: list[str],
        non_json_lines: list[str],
        raw_lines: list[str],
    ) -> str:
        """Everything the turn said, once.

        The terminal result event restates the whole reply, so harvesting it alongside the
        assistant text hands every caller that keeps the raw stream two copies. Stage-shaped
        callers never noticed: they parse a delimited section out of the text and a second
        copy of it changes nothing. The callers that keep the whole reply did notice, and
        nobody was watching -- measured on the sixty-task trial of 2026-08-19, whose adapter
        has since been removed from this repository: **fifty-five of the control arm's sixty
        answers carried the answer twice** (forty of them an exact byte-for-byte halving)
        against none of the pipeline arm's, because only the control arm keeps the reply.
        That asymmetry sat inside a paired comparison, which is reason enough to repair it
        -- and note that it is the *asymmetry* that is the reason, not a price: re-judging
        twelve of them once de-duplicated moved the score by +0.033 points on average
        (sd 0.633, seven unchanged), so the doubling bought the arm that had it nothing
        measurable. An earlier revision of this docstring said -0.307 over eleven,
        which is not in the array it cited; the +0.033 over twelve above is the re-derived
        figure, and the results write-up that carried the correction went with the adapter.

        So the result event is a fallback, not a contribution. It is the reply only when
        nothing else captured one -- a turn that emitted no assistant text at all, which is
        the case the harvest was presumably added for.
        """
        fragment_text = "\n".join(fragment for fragment in extracted_fragments if fragment).strip()
        if not fragment_text:
            fragment_text = "\n".join(f for f in terminal_fragments if f).strip()
        non_json_text = "\n".join(line for line in non_json_lines if line).strip()
        raw_text = "\n".join(line for line in raw_lines if line).strip()

        parts: list[str] = []
        if fragment_text:
            parts.append(fragment_text)
        if non_json_text:
            parts.append(non_json_text)
        if not parts and raw_text:
            parts.append(raw_text)

        return "\n\n".join(parts).strip()

    # A 1-page PDF with no content stream. Small enough to inline, and a real
    # PDF rather than a renamed text file, so anything that opens the manuscript
    # during a fake run gets a file it can actually parse.
    _MINIMAL_PDF = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n"
        b"%%EOF\n"
    )

    @staticmethod
    def _minimal_png(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (120, 120, 120)) -> bytes:
        """A real, decodable PNG. The report viewer is handed an image, not a stub."""
        import struct
        import zlib

        raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

        def chunk(tag: bytes, data: bytes) -> bytes:
            body = tag + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )

    @staticmethod
    def _answer_validity_findings(paths: RunPaths, stage: StageSpec) -> None:
        """Answer the previous stage's validity findings, honestly.

        Fake mode's single finding — one run of a two-row synthetic split — is
        entirely correct and the stub cannot fix it, so the honest disposition
        is `accepted_limitation`. A stub that rebutted a true objection would
        model the failure the reviewer exists to catch.
        """
        from .validity_review import (
            load_findings,
            reviewed_stage_for,
            validity_response_path,
        )

        reviewed = reviewed_stage_for(stage)
        if reviewed is None:
            return
        findings = load_findings(paths, reviewed)
        if not findings:
            return
        write_text(
            validity_response_path(paths, reviewed),
            json.dumps(
                {
                    "responses": [
                        {
                            "id": item.identifier,
                            "status": "accepted_limitation",
                            "explanation": (
                                "fake-operator mode cannot address this objection, and the "
                                "objection is correct: nothing in this run was measured. "
                                "Recorded as a standing limitation rather than rebutted."
                            ),
                            "evidence": "",
                        }
                        for item in findings
                    ]
                },
                indent=2,
            )
            + "\n",
        )

    def _write_fake_stage_artifacts(self, stage: StageSpec, paths: RunPaths) -> list[Path]:
        """Produce the artifacts ``validate_stage_artifacts`` requires at this stage.

        Fake mode exists to exercise the workflow end to end without a model.
        That only works if it clears the same artifact gates a real run clears —
        otherwise every stage from 03 on fails validation, burns its retry
        budget and gets auto-skipped, and the "local validation" run validates
        nothing past stage 02.

        The set is cumulative and rewritten on every stage from 03 onward,
        because several gates additionally require their artifacts to have been
        touched during the current stage's execution.
        """
        from .utils import selected_output_format, selected_venue_key

        if stage.number < 3:
            return []

        written: list[Path] = []

        def _write(path: Path, body: str) -> None:
            write_text(path, body)
            written.append(path)

        def _write_json(path: Path, payload: object) -> None:
            _write(path, json.dumps(payload, indent=2) + "\n")

        # Stage 03+: the experimental protocol, declared before results exist.
        _write_json(
            paths.experimental_protocol,
            {
                "declared_at": self._now(),
                "primary_metric": "placeholder accuracy on a two-row synthetic split",
                "planned_seeds": 1,
                "baselines": [
                    {
                        "name": "placeholder baseline",
                        "why_competent": (
                            "Stand-in declared by fake-operator mode. Not a real comparison."
                        ),
                        "tuning_budget": "none; fake mode runs no tuning",
                    }
                ],
            },
        )

        # Stage 03+: which figures the report will carry, chosen before any
        # result exists. Written once and then left alone: the plan has no
        # freshness requirement, and rewriting it every stage would erase the
        # `declared_at` and `digest` the manager stamps on Stage 03 approval —
        # the very evidence that the choice predates the results.
        #
        # Exactly one entry, naming the figure this stub actually publishes and
        # references at Stage 07, so the fixture exercises the published path
        # rather than the dropped one. One entry rather than five on purpose:
        # MAX_REPORT_FIGURES is a ceiling, and a fixture that filled it would
        # teach the ceiling as a target to everyone who reads this file.
        if not paths.report_plan.exists():
            _write_json(
                paths.report_plan,
                {
                    "figures": [
                        {
                            "slot": 1,
                            "filename": "fake_comparison.png",
                            "supports": ["H1"],
                            "shows": (
                                "Placeholder produced by fake-operator mode. In a real run "
                                "this slot would show the placeholder score (dimensionless) "
                                "for the baseline and treatment conditions. Nothing here was "
                                "measured."
                            ),
                            "if_supported": (
                                "the treatment bar would stand above the baseline bar; fake "
                                "mode measures nothing, so it does not"
                            ),
                            "if_refuted": (
                                "the two bars would be indistinguishable, which is what a "
                                "fabricated placeholder actually shows"
                            ),
                            "source_artifact": "results/fake_results.json",
                            "dropped_because": "",
                        }
                    ],
                    "headline_numbers": [
                        {
                            "quantity": (
                                "placeholder score, treatment minus baseline (not a "
                                "measurement)"
                            ),
                            "unit": "dimensionless",
                            "source_artifact": "results/fake_results.json",
                        }
                    ],
                    "task_outputs": [
                        {
                            "stated": (
                                "whatever the task description asked for — fake-operator mode "
                                "does not read it"
                            ),
                            "covered_by": "not_attempted",
                            "why_not": (
                                "fake-operator mode exercises the workflow and measures "
                                "nothing, so it answers no deliverable the task named."
                            ),
                        }
                    ],
                },
            )

        # Stage 03+: machine-readable data under workspace/data.
        _write_json(
            paths.data_dir / "fake_dataset.json",
            {
                "dataset_id": "fake-synthetic-001",
                "note": "Placeholder produced by fake-operator mode. Not real data.",
                "rows": [
                    {"id": 1, "condition": "baseline", "score": 0.61},
                    {"id": 2, "condition": "treatment", "score": 0.74},
                ],
            },
        )
        _write(
            paths.data_dir / "fake_dataset.csv",
            "id,condition,score\n1,baseline,0.61\n2,treatment,0.74\n",
        )

        if stage.number >= 5:
            # Stage 05+: result artifacts. experiment_manifest.json itself is
            # written by the manager, and it excludes itself from the result
            # set, so a separate result file is required.
            _write_json(
                paths.results_dir / "fake_results.json",
                {
                    "metric": "accuracy",
                    "baseline": 0.61,
                    "treatment": 0.74,
                    "delta": 0.13,
                    "n_seeds": 2,
                    "note": "Placeholder produced by fake-operator mode. Not a real result.",
                },
            )
            _write(
                paths.code_dir / "fake_experiment.py",
                '"""Placeholder experiment script written by fake-operator mode."""\n'
                "\n"
                "def main() -> None:\n"
                '    print("fake experiment")\n'
                "\n"
                "\n"
                'if __name__ == "__main__":\n'
                "    main()\n",
            )

        if stage.number >= 6:
            # Stage 06+: a verdict on every preregistered hypothesis. The fake
            # verdict is deliberately `refuted` — the placeholder result (0.61
            # vs 0.74, a 13-point gap on two rows with one seed) does not clear
            # the decision rule the fake Stage 02 wrote, and a stub that always
            # confirms its own hypothesis would model exactly the failure the
            # preregistration exists to catch.
            from .preregistration import load_preregistration

            prereg = load_preregistration(paths)
            if prereg is not None:
                _write_json(
                    paths.hypothesis_outcomes,
                    {
                        "generated_at": self._now(),
                        "preregistration_digest": prereg.digest,
                        "outcomes": [
                            {
                                "id": identifier,
                                "verdict": "refuted",
                                "rationale": (
                                    "Placeholder adjudication from fake-operator mode. The stub "
                                    "result does not clear this hypothesis's decision rule, and "
                                    "no real measurement was taken."
                                ),
                                "evidence": ["results/fake_results.json"],
                                "statistics": {
                                    "n_seeds": 1,
                                    "dispersion": 0.0,
                                    "dispersion_type": "none",
                                    "single_run_justification": (
                                        "fake-operator mode writes a fixed placeholder rather "
                                        "than measuring anything, so repeating it would change "
                                        "nothing. This is not a claim about a real procedure."
                                    ),
                                },
                            }
                            for identifier in prereg.adjudicated_ids
                        ],
                        "exploratory_findings": [],
                    },
                )

            # Stage 06+: close the round. The fake hypothesis came out refuted,
            # so the only honest way to converge is to declare the refutation
            # the result. A stub that claimed convergence on a supported
            # hypothesis it never had would model the failure this gate exists
            # to catch.
            _write_json(
                paths.round_decision,
                {
                    "decision": "converged",
                    "rationale": (
                        "fake-operator mode measures nothing, so no further round would "
                        "produce a different outcome. Closing the round rather than "
                        "spending budget on a stub."
                    ),
                    "what_we_learned": (
                        "Nothing about the research question. The run exercised the workflow "
                        "end to end and the preregistered hypothesis was not supported by the "
                        "placeholder result."
                    ),
                    "what_changes_next": "",
                    "negative_result": True,
                },
            )

            # Stage 06+: answer whatever the adversarial reviewer raised against
            # the previous stage. The fake response is `accepted_limitation`,
            # because the fake finding (a single run of a two-row split) is
            # entirely correct and the stub cannot fix it.
            self._answer_validity_findings(paths, stage)

            # Stage 06+: figures. SVG keeps this a text write with no encoder.
            _write(
                paths.figures_dir / "fig1_fake_comparison.svg",
                '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="120">'
                '<rect x="20" y="50" width="40" height="50" fill="#888"/>'
                '<rect x="90" y="30" width="40" height="70" fill="#444"/>'
                '<text x="20" y="115" font-size="10">fake baseline vs treatment</text>'
                "</svg>\n",
            )

        if stage.number >= 7:
            self._answer_validity_findings(paths, stage)

            # Every claim traces to evidence. With the fake hypothesis refuted,
            # the only honest status left is exploratory — which is the point:
            # the stub cannot manufacture a confirmatory claim.
            _write_json(
                paths.claim_provenance,
                {
                    "claims": [
                        {
                            "claim": (
                                "Placeholder finding produced by fake-operator mode; no "
                                "measurement supports it."
                            ),
                            "status": "exploratory",
                            "hypothesis_id": "",
                            "evidence": ["results/fake_results.json"],
                        }
                    ]
                },
            )

        if stage.number >= 7 and selected_output_format(paths) == "markdown":
            # The markdown deliverable is gated on a report of real length with
            # a figure that actually resolves, so the placeholder has to be a
            # real report shape rather than a stub. It must also avoid the
            # bracketed placeholder markers the gate rejects, hence plain prose
            # saying what it is.
            image_path = paths.report_images_dir / "fake_comparison.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            image_path.write_bytes(self._minimal_png())
            written.append(image_path)

            filler = (
                "This paragraph exists so the report clears the minimum length gate. "
                "It describes, in the shape a real report would use, a two-condition "
                "comparison between a baseline and a treatment on a synthetic dataset "
                "of two rows, measured once, with no statistical test applied. "
            )
            _write(
                paths.report_file,
                "# Placeholder Research Report (fake-operator mode)\n\n"
                "This report was generated by AutoR's fake operator to exercise the "
                "Stage 07 gates without calling a model. Nothing in it is a research "
                "result and none of its numbers were measured.\n\n"
                "## Abstract\n\n"
                f"{filler}\n\n"
                "## Methodology\n\n"
                f"{filler * 3}\n\n"
                "## Results\n\n"
                f"{filler * 3}\n\n"
                "![Fake baseline versus treatment scores.](images/fake_comparison.png)\n\n"
                "## Discussion\n\n"
                f"{filler * 3}\n\n"
                "## Limitations\n\n"
                "The entire report is fabricated scaffolding. Replace fake mode with a "
                "real operator before drawing any conclusion from this file.\n",
            )
            _write_json(
                paths.artifacts_dir / "report_review.json",
                {
                    "overall_status": "placeholder",
                    "report_available": True,
                    "referenced_image_count": 1,
                    "issue_counts": {"critical": 0, "major": 0, "minor": 0},
                    "issues": [],
                    "priority_fixes": ["Replace this placeholder with a real report review."],
                },
            )
        if stage.number >= 7:
            # A coverage record the real gate accepts, saying plainly that it is fake. It
            # quotes the task statement verbatim rather than inventing a requirement,
            # because that is exactly the rule a real run is held to.
            #
            # Outside the markdown branch, like the gate that reads it. Both had the same
            # coupling and for the same reason -- the record arrived while markdown was
            # the only format anyone ran -- so a latex run wrote no coverage record and
            # was never asked for one. Moving only the gate turned the latex end-to-end
            # pipeline red at Stage 07, which is `test_no_stage_needed_a_retry` doing the
            # job its comment claims: noticing an artifact gate fake mode was never
            # taught to satisfy.
            from .deliverables import COVERAGE_FILENAME, demanding_sentences

            _statement = task_statement(read_text(paths.user_input))
            _fake_reason = (
                "fake-operator mode does not do research; nothing was actually derived."
            )
            _entries = [
                {"task_quote": sentence, "addressed": False, "reason": _fake_reason}
                for sentence in demanding_sentences(_statement)
            ] or [
                {
                    "task_quote": " ".join(_statement.split())[:120],
                    "addressed": False,
                    "reason": _fake_reason,
                }
            ]
            _write_json(paths.artifacts_dir / COVERAGE_FILENAME, {"deliverables": _entries})

            venue = selected_venue_key(paths)
            _write(
                paths.writing_dir / "main.tex",
                f"% AutoR venue: {venue}\n"
                "\\documentclass{article}\n"
                "\\begin{document}\n"
                "\\title{Placeholder Manuscript (fake-operator mode)}\n"
                "\\maketitle\n"
                "\\input{sections/introduction}\n"
                "\\bibliographystyle{plain}\n"
                "\\bibliography{references}\n"
                "\\end{document}\n",
            )
            _write(
                paths.writing_dir / "sections" / "introduction.tex",
                "\\section{Introduction}\n"
                "This manuscript was produced by fake-operator mode to exercise the "
                "Stage 07 writing gates. It contains no research content~\\cite{fake2026}.\n",
            )
            _write(
                paths.writing_dir / "references.bib",
                "@article{fake2026,\n"
                "  title  = {A Placeholder Reference},\n"
                "  author = {Fake Operator},\n"
                "  year   = {2026},\n"
                "  journal= {Journal of Workflow Validation}\n"
                "}\n",
            )
            pdf_path = paths.writing_dir / "main.pdf"
            pdf_path.parent.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(self._MINIMAL_PDF)
            written.append(pdf_path)
            _write(
                paths.artifacts_dir / "build_log.txt",
                "fake-operator mode did not run a LaTeX toolchain.\n"
                "This log exists so the Stage 07 build-metadata gate has something to read.\n",
            )
            _write_json(
                paths.artifacts_dir / "citation_verification.json",
                {
                    "overall_status": "placeholder",
                    "total_citations": 1,
                    "claim_coverage": [
                        {
                            "claim": "Placeholder claim produced by fake-operator mode.",
                            "citation_keys": ["fake2026"],
                            "source_ids": ["S1"],
                        }
                    ],
                },
            )
            _write_json(
                paths.artifacts_dir / "self_review.json",
                {
                    "overall_status": "placeholder",
                    "note": "fake-operator mode does not perform a real self review.",
                    "findings": [],
                },
            )
            _write_json(
                paths.artifacts_dir / "layout_review.json",
                {
                    "overall_status": "placeholder",
                    "pdf_available": True,
                    "build_log_checked": True,
                    "issue_counts": {"critical": 0, "major": 0, "minor": 0},
                    "issues": [],
                    "priority_fixes": ["Replace this placeholder with a real layout review."],
                },
            )

        if stage.number >= 8:
            _write_json(
                paths.reviews_dir / "readiness_review.json",
                {
                    "overall_status": "placeholder",
                    "venue": selected_venue_key(paths),
                    "checklist": [
                        {"item": "Manuscript compiles", "status": "not_verified"},
                        {"item": "Artifacts released", "status": "not_verified"},
                    ],
                    "note": "fake-operator mode does not perform a real readiness review.",
                },
            )

        return written

    def _run_fake(
        self,
        stage: StageSpec,
        prompt: str,
        paths: RunPaths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        session_id = self._resolve_stage_session_id(paths, stage, continue_session=continue_session)
        self._persist_stage_session_id(paths, stage, session_id)
        approved_memory = self._extract_approved_memory_from_prompt(prompt) or read_text(paths.memory)
        previous_summaries = approved_stage_summaries(approved_memory)
        agent_label = self._agent_label()
        note_path = paths.notes_dir / f"{stage.slug}_fake_operator_note.md"
        stage_tmp_path = paths.stage_tmp_file(stage)
        user_goal = read_text(paths.user_input).strip()
        write_text(
            note_path,
            (
                f"# Fake Operator Note: {stage.stage_title}\n\n"
                "This file was produced by fake-operator mode to validate the workflow, "
                "directory layout, stage summary handling, and approval loop without "
                f"calling {agent_label}."
            ),
        )

        if stage.number == 1 and "smoke test" in user_goal.lower():
            intro_path = paths.notes_dir / "autor_intro.md"
            sources_path = paths.literature_dir / "sources.json"
            claims_path = paths.literature_dir / "claims.json"
            write_text(
                intro_path,
                (
                    "# AutoR Overview\n\n"
                    "AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner.\n\n"
                    "It executes a fixed 8-stage pipeline:\n"
                    "1. Literature survey\n"
                    "2. Hypothesis generation\n"
                    "3. Study design\n"
                    "4. Implementation\n"
                    "5. Experimentation\n"
                    "6. Analysis\n"
                    "7. Writing\n"
                    "8. Dissemination\n\n"
                    "Every stage writes artifacts into an isolated run directory and must be explicitly approved by the user.\n"
                ),
            )
            write_text(
                sources_path,
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "S1",
                                "title": "AutoR product overview",
                                "path": relative_to_run(intro_path, paths.run_root),
                            }
                        ]
                    },
                    indent=2,
                ),
            )
            write_text(
                claims_path,
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "statement": "AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner.",
                                "source_ids": ["S1"],
                            }
                        ]
                    },
                    indent=2,
                ),
            )
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                "Introduce AutoR during a fake-mode smoke test while demonstrating the terminal UI, "
                "stage summary contract, and approval loop.\n\n"
                "## What I Did\n"
                f"- Entered fake-operator mode so the full terminal workflow could be demonstrated without calling {agent_label}.\n"
                "- Generated a short markdown introduction to AutoR for recording and smoke-test purposes.\n"
                f"- Wrote overview material to `{relative_to_run(intro_path, paths.run_root)}` and preserved the fake operator note at `{relative_to_run(note_path, paths.run_root)}`.\n"
                f"- Produced a valid stage summary draft at `{relative_to_run(stage_tmp_path, paths.run_root)}`.\n\n"
                "## Key Results\n"
                "- AutoR is a terminal-first, file-based, human-in-the-loop research workflow runner.\n"
                "- The workflow is fixed into 8 stages: literature, hypothesis, design, implementation, experimentation, analysis, writing, and dissemination.\n"
                "- Every run is isolated under `runs/<run_id>/`, with prompts, logs, stage summaries, and workspace artifacts written to disk.\n"
                "- The UI smoke test confirms the current terminal interface, menu interaction, and stage-summary rendering path are working.\n"
                "- This output is a product demo and workflow intro, not a real research result.\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(intro_path, paths.run_root)}`\n"
                f"- `{relative_to_run(sources_path, paths.run_root)}`\n"
                f"- `{relative_to_run(claims_path, paths.run_root)}`\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Decision Ledger\n"
                "- **Open Questions**: Which real research goal should be used for the first live run?\n"
                "- **Locked Decisions**: Keep the smoke test in fake mode so the demo stays deterministic.\n"
                "- **Assumptions**: The current terminal UI and approval loop are the main things being demonstrated.\n"
                "- **Rejected Alternatives**: Treating the smoke test as a real research result.\n\n"
                "## Suggestions for Refinement\n"
                f"1. Switch from fake mode to the real {agent_label} operator and record a live stage execution.\n"
                "2. Tune the terminal theme, colors, and screen layout for recording aesthetics.\n"
                "3. Expand the intro note with a concrete example run and artifact tour before moving on.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        elif stage.slug == "01_literature_survey":
            sources_path = paths.literature_dir / "sources.json"
            claims_path = paths.literature_dir / "claims.json"
            write_text(
                sources_path,
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "S1",
                                "title": "Foundational long-context prompting study",
                                "path": relative_to_run(note_path, paths.run_root),
                            },
                            {
                                "source_id": "S2",
                                "title": "Retrieval-augmented reasoning baseline",
                                "path": relative_to_run(note_path, paths.run_root),
                            },
                        ]
                    },
                    indent=2,
                ),
            )
            write_text(
                claims_path,
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "statement": "Long-context prompting degrades when relevant evidence is diffuse.",
                                "source_ids": ["S1"],
                            },
                            {
                                "claim_id": "CL2",
                                "statement": "Retrieval is a common mitigation strategy in recent reasoning systems.",
                                "source_ids": ["S1", "S2"],
                            },
                        ]
                    },
                    indent=2,
                ),
            )
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                "Validate the literature-survey workflow using a minimal claim-to-source ledger.\n\n"
                "## What I Did\n"
                f"- Executed fake-operator mode instead of invoking {agent_label}.\n"
                f"- Wrote supporting source and claim ledgers to `{relative_to_run(sources_path, paths.run_root)}` and `{relative_to_run(claims_path, paths.run_root)}`.\n"
                f"- Preserved the fake operator note at `{relative_to_run(note_path, paths.run_root)}`.\n"
                "- Produced a valid Stage 01 summary with traceable survey artifacts.\n\n"
                "## Key Results\n"
                "- The fake literature run now produces a structured source catalog and claim ledger.\n"
                "- Downstream stages can inherit grounded survey claims instead of only prose.\n"
                "- This remains workflow scaffolding, not a real literature review.\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(sources_path, paths.run_root)}`\n"
                f"- `{relative_to_run(claims_path, paths.run_root)}`\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Decision Ledger\n"
                "- **Open Questions**: Which real papers should replace the fake source catalog?\n"
                "- **Locked Decisions**: Stage 01 should emit traceable survey evidence, not only prose.\n"
                "- **Assumptions**: The fake ledgers are placeholders for workflow validation only.\n"
                "- **Rejected Alternatives**: Approving a literature stage with no claim-to-source trace.\n\n"
                "## Suggestions for Refinement\n"
                "1. Replace the fake source ledger with real paper metadata before continuing.\n"
                "2. Expand the claim ledger so it captures conflicting evidence, not only supporting evidence.\n"
                "3. Add dataset and benchmark notes to the literature directory alongside the ledgers.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        elif stage.slug == "02_hypothesis_generation":
            hypotheses_path = paths.notes_dir / "hypotheses.md"
            write_text(
                hypotheses_path,
                (
                    "# Typed Hypotheses\n\n"
                    "## Theoretical Propositions\n"
                    "- T1: Retrieval addresses context fragmentation.\n\n"
                    "## Empirical Hypotheses\n"
                    "- H1: Retrieval will improve long-context accuracy.\n\n"
                    "## Paper Claims\n"
                    "- C1: Retrieval is a practical long-context fix.\n"
                ),
            )
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                "Validate the Stage 02 workflow using typed propositions, empirical hypotheses, and provisional paper claims.\n\n"
                "## What I Did\n"
                f"- Executed fake-operator mode instead of invoking {agent_label}.\n"
                f"- Wrote supporting hypothesis notes to `{relative_to_run(hypotheses_path, paths.run_root)}`.\n"
                f"- Preserved the fake operator note at `{relative_to_run(note_path, paths.run_root)}`.\n"
                "- Produced a typed Stage 02 summary so downstream stages can consume structured hypothesis context.\n\n"
                "## Key Results\n\n"
                "### Theoretical Propositions\n"
                "- **T1**: Retrieval reduces context fragmentation in long-context prompting.\n"
                "  - Derived from: Prior long-context failure patterns summarized in Stage 01.\n\n"
                "### Empirical Hypotheses\n"
                "- **H1**: Adding retrieval will improve long-context task accuracy by at least 8 points.\n"
                "  - Depends on: T1\n"
                "  - Decision rule: supported if retrieval-on beats retrieval-off by more than 8 "
                "accuracy points on the held-out split; refuted if the gap is 8 points or less.\n"
                "  - Verification: Compare retrieval-on vs retrieval-off on the benchmark suite.\n\n"
                "### Paper Claims (Provisional)\n"
                "- **C1**: Retrieval is a practical way to stabilize long-context reasoning.\n"
                "  - Status: proposed\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(hypotheses_path, paths.run_root)}`\n"
                f"- `{relative_to_run(paths.hypothesis_manifest, paths.run_root)}`\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Decision Ledger\n"
                "- **Open Questions**: How large should the retrieval gain threshold be?\n"
                "- **Locked Decisions**: Keep typed claims separated for downstream stages.\n"
                "- **Assumptions**: Stage 03 onward will treat empirical hypotheses as the main test targets.\n"
                "- **Rejected Alternatives**: Mixing theory, hypotheses, and paper narrative into one prose block.\n\n"
                "## Suggestions for Refinement\n"
                "1. Add a second empirical hypothesis about latency trade-offs.\n"
                "2. Tighten the effect-size threshold with more prior evidence.\n"
                "3. Add a weaker fallback paper claim in case the main hypothesis is only partially supported.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        else:
            artifact_paths = self._write_fake_stage_artifacts(stage, paths)
            artifact_lines = "".join(
                f"- `{relative_to_run(path, paths.run_root)}`\n" for path in artifact_paths
            )
            artifact_did = (
                f"- Wrote {len(artifact_paths)} placeholder artifacts so this stage clears the same "
                "artifact gates a real run has to clear.\n"
                if artifact_paths
                else ""
            )
            stage_markdown = (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                f"Validate the workflow path for {stage.display_name} and confirm that the "
                "manager, operator, and filesystem contracts are functioning.\n\n"
                "## What I Did\n"
                f"- Executed fake-operator mode instead of invoking {agent_label}.\n"
                f"- Created a placeholder artifact at `{relative_to_run(note_path, paths.run_root)}`.\n"
                + artifact_did
                + f"- Simulated a complete stage attempt for `{stage.slug}`.\n\n"
                "## Key Results\n"
                "- The orchestration loop, run layout, and stage-summary validation path are active.\n"
                f"- Prompt length for this attempt was {len(prompt.split())} words.\n"
                "- No research claim from this stage should be treated as real output.\n\n"
                "## Files Produced\n"
                f"- `{relative_to_run(note_path, paths.run_root)}`\n"
                + artifact_lines
                + f"- `{relative_to_run(stage_tmp_path, paths.run_root)}`\n\n"
                "## Decision Ledger\n"
                f"- **Open Questions**: What real evidence should replace the fake output for {stage.display_name}?\n"
                f"- **Locked Decisions**: Keep `{stage.slug}` inside the current run layout and approval contract.\n"
                "- **Assumptions**: This smoke run is only validating workflow mechanics.\n"
                "- **Rejected Alternatives**: Treating placeholder artifacts as real research deliverables.\n\n"
                "## Suggestions for Refinement\n"
                f"1. Replace fake mode with the real {agent_label} operator and inspect the resulting artifacts.\n"
                "2. Tighten the stage prompt to better reflect the target of actual publication-grade work.\n"
                "3. Add stronger expectations for the concrete artifacts and files outputs from this stage.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )
        write_text(stage_tmp_path, stage_markdown)
        append_jsonl(
            paths.logs_raw,
            {
                "_meta": {
                    "stage": stage.slug,
                    "attempt": attempt_no,
                    "mode": "fake_continue" if continue_session else "fake_start",
                    "session_id": session_id,
                }
            },
        )

        return OperatorResult(
            success=True,
            exit_code=0,
            stdout="Fake operator completed successfully.",
            stderr="",
            stage_file_path=stage_tmp_path,
            session_id=session_id,
        )

    def _extract_approved_memory_from_prompt(self, prompt: str) -> str | None:
        match = re.search(
            r"^# Approved Memory\s*$\n?(.*?)(?=^# [^\n]+\s*$|\Z)",
            prompt,
            flags=re.MULTILINE | re.DOTALL,
        )
        if not match:
            return None
        extracted = match.group(1).strip()
        return extracted or None

    def _resolve_stage_session_id(
        self,
        paths: RunPaths,
        stage: StageSpec,
        continue_session: bool,
        allow_create: bool = True,
    ) -> str | None:
        # A persisted id is good for a *continuation* and for nothing else. `--session-id`
        # accepts a uuid once; the second time the CLI answers `Error: Session ID <uuid>
        # is already in use.`, which matches none of `_looks_like_resume_failure`'s
        # patterns, so no fallback fires and the attempt burns with nothing written.
        #
        # A stage can be entered more than once -- a revisit edge, `--redo-stage`,
        # `--resume-run` into an unapproved stage -- and every entry starts the attempt
        # loop at `continue_session = False` in `_run_stage`, with `build_prompt` rather
        # than `build_continuation_prompt`. That is a new conversation and it needs a new
        # id. The one entry that deliberately resumes, Studio's pending feedback, sets the
        # flag to True and still gets the persisted id and `--resume`.
        if not continue_session:
            return str(uuid.uuid4())

        broken_session_id: str | None = None
        session_state_path = paths.stage_session_state_file(stage)
        if session_state_path.exists():
            payload = json.loads(read_text(session_state_path))
            session_id = str(payload.get("session_id") or "").strip()
            broken = bool(payload.get("broken", False))
            if session_id and not broken:
                return session_id
            if session_id and broken:
                broken_session_id = session_id

        session_file = paths.stage_session_file(stage)
        if session_file.exists():
            session_id = read_text(session_file).strip()
            if session_id and session_id != broken_session_id:
                return session_id

        if continue_session and not allow_create:
            return None

        return str(uuid.uuid4())

    def _select_effective_session_id(
        self,
        *,
        requested_session_id: str | None,
        observed_session_id: str | None,
        success: bool,
    ) -> str | None:
        del observed_session_id, success
        return requested_session_id

    def _persist_stage_session_id(self, paths: RunPaths, stage: StageSpec, session_id: str | None) -> None:
        if not session_id:
            return
        write_text(paths.stage_session_file(stage), session_id)
        self._update_session_state(
            paths,
            stage,
            session_id,
            {
                "broken": False,
                "updated_at": self._now(),
            },
        )

    def _extract_session_id(self, payload: dict[str, object]) -> str | None:
        value = payload.get("session_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = payload.get("thread_id")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _prepare_invocation(
        self,
        prompt_path: Path,
        session_id: str,
        *,
        paths: RunPaths,
        resume: bool,
        tools: str | None = None,
    ) -> tuple[list[str], Path, str | None]:
        return (
            self._build_cli_command(
                prompt_path,
                session_id,
                resume=resume,
                tools=tools,
                mcp_config=self._mcp_config_path(paths),
                disallowed_tools=self.disallowed_tools,
            ),
            paths.run_root,
            None,
        )

    def _mcp_config_path(self, paths: RunPaths) -> Path | None:
        """Materialize the MCP servers' config inside the run.

        Written into `operator_state/` rather than a temp file so it sits with the prompts
        and session IDs: a run should be able to say what tools its agent was given, not
        only what it was told.

        Two servers, composed here rather than by either of them. The search server is
        conditional -- it replaces a built-in that only some deployments disable. The
        workspace server is not: it hands the agent the revertible write primitives, which
        are additive (a stage that ignores them writes files as before, and those writes
        are still attributed at the boundary) and are the only way a write can be withdrawn
        at the grain it was made rather than as a whole file at the end of a stage.
        """
        from .mcp_write import build_mcp_server_entry
        from .web_search import build_mcp_config, write_mcp_config

        servers: dict[str, object] = dict(build_mcp_server_entry(paths))
        if self.web_search_mcp:
            servers.update(build_mcp_config().get("mcpServers", {}))

        return write_mcp_config(
            paths.operator_state_dir / "mcp_config.json", servers=servers
        )

    def _build_cli_command(
        self,
        prompt_path: Path,
        session_id: str,
        *,
        resume: bool,
        tools: str | None = None,
        mcp_config: Path | None = None,
        disallowed_tools: Sequence[str] | None = None,
    ) -> list[str]:
        command = [
            self.command,
            "--model",
            self.model,
            "--permission-mode",
            "bypassPermissions",
            "--dangerously-skip-permissions",
        ]
        if self.isolate_auto_memory:
            # `--settings` adds to the settings already in force rather than replacing them,
            # so this turns off one feature and leaves the user's auth, model and env alone
            # -- checked against the real binary (2.1.229), where a run carrying this flag
            # still reached its configured backend.
            #
            # How to check a transcript for it, and the trap: the isolated run's `init` event
            # **omits `memory_paths` entirely** rather than setting it to null. So
            # `init["memory_paths"] is None` raises `KeyError` on precisely the run the check
            # exists to recognise, and `init.get("memory_paths")` cannot tell an isolated run
            # from a malformed event. Test `"memory_paths" not in init`.
            command.extend(["--settings", json.dumps({"autoMemoryEnabled": False})])
        if mcp_config is not None:
            # Not --strict-mcp-config: that would also drop whatever servers the user has
            # configured for their own environment, which is not AutoR's call to make.
            command.extend(["--mcp-config", str(mcp_config)])
        if tools:
            command.extend(["--tools", tools])
        if disallowed_tools:
            # One comma-joined argument rather than one argument per tool: `claude --help`
            # (2.1.229) declares the option variadic, so a second bare word after it is
            # read as a second tool name. Joining is also what makes the omission legible
            # -- the flag is absent entirely when nothing is denied, instead of present
            # with an empty value, which the CLI would read as a denial of nothing and a
            # reader would have to decide about.
            command.extend(["--disallowed-tools", ",".join(disallowed_tools)])
        if resume:
            command.extend(["--resume", session_id])
        else:
            command.extend(["--session-id", session_id])
        command.extend(
            [
                "-p",
                f"@{prompt_path}",
                "--output-format",
                "stream-json",
                "--verbose",
            ]
        )
        return command

    def _looks_like_resume_failure(self, stdout_text: str, stderr_text: str) -> bool:
        combined = "\n".join(part for part in [stdout_text, stderr_text] if part).lower()
        return (
            "no conversation found with session id" in combined
            or ("resume" in combined and "not found" in combined)
            or "no rollout found for thread id" in combined
            or ("thread/resume" in combined and "no rollout found" in combined)
        )

    def _write_attempt_state(
        self,
        paths: RunPaths,
        stage: StageSpec,
        attempt_no: int,
        payload: dict[str, object],
    ) -> None:
        write_text(paths.stage_attempt_state_file(stage, attempt_no), json.dumps(payload, indent=2, ensure_ascii=True))

    def _update_session_state(
        self,
        paths: RunPaths,
        stage: StageSpec,
        session_id: str | None,
        changes: dict[str, object],
    ) -> None:
        path = paths.stage_session_state_file(stage)
        payload: dict[str, object] = {}
        if path.exists():
            try:
                payload = json.loads(read_text(path))
            except json.JSONDecodeError:
                payload = {}
        payload.update(changes)
        if session_id:
            payload["session_id"] = session_id
        write_text(path, json.dumps(payload, indent=2, ensure_ascii=True))

    def _mark_session_broken(self, paths: RunPaths, stage: StageSpec, session_id: str | None, reason: str) -> None:
        self._update_session_state(
            paths,
            stage,
            session_id,
            {
                "broken": True,
                "broken_reason": reason,
                "updated_at": self._now(),
            },
        )

    def _now(self) -> str:
        return datetime.now().isoformat(timespec="seconds")

    def _agent_label(self) -> str:
        return "Codex" if self.backend_name == "codex" else "Claude"
