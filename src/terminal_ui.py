from __future__ import annotations

import json
import os
import re
import shutil
import sys
import unicodedata
from typing import Any, TextIO


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class UnattendedInputError(RuntimeError):
    """Raised when an unattended run reaches a prompt that would block on a human.

    Unattended AutoR must never wait on stdin. Any prompt that survives is a bug in
    the automation path, so it fails loudly with the prompt text instead of hanging.
    """


class TerminalUI:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    REVERSE = "\x1b[7m"

    FG_BLUE = "\x1b[34m"
    FG_CYAN = "\x1b[36m"
    FG_GREEN = "\x1b[32m"
    FG_MAGENTA = "\x1b[35m"
    FG_RED = "\x1b[31m"
    FG_WHITE = "\x1b[37m"
    FG_YELLOW = "\x1b[33m"

    def __init__(
        self,
        output_stream: TextIO = sys.stdout,
        input_stream: TextIO = sys.stdin,
        interactive: bool = True,
    ) -> None:
        self.output_stream = output_stream
        self.input_stream = input_stream
        self.interactive = interactive

    def show_run_started(self, run_root: str, model: str, venue: str, resumed: bool = False) -> None:
        action = "Resume Run" if resumed else "Start Run"
        body = [
            f"Run root : {run_root}",
            f"Model    : {model}",
            f"Venue    : {venue}",
        ]
        self.panel(action, body, color=self.FG_CYAN)

    def show_banner(self) -> None:
        banner_lines = [
            " █████╗ ██╗   ██╗████████╗ ██████╗ ██████╗ ",
            "██╔══██╗██║   ██║╚══██╔══╝██╔═══██╗██╔══██╗",
            "███████║██║   ██║   ██║   ██║   ██║██████╔╝",
            "██╔══██║██║   ██║   ██║   ██║   ██║██╔══██╗",
            "██║  ██║╚██████╔╝   ██║   ╚██████╔╝██║  ██║",
            "╚═╝  ╚═╝ ╚═════╝    ╚═╝    ╚═════╝ ╚═╝  ╚═╝",
        ]
        subtitle = "Human-Centered AI Research Co-pilot"
        width = self._width()
        self.write("\n")
        for line in banner_lines:
            self.write(self._style(line.center(width), self.BOLD, self.FG_CYAN) + "\n")
        self.write(self._style(subtitle.center(width), self.DIM, self.FG_WHITE) + "\n\n")

    def show_stage_start(
        self,
        stage_title: str,
        attempt_no: int,
        continue_session: bool,
    ) -> None:
        mode = "continue current session" if continue_session else "start new session"
        self.panel(
            f"{stage_title} | Attempt {attempt_no}",
            [f"Mode: {mode}"],
            color=self.FG_BLUE,
        )

    def show_stage_document(self, stage_title: str, markdown: str) -> None:
        self.panel(
            f"{stage_title} | Stage Summary",
            markdown.rstrip().splitlines(),
            color=self.FG_BLUE,
        )

    def show_status(self, message: str, level: str = "info") -> None:
        labels = {
            "info": ("INFO", self.FG_CYAN),
            "success": ("OK", self.FG_GREEN),
            "warn": ("WARN", self.FG_YELLOW),
            "error": ("ERR", self.FG_RED),
        }
        label, color = labels.get(level, labels["info"])
        self.write(self._style(f"[{label}] ", self.BOLD, color) + message.rstrip() + "\n")

    def show_stream_event(
        self,
        payload: dict[str, Any],
        tool_names: dict[str, str],
    ) -> None:
        event_type = payload.get("type")
        if event_type == "thread.started":
            self._render_codex_thread_started(payload)
            return
        if event_type in {"item.started", "item.completed"}:
            self._render_codex_item_event(payload, tool_names)
            return
        if event_type == "turn.completed":
            self._render_codex_turn_completed(payload)
            return
        if event_type == "error":
            self._render_codex_error(payload)
            return
        if event_type == "system":
            self._render_system_event(payload)
            return
        if event_type == "assistant":
            self._render_assistant_event(payload, tool_names)
            return
        if event_type == "user":
            self._render_user_event(payload, tool_names)
            return
        if event_type == "result":
            self._render_result_event(payload)
            return

    def show_revision_delta(self, delta_text: str, attempt_no: int) -> None:
        title = f"What Changed | Attempt {attempt_no}"
        self.panel(title, delta_text.rstrip().splitlines(), color=self.FG_YELLOW)

    def show_raw_stream_line(self, line: str) -> None:
        self.panel("Agent Raw Output", [line], color=self.FG_YELLOW)

    def choose_action(self, suggestions: list[str]) -> str:
        options = [
            f"1. Use suggestion 1: {suggestions[0]}",
            f"2. Use suggestion 2: {suggestions[1]}",
            f"3. Use suggestion 3: {suggestions[2]}",
            "4. Refine with your own feedback",
            "5. Approve and continue",
            "6. Abort",
        ]

        selected = self._choose_menu_index("Choose Next Action", options)
        self.panel(
            "Selected Action",
            [options[selected]],
            color=self.FG_GREEN if selected == 4 else self.FG_MAGENTA,
        )
        return str(selected + 1)

    def read_multiline_feedback(self) -> str:
        self.panel(
            "Custom Feedback",
            [
                "Enter custom feedback and finish with an empty line.",
                "The current stage will continue in the same Claude session.",
            ],
            color=self.FG_MAGENTA,
        )
        lines: list[str] = []
        while True:
            prompt = self._style("> ", self.BOLD, self.FG_MAGENTA) if not lines else ""
            line = self._read_line(prompt)
            if not line.strip():
                if lines:
                    break
                self.show_status("Feedback cannot be empty.", level="warn")
                continue
            lines.append(line.rstrip())
        return "\n".join(lines).strip()

    def choose_intake_clarification_answer(
        self,
        question: str,
        options: list[str],
        index: int,
        total: int,
    ) -> str | None:
        menu = [f"{number}. {option}" for number, option in enumerate(options, start=1)]
        custom_number = len(menu) + 1
        skip_number = len(menu) + 2
        menu.append(f"{custom_number}. Custom response")
        menu.append(f"{skip_number}. Skip this question")

        if self._interactive_input_available():
            selected = self._choose_menu_index(
                f"Intake Clarification {index}/{total}",
                [question, "", *menu],
                selectable_start=2,
                clear_on_select=False,
            )
            action_index = selected - 2
            if action_index < len(options):
                return options[action_index]
            if action_index == len(options):
                return self._read_required_single_line(
                    "Custom response",
                    context=[f"Question: {question}", "", "Available options:", *options],
                )
            return None

        body = [question, "", *menu]
        while True:
            self.panel(f"Intake Clarification {index}/{total}", body, color=self.FG_MAGENTA)
            choice = self._read_line(
                self._style(
                    "Enter your choice or type a custom response:\n> ",
                    self.BOLD,
                    self.FG_MAGENTA,
                )
            ).strip()
            if not choice:
                self.show_status("Please choose an option, type a response, or skip.", level="warn")
                continue
            if choice.isdigit():
                selected = int(choice)
                if 1 <= selected <= len(options):
                    return options[selected - 1]
                if selected == custom_number:
                    return self._read_required_single_line(
                        "Custom response",
                        context=[f"Question: {question}", "", "Available options:", *options],
                    )
                if selected == skip_number:
                    return None
                self.show_status(f"Invalid choice. Enter 1-{skip_number}.", level="warn")
                continue
            return choice

    def choose_intake_final_action(self) -> str:
        options = [
            "1. Refine with your own feedback",
            "2. Approve intake and continue",
            "3. Abort",
        ]
        if self._interactive_input_available():
            selected = self._choose_menu_index("Review Intake Brief", options)
            return ["4", "5", "6"][selected]

        mapping = {"1": "4", "2": "5", "3": "6", "4": "4", "5": "5", "6": "6"}
        while True:
            self.panel("Review Intake Brief", options, color=self.FG_MAGENTA)
            choice = self._read_line(self._style("Enter your choice:\n> ", self.BOLD, self.FG_MAGENTA)).strip()
            if choice in mapping:
                return mapping[choice]
            self.show_status("Invalid choice. Enter 1, 2, or 3.", level="warn")

    def read_optional_multiline_feedback(
        self,
        title: str = "Additional Guidance",
        instructions: str = (
            "Optionally enter extra guidance and finish with an empty line. "
            "Press Enter immediately to skip."
        ),
    ) -> str | None:
        self.panel(title, [instructions], color=self.FG_MAGENTA)
        lines: list[str] = []
        while True:
            prompt = self._style("> ", self.BOLD, self.FG_MAGENTA) if not lines else ""
            line = self._read_line(prompt)
            if not line.strip():
                break
            lines.append(line.rstrip())
        text = "\n".join(lines).strip()
        return text or None

    def _read_required_single_line(self, label: str, context: list[str] | None = None) -> str:
        if context:
            self.panel(label, context, color=self.FG_MAGENTA)
        while True:
            answer = self._read_line(self._style(f"{label}:\n> ", self.BOLD, self.FG_MAGENTA)).strip()
            if answer:
                return answer
            self.show_status("Response cannot be empty.", level="warn")

    # ------------------------------------------------------------------
    # Intake session helpers
    # ------------------------------------------------------------------

    def read_single_line(self, prompt: str) -> str:
        """Read a single line of input with a styled prompt."""
        return self._read_line(self._style(prompt, self.BOLD, self.FG_CYAN))

    def ask_yes_no(self, question: str, default: bool = True) -> bool:
        """Ask a yes/no question. Returns *default* on empty input."""
        hint = "[Y/n]" if default else "[y/N]"
        answer = self._read_line(
            self._style(f"  {question} {hint} ", self.BOLD, self.FG_CYAN)
        ).strip().lower()
        if not answer:
            return default
        return answer in {"y", "yes"}

    def ask_resource_paths(self) -> list[tuple[str, str]]:
        """Collect file/directory paths and descriptions interactively.

        Returns list of ``(path, description)`` tuples.
        The user enters an empty path to stop.
        """
        self.panel(
            "Add Resources",
            [
                "Enter file or directory paths one at a time.",
                "For each path, you can add a short description.",
                "Press Enter on an empty path to finish.",
            ],
            color=self.FG_MAGENTA,
        )
        entries: list[tuple[str, str]] = []
        idx = 1
        while True:
            path = self._read_line(
                self._style(f"  Path {idx} (empty to finish): ", self.BOLD, self.FG_MAGENTA)
            ).strip()
            if not path:
                break
            desc = self._read_line(
                self._style("  Description (optional): ", self.DIM, self.FG_WHITE)
            ).strip()
            entries.append((path, desc))
            idx += 1
        return entries

    def show_intake_summary(self, context: object) -> None:
        """Display a summary panel for an IntakeContext."""
        # Import here to avoid circular imports
        from .intake import IntakeContext
        assert isinstance(context, IntakeContext)

        body: list[str] = [f"Goal: {context.goal}"]
        if context.resources:
            body.append(f"Resources: {len(context.resources)} file(s)")
            for r in context.resources:
                label = f"  - [{r.resource_type}] {r.source_path}"
                if r.description:
                    label += f" ({r.description})"
                body.append(label)
        if context.qa_transcript:
            body.append("")
            for turn in context.qa_transcript:
                body.append(f"Q: {turn.question}")
                body.append(f"A: {turn.answer}")
        self.panel("Intake Summary", body, color=self.FG_GREEN)

    def panel(self, title: str, body: list[str] | str, color: str = "") -> None:
        lines = self._panel_lines(title, body, color=color)
        self.write("\n".join(lines) + "\n")

    def rule(self, title: str, color: str = "") -> None:
        width = self._width()
        label = f" {title} "
        if len(label) >= width - 2:
            rendered = label[: width - 2]
        else:
            left = (width - len(label)) // 2
            right = width - len(label) - left
            rendered = "=" * left + label + "=" * right
        self.write(self._style(rendered + "\n", self.BOLD, color))

    def write(self, text: str) -> None:
        self._write(text)

    def _render_system_event(self, payload: dict[str, Any]) -> None:
        if payload.get("subtype") != "init":
            return
        model = str(payload.get("model") or "unknown")
        tool_count = len(payload.get("tools") or [])
        version = str(payload.get("claude_code_version") or "unknown")
        body = [
            f"Model       : {model}",
            f"Tools       : {tool_count} available",
            f"Code ver.   : {version}",
        ]
        self.panel("Claude Session Ready", body, color=self.FG_CYAN)

    def _render_codex_thread_started(self, payload: dict[str, Any]) -> None:
        thread_id = str(payload.get("thread_id") or "unknown")
        self.panel("Codex Session Ready", [f"Thread ID   : {thread_id}"], color=self.FG_CYAN)

    def _render_codex_item_event(
        self,
        payload: dict[str, Any],
        tool_names: dict[str, str],
    ) -> None:
        item = payload.get("item")
        if not isinstance(item, dict):
            return
        item_type = str(item.get("type") or "")
        event_type = str(payload.get("type") or "")
        item_id = str(item.get("id") or "")

        if item_type == "agent_message" and event_type == "item.completed":
            text = str(item.get("text") or "").strip()
            if text:
                self.panel("Codex Response", self._truncate_text_block(text, max_chars=1800), color=self.FG_GREEN)
            return

        if item_type != "command_execution":
            return

        tool_names[item_id] = "Bash"
        command = str(item.get("command") or "").strip()
        if event_type == "item.started":
            self.panel(
                "Tool Call | Bash",
                [f"Command: {self._truncate(command, 260)}"],
                color=self.FG_BLUE,
            )
            return

        output = str(item.get("aggregated_output") or "").strip()
        exit_code = item.get("exit_code")
        body = [f"Command: {self._truncate(command, 260)}"]
        if exit_code is not None:
            body.append(f"Exit code: {exit_code}")
        if output:
            body.append(f"Output  : {self._truncate(output, 420)}")
        self.panel(
            "Tool Result | Bash",
            body,
            color=self.FG_RED if exit_code not in {0, None} else self.FG_YELLOW,
        )

    def _render_codex_turn_completed(self, payload: dict[str, Any]) -> None:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            self.panel("Codex Finished", ["Turn completed."], color=self.FG_GREEN)
            return
        body = [
            f"Input tokens  : {usage.get('input_tokens', 'unknown')}",
            f"Cached input  : {usage.get('cached_input_tokens', 'unknown')}",
            f"Output tokens : {usage.get('output_tokens', 'unknown')}",
        ]
        self.panel("Codex Finished", body, color=self.FG_GREEN)

    def _render_codex_error(self, payload: dict[str, Any]) -> None:
        message = str(payload.get("message") or "").strip()
        if not message:
            return
        self.panel("Codex Status", [self._truncate(message, 420)], color=self.FG_YELLOW)

    def _render_assistant_event(
        self,
        payload: dict[str, Any],
        tool_names: dict[str, str],
    ) -> None:
        message = payload.get("message")
        if not isinstance(message, dict):
            return
        for item in message.get("content", []) or []:
            item_type = item.get("type")
            if item_type == "thinking":
                thinking = str(item.get("thinking") or "").strip()
                if thinking:
                    self.panel(
                        "Claude Thinking",
                        self._truncate_text_block(thinking, max_chars=1400),
                        color=self.FG_MAGENTA,
                    )
            elif item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    self.panel(
                        "Claude Response",
                        self._truncate_text_block(text, max_chars=1800),
                        color=self.FG_GREEN,
                    )
            elif item_type == "tool_use":
                tool_id = str(item.get("id") or "")
                tool_name = str(item.get("name") or "Tool")
                tool_names[tool_id] = tool_name
                summary = self._summarize_tool_use(tool_name, item.get("input"))
                self.panel(f"Tool Call | {tool_name}", summary, color=self.FG_BLUE)

    def _render_user_event(
        self,
        payload: dict[str, Any],
        tool_names: dict[str, str],
    ) -> None:
        result_payload = payload.get("tool_use_result")
        if not isinstance(result_payload, dict):
            return

        tool_use_id = ""
        tool_result_content = ""
        message = payload.get("message")
        if isinstance(message, dict):
            for item in message.get("content", []) or []:
                if item.get("type") == "tool_result":
                    tool_use_id = str(item.get("tool_use_id") or "")
                    tool_result_content = str(item.get("content") or "")
                    break

        tool_name = tool_names.get(tool_use_id, "Tool")
        color = self.FG_RED if result_payload.get("is_error") else self.FG_YELLOW
        summary = self._summarize_tool_result(tool_name, result_payload, tool_result_content)
        self.panel(f"Tool Result | {tool_name}", summary, color=color)

    def _render_result_event(self, payload: dict[str, Any]) -> None:
        subtype = str(payload.get("subtype") or "")
        is_error = bool(payload.get("is_error"))
        duration_ms = int(payload.get("duration_ms") or 0)
        turns = int(payload.get("num_turns") or 0)
        session_id = str(payload.get("session_id") or "unknown")
        title = "Claude Finished" if not is_error else "Claude Failed"
        color = self.FG_GREEN if not is_error else self.FG_RED
        # The two fields come from different places and can disagree: a stream cut
        # mid-response arrives as `is_error: true` with `subtype: "success"`,
        # because the CLI did finish emitting. Rendering them independently
        # produced the panel "Claude Failed / Status: success", which is the worst
        # possible thing to read when reconstructing an unattended run hours later
        # — it says both that the call failed and that it did not. Say which field
        # is which instead of picking one.
        status = subtype or ("error" if is_error else "success")
        if is_error and subtype and subtype != "error":
            status = f"{subtype} (the backend still flagged this call as failed)"
        body = [
            f"Status     : {status}",
            f"Turns      : {turns}",
            f"Duration   : {duration_ms / 1000:.1f}s",
            f"Session ID : {session_id}",
        ]
        self.panel(title, body, color=color)

    def _summarize_tool_use(self, tool_name: str, payload: Any) -> list[str]:
        if not isinstance(payload, dict):
            return [self._truncate(json.dumps(payload, ensure_ascii=False), 220)]

        if tool_name == "Bash":
            command = self._truncate(str(payload.get("command") or ""), 260)
            description = str(payload.get("description") or "Run shell command")
            return [description, f"Command: {command}"]
        if tool_name in {"Read", "Write", "Edit"}:
            file_path = str(payload.get("file_path") or payload.get("path") or "")
            if tool_name == "Write":
                content = str(payload.get("content") or "")
                return [f"File: {file_path}", f"Content preview: {self._truncate(content, 220)}"]
            return [f"File: {file_path}"]
        if tool_name == "TodoWrite":
            todos = payload.get("todos") or []
            summary = self._summarize_todos(todos)
            return summary if summary else ["Update todo list"]
        if tool_name == "WebSearch":
            return [f"Query: {self._truncate(str(payload.get('query') or ''), 240)}"]
        if tool_name == "WebFetch":
            url = str(payload.get("url") or payload.get("urlOrPath") or "")
            return [f"Target: {self._truncate(url, 240)}"]
        if tool_name == "Glob":
            return [f"Pattern: {self._truncate(str(payload.get('pattern') or ''), 240)}"]
        if tool_name == "Grep":
            query = str(payload.get("pattern") or payload.get("query") or "")
            path = str(payload.get("path") or "")
            return [f"Search: {self._truncate(query, 200)}", f"Path  : {self._truncate(path, 180)}"]
        if tool_name == "TaskOutput":
            return [self._truncate(str(payload.get("output") or payload.get("content") or ""), 260)]
        return [self._truncate(json.dumps(payload, ensure_ascii=False), 320)]

    def _summarize_tool_result(
        self,
        tool_name: str,
        payload: dict[str, Any],
        fallback_content: str,
    ) -> list[str]:
        if tool_name == "TodoWrite":
            todos = payload.get("newTodos") or payload.get("todos") or []
            summary = self._summarize_todos(todos)
            if summary:
                return summary

        stdout = str(payload.get("stdout") or "").strip()
        stderr = str(payload.get("stderr") or "").strip()
        if stdout or stderr:
            lines: list[str] = []
            if stdout:
                lines.append(f"stdout: {self._truncate(stdout, 420)}")
            if stderr:
                lines.append(f"stderr: {self._truncate(stderr, 420)}")
            return lines

        query = str(payload.get("query") or "").strip()
        results = payload.get("results")
        if query and isinstance(results, list):
            result_preview = ", ".join(self._truncate(str(item), 120) for item in results[:3])
            return [f"Query  : {self._truncate(query, 220)}", f"Result : {result_preview or '(no visible result)'}"]

        if fallback_content.strip():
            return [self._truncate(fallback_content.strip(), 420)]

        return [self._truncate(json.dumps(payload, ensure_ascii=False), 420)]

    def _summarize_todos(self, todos: Any) -> list[str]:
        if not isinstance(todos, list) or not todos:
            return []
        status_counts: dict[str, int] = {}
        lines: list[str] = []
        for item in todos:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        if status_counts:
            counts = ", ".join(f"{key}={value}" for key, value in sorted(status_counts.items()))
            lines.append(f"Todos: {counts}")
        for item in todos[:4]:
            if not isinstance(item, dict):
                continue
            active = str(item.get("activeForm") or item.get("content") or "").strip()
            status = str(item.get("status") or "unknown")
            lines.append(f"- [{status}] {self._truncate(active, 160)}")
        if len(todos) > 4:
            lines.append(f"... {len(todos) - 4} more")
        return lines

    def _panel_lines(self, title: str, body: list[str] | str, color: str = "") -> list[str]:
        width = self._width()
        inner_width = width - 4
        rendered: list[str] = []
        border = "+" + "-" * (width - 2) + "+"
        header_text = self._pad_to_width(self._truncate_to_width(title, inner_width), inner_width)
        header = f"| {header_text} |"
        divider = "|" + "-" * (width - 2) + "|"
        rendered.append(self._style(border, color))
        rendered.append(self._style(header, self.BOLD, color))
        rendered.append(self._style(divider, color))

        body_lines = body if isinstance(body, list) else [body]
        for raw_line in body_lines:
            wrapped = self._wrap_preserving_paragraphs(str(raw_line), inner_width)
            if not wrapped:
                rendered.append(self._framed_body_line("", inner_width, color=color))
                continue
            for line in wrapped:
                rendered.append(self._framed_body_line(line, inner_width, color=color))
        rendered.append(self._style(border, color))
        return rendered

    def _menu_lines(
        self,
        title: str,
        options: list[str],
        selected: int,
        *,
        selectable_start: int = 0,
    ) -> list[str]:
        width = self._width()
        inner_width = width - 4
        header_text = self._pad_to_width(self._truncate_to_width(title, inner_width), inner_width)
        lines = [
            self._style("+" + "-" * (width - 2) + "+", self.FG_MAGENTA),
            self._style(f"| {header_text} |", self.BOLD, self.FG_MAGENTA),
            self._style("|" + "-" * (width - 2) + "|", self.FG_MAGENTA),
        ]
        for index, option in enumerate(options):
            is_selectable = index >= selectable_start
            is_selected = index == selected
            prefix = ">" if is_selected else " "
            if not is_selectable:
                prefix = " "
            text = f"{prefix} {option}"
            for line_no, wrapped in enumerate(self._wrap_preserving_paragraphs(text, inner_width)):
                if is_selected:
                    lines.append(
                        self._framed_body_line(
                            wrapped,
                            inner_width,
                            color=self.FG_MAGENTA,
                            text_codes=(self.REVERSE, self.FG_MAGENTA),
                        )
                    )
                else:
                    lines.append(self._framed_body_line(wrapped, inner_width, color=self.FG_MAGENTA))
                if line_no == 0:
                    prefix = " "
        selectable_count = len(options) - selectable_start
        jump_hint = f"1-{selectable_count}" if selectable_count > 1 else "1"
        hint = f"Controls: Up/Down or j/k, {jump_hint} to jump, Enter to select"
        lines.append(self._style("|" + "-" * (width - 2) + "|", self.FG_MAGENTA))
        lines.append(self._framed_body_line(self._truncate_to_width(hint, inner_width), inner_width, color=self.FG_MAGENTA))
        lines.append(self._style("+" + "-" * (width - 2) + "+", self.FG_MAGENTA))
        return lines

    def _choose_menu_index(
        self,
        title: str,
        options: list[str],
        *,
        selectable_start: int = 0,
        clear_on_select: bool = True,
    ) -> int:
        if not self._interactive_input_available():
            while True:
                self.panel(title, options, color=self.FG_MAGENTA)
                choice = self._read_line("Enter your choice:\n> ").strip()
                if choice.isdigit():
                    selected = selectable_start + int(choice) - 1
                    if selectable_start <= selected < len(options):
                        return selected
                max_choice = len(options) - selectable_start
                self.show_status(f"Invalid choice. Enter 1-{max_choice}.", level="warn")

        selected = selectable_start
        previous_line_count = 0
        self._write("\x1b[?25l")
        try:
            while True:
                lines = self._menu_lines(title, options, selected, selectable_start=selectable_start)
                previous_line_count = self._replace_live_block(lines, previous_line_count)
                key = self._read_key()

                if key in {"up", "k"}:
                    selected -= 1
                    if selected < selectable_start:
                        selected = len(options) - 1
                elif key in {"down", "j"}:
                    selected += 1
                    if selected >= len(options):
                        selected = selectable_start
                elif key.isdigit():
                    candidate = selectable_start + int(key) - 1
                    if selectable_start <= candidate < len(options):
                        selected = candidate
                elif key == "enter":
                    if clear_on_select:
                        self._clear_live_block(previous_line_count)
                    return selected
        finally:
            self._write("\x1b[?25h")

    def _replace_live_block(self, lines: list[str], previous_line_count: int) -> int:
        self._clear_live_block(previous_line_count)
        self._write("\n".join(lines) + "\n")
        return len(lines)

    def _clear_live_block(self, line_count: int) -> None:
        if line_count <= 0 or not self._ansi_available():
            return
        self._write(f"\x1b[{line_count}F")
        for _ in range(line_count):
            self._write("\x1b[2K\r")
            self._write("\x1b[1E")
        self._write(f"\x1b[{line_count}F")

    def _wrap_preserving_paragraphs(self, text: str, width: int) -> list[str]:
        lines: list[str] = []
        for paragraph in text.splitlines():
            if not paragraph.strip():
                lines.append("")
                continue
            lines.extend(self._wrap_display_line(paragraph, width))
        return lines

    def _wrap_display_line(self, text: str, width: int) -> list[str]:
        remaining = text
        wrapped: list[str] = []
        while self._display_width(remaining) > width:
            cut = self._find_wrap_cut(remaining, width)
            segment = remaining[:cut].rstrip()
            wrapped.append(segment or remaining[:cut])
            remaining = remaining[cut:].lstrip()
        wrapped.append(remaining)
        return wrapped

    def _find_wrap_cut(self, text: str, width: int) -> int:
        cells = 0
        last_space = -1
        for index, char in enumerate(text):
            char_width = self._char_width(char)
            if cells + char_width > width:
                if last_space > 0:
                    return last_space + 1
                return max(index, 1)
            cells += char_width
            if char.isspace():
                last_space = index
        return len(text)

    def _framed_body_line(
        self,
        text: str,
        inner_width: int,
        *,
        color: str = "",
        text_codes: tuple[str, ...] = (),
    ) -> str:
        padded = self._pad_to_width(text, inner_width)
        body = self._style(padded, *text_codes) if text_codes else padded
        if color and self._ansi_available():
            return f"{self._style('|', color)} {body} {self._style('|', color)}"
        return f"| {body} |"

    def _pad_to_width(self, text: str, width: int) -> str:
        return text + " " * max(0, width - self._display_width(text))

    def _truncate_to_width(self, text: str, width: int) -> str:
        if self._display_width(text) <= width:
            return text
        suffix = "..."
        target = max(0, width - len(suffix))
        cells = 0
        chars: list[str] = []
        for char in text:
            char_width = self._char_width(char)
            if cells + char_width > target:
                break
            chars.append(char)
            cells += char_width
        return "".join(chars).rstrip() + suffix

    def _display_width(self, text: str) -> int:
        visible = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", text)
        return sum(self._char_width(char) for char in visible)

    def _char_width(self, char: str) -> int:
        if unicodedata.combining(char):
            return 0
        if unicodedata.east_asian_width(char) in {"F", "W"}:
            return 2
        return 1

    def _truncate_text_block(self, text: str, max_chars: int) -> list[str]:
        content = text.strip()
        if len(content) > max_chars:
            content = content[: max_chars - 3].rstrip() + "..."
        return content.splitlines()

    def _truncate(self, text: str, max_chars: int) -> str:
        stripped = text.strip()
        if len(stripped) <= max_chars:
            return stripped
        return stripped[: max_chars - 3].rstrip() + "..."

    def _style(self, text: str, *codes: str) -> str:
        if not self._ansi_available():
            return text
        active = "".join(code for code in codes if code)
        if not active:
            return text
        return f"{active}{text}{self.RESET}"

    def _width(self) -> int:
        columns = shutil.get_terminal_size((100, 20)).columns
        return min(max(columns, 20), 118)

    def _read_line(self, prompt: str = "") -> str:
        if not self.interactive:
            raise UnattendedInputError(
                "AutoR is running unattended and cannot answer an interactive prompt: "
                + (ANSI_ESCAPE_RE.sub("", prompt).strip() or "(unlabelled prompt)")
            )
        if prompt:
            self._write(prompt)
        line = self.input_stream.readline()
        if line == "":
            raise EOFError("No input available.")
        return line.rstrip("\r\n")

    def _write(self, text: str) -> None:
        self.output_stream.write(text)
        self.output_stream.flush()

    def _ansi_available(self) -> bool:
        is_tty = hasattr(self.output_stream, "isatty") and self.output_stream.isatty()
        if not is_tty:
            return False
        return os.environ.get("TERM", "").lower() != "dumb"

    def _interactive_input_available(self) -> bool:
        if not self.interactive:
            return False
        return hasattr(self.input_stream, "isatty") and self.input_stream.isatty()

    def _read_key(self) -> str:
        try:
            import termios
            import tty

            file_descriptor = self.input_stream.fileno()
            old_settings = termios.tcgetattr(file_descriptor)
        except (ImportError, AttributeError, OSError):
            line = self._read_line()
            return "enter" if not line else line[0]
        try:
            tty.setraw(file_descriptor)
            first = self.input_stream.read(1)
            if first in {"\r", "\n"}:
                return "enter"
            if first == "\x1b":
                second = self.input_stream.read(1)
                third = self.input_stream.read(1)
                sequence = first + second + third
                if sequence == "\x1b[A":
                    return "up"
                if sequence == "\x1b[B":
                    return "down"
                return ""
            return first
        finally:
            termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)
