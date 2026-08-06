"""The MCP server that hands the coding agent a real `web_search` tool.

Driven at the protocol level rather than through the SDK: MCP is plain JSON-RPC over
stdio here, and a test that spoke to a mock client would only prove the mock agrees with
itself.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from src import mcp_web_search
from src.mcp_web_search import call_web_search, handle_message, serve
from src.web_search import (
    MCP_SERVER_NAME,
    MCP_TOOL_NAME,
    SearchResult,
    WebSearchError,
    WebSearchResponse,
    build_mcp_config,
    build_web_search_prompt_section,
    write_mcp_config,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _grounded(query: str = "q", **_: object) -> WebSearchResponse:
    return WebSearchResponse(
        query, "gemini-test", "An answer.", "vertex",
        [SearchResult("A Paper", "https://arxiv.org/abs/1", ["A claim."])],
    )


def _ungrounded(query: str = "q", **_: object) -> WebSearchResponse:
    return WebSearchResponse(query, "gemini-test", "An answer with nothing behind it.")


class ProtocolTest(unittest.TestCase):
    def test_initialize_declares_the_tools_capability(self) -> None:
        reply = handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18"},
        })
        self.assertEqual(reply["id"], 1)
        self.assertIn("tools", reply["result"]["capabilities"])
        self.assertEqual(reply["result"]["serverInfo"]["name"], MCP_SERVER_NAME)

    def test_it_echoes_the_client_protocol_version(self) -> None:
        """MCP negotiates down. A server that insists on its favourite version stops
        working the next time the client updates."""
        reply = handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        })
        self.assertEqual(reply["result"]["protocolVersion"], "2099-01-01")

    def test_a_client_that_names_no_version_gets_the_fallback(self) -> None:
        reply = handle_message({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(
            reply["result"]["protocolVersion"], mcp_web_search.FALLBACK_PROTOCOL_VERSION
        )

    def test_tools_list_advertises_web_search_with_a_query_parameter(self) -> None:
        reply = handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = reply["result"]["tools"]
        self.assertEqual([t["name"] for t in tools], ["web_search"])
        schema = tools[0]["inputSchema"]
        self.assertEqual(schema["required"], ["query"])
        self.assertIn("max_results", schema["properties"])

    def test_the_advertised_description_carries_the_anti_fabrication_rule(self) -> None:
        """The tool description is the only instruction that travels with the tool."""
        description = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )["result"]["tools"][0]["description"]
        self.assertIn("never invent a reference", description.lower())
        self.assertIn("not text from the page", description)

    def test_a_notification_is_answered_with_silence(self) -> None:
        """Replying to a notification is itself a protocol violation."""
        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_a_known_method_without_an_id_is_also_answered_with_silence(self) -> None:
        """A notification is defined by the absent id, not by the method name. Replying
        to `initialize` sent as a notification is the same protocol violation as replying
        to `notifications/initialized`."""
        for method in ("initialize", "tools/list", "ping"):
            with self.subTest(method=method):
                self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": method}))

    def test_a_tool_call_without_an_id_runs_nothing_back(self) -> None:
        self.assertIsNone(handle_message(
            {"jsonrpc": "2.0", "method": "tools/call",
             "params": {"name": "web_search", "arguments": {"query": "q"}}},
            search=_grounded,
        ))

    def test_an_unknown_method_is_an_error_not_a_crash(self) -> None:
        reply = handle_message({"jsonrpc": "2.0", "id": 3, "method": "tools/nope"})
        self.assertEqual(reply["error"]["code"], mcp_web_search.METHOD_NOT_FOUND)

    def test_an_unknown_tool_name_is_rejected(self) -> None:
        reply = handle_message({
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "rm_rf", "arguments": {}},
        })
        self.assertEqual(reply["error"]["code"], mcp_web_search.METHOD_NOT_FOUND)


class ToolCallTest(unittest.TestCase):
    def _call(self, arguments, search=_grounded):
        return handle_message(
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
             "params": {"name": "web_search", "arguments": arguments}},
            search=search,
        )["result"]

    def test_a_grounded_search_returns_the_sources(self) -> None:
        result = self._call({"query": "attention sinks"})
        self.assertFalse(result["isError"])
        self.assertIn("https://arxiv.org/abs/1", result["content"][0]["text"])

    def test_the_query_reaches_the_search(self) -> None:
        seen = {}

        def record(query, **kwargs):
            seen["query"], seen["kwargs"] = query, kwargs
            return _grounded(query)

        self._call({"query": "grokking"}, search=record)
        self.assertEqual(seen["query"], "grokking")

    def test_max_results_is_forwarded_when_sensible(self) -> None:
        seen = {}

        def record(query, **kwargs):
            seen.update(kwargs)
            return _grounded(query)

        self._call({"query": "q", "max_results": 3}, search=record)
        self.assertEqual(seen.get("max_results"), 3)

    def test_a_nonsense_max_results_is_dropped_rather_than_passed_on(self) -> None:
        for value in (0, -1, True, "three", None):
            with self.subTest(value=value):
                seen = {}

                def record(query, **kwargs):
                    seen.update(kwargs)
                    return _grounded(query)

                self._call({"query": "q", "max_results": value}, search=record)
                self.assertNotIn("max_results", seen)

    def test_an_empty_query_is_an_error_without_calling_the_search(self) -> None:
        def explode(*args, **kwargs):
            raise AssertionError("must not search")

        result = self._call({"query": "   "}, search=explode)
        self.assertTrue(result["isError"])
        self.assertIn("non-empty", result["content"][0]["text"])

    def test_a_search_failure_is_a_tool_error_not_a_protocol_error(self) -> None:
        """The model can act on a tool error; a protocol error just ends the call."""
        def fail(*args, **kwargs):
            raise WebSearchError("no backend configured")

        result = self._call({"query": "q"}, search=fail)
        self.assertTrue(result["isError"])
        self.assertIn("no backend configured", result["content"][0]["text"])

    def test_an_unexpected_exception_never_escapes(self) -> None:
        """An uncaught exception here takes down the agent's whole stage."""
        def boom(*args, **kwargs):
            raise RuntimeError("kaboom")

        result = self._call({"query": "q"}, search=boom)
        self.assertTrue(result["isError"])
        self.assertIn("kaboom", result["content"][0]["text"])

    def test_an_ungrounded_answer_is_flagged_as_an_error(self) -> None:
        """An answer with no citable source is the failure this module exists to prevent,
        so it must not look like a successful search."""
        result = self._call({"query": "q"}, search=_ungrounded)
        self.assertTrue(result["isError"])
        self.assertIn("No citable source", result["content"][0]["text"])

    def test_an_ungrounded_answer_still_returns_the_text(self) -> None:
        """Flagged, but not withheld: the answer may still be a useful lead."""
        result = self._call({"query": "q"}, search=_ungrounded)
        self.assertIn("An answer with nothing behind it.", result["content"][0]["text"])

    def test_the_result_never_presents_claims_as_page_quotations(self) -> None:
        body = self._call({"query": "q"})["content"][0]["text"]
        self.assertNotIn("> A claim.", body)
        self.assertIn("not text from the page", body)


class StdioLoopTest(unittest.TestCase):
    def _drive(self, lines):
        out = io.StringIO()
        serve(io.StringIO("".join(f"{line}\n" for line in lines)), out, search=_grounded)
        return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]

    def test_a_session_replies_only_to_requests(self) -> None:
        replies = self._drive([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
        ])
        self.assertEqual([r["id"] for r in replies], [1, 2])

    def test_a_malformed_line_does_not_end_the_session(self) -> None:
        replies = self._drive(["not json at all", json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})])
        self.assertEqual([r["id"] for r in replies], [7])

    def test_blank_lines_are_ignored(self) -> None:
        replies = self._drive(["", "   ", json.dumps({"jsonrpc": "2.0", "id": 8, "method": "tools/list"})])
        self.assertEqual(len(replies), 1)

    def test_every_reply_is_one_line_of_json(self) -> None:
        out = io.StringIO()
        serve(io.StringIO(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"), out)
        self.assertEqual(len(out.getvalue().strip().splitlines()), 1)


class SubprocessContractTest(unittest.TestCase):
    """The config says `python -m src.mcp_web_search`; prove that actually starts."""

    def test_the_module_runs_as_a_server_and_answers(self) -> None:
        config = build_mcp_config()[ "mcpServers"][MCP_SERVER_NAME]
        proc = subprocess.run(
            [config["command"], *config["args"]],
            cwd=config["cwd"],
            env={"PYTHONPATH": config["env"]["PYTHONPATH"], "PATH": "/usr/bin:/bin"},
            input=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n",
            text=True, capture_output=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        payload = json.loads(proc.stdout.strip().splitlines()[0])
        self.assertEqual(payload["result"]["tools"][0]["name"], "web_search")


class McpConfigTest(unittest.TestCase):
    def test_it_names_this_interpreter_not_a_bare_python(self) -> None:
        server = build_mcp_config()["mcpServers"][MCP_SERVER_NAME]
        self.assertEqual(server["command"], sys.executable)

    def test_the_child_can_import_the_repo(self) -> None:
        """Without PYTHONPATH the child cannot resolve `src.web_search` and the server
        dies on import, which the agent sees only as a missing tool."""
        server = build_mcp_config()["mcpServers"][MCP_SERVER_NAME]
        self.assertEqual(server["env"]["PYTHONPATH"], str(REPO_ROOT))
        self.assertEqual(Path(server["cwd"]), REPO_ROOT)

    def test_the_advertised_tool_name_matches_the_server_name(self) -> None:
        """Claude Code derives mcp__<server>__<tool>; a mismatch means the prompt points
        at a tool that does not exist."""
        self.assertEqual(MCP_TOOL_NAME, f"mcp__{MCP_SERVER_NAME}__web_search")
        self.assertIn(MCP_SERVER_NAME, build_mcp_config()["mcpServers"])

    def test_writing_it_puts_it_inside_the_run(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            written = write_mcp_config(Path(tmp) / "operator_state" / "mcp_config.json")
            self.assertTrue(written.exists())
            self.assertIn(MCP_SERVER_NAME, json.loads(written.read_text())["mcpServers"])


class OperatorWiringTest(unittest.TestCase):
    def _command(self, *, web_search_mcp: bool):
        import tempfile

        from src.operator import ClaudeOperator
        from src.utils import build_run_paths, ensure_run_layout

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(paths)
        operator = ClaudeOperator(web_search_mcp=web_search_mcp)
        command, _, _ = operator._prepare_invocation(
            paths.prompt_cache_dir / "p.md", "sid", paths=paths, resume=False
        )
        return command, paths

    def test_the_claude_command_loads_the_server_when_search_is_active(self) -> None:
        command, paths = self._command(web_search_mcp=True)
        self.assertIn("--mcp-config", command)
        written = Path(command[command.index("--mcp-config") + 1])
        self.assertEqual(written.parent, paths.operator_state_dir)

    def test_no_flag_when_search_is_not_active(self) -> None:
        command, _ = self._command(web_search_mcp=False)
        self.assertNotIn("--mcp-config", command)

    def test_the_config_lands_in_the_run_for_audit(self) -> None:
        """A run should be able to say what tools its agent was given, not only what it
        was told."""
        command, paths = self._command(web_search_mcp=True)
        written = Path(command[command.index("--mcp-config") + 1])
        self.assertTrue(written.exists())
        self.assertTrue(str(written).startswith(str(paths.run_root)))

    def test_it_does_not_use_strict_mcp_config(self) -> None:
        """--strict-mcp-config would also drop the user's own servers, which is not
        AutoR's call to make."""
        command, _ = self._command(web_search_mcp=True)
        self.assertNotIn("--strict-mcp-config", command)


class PromptSectionNamesTheToolTest(unittest.TestCase):
    def test_the_section_names_the_tool_when_one_is_provided(self) -> None:
        self.assertIn(MCP_TOOL_NAME, build_web_search_prompt_section())

    def test_it_falls_back_to_the_shell_command_for_backends_without_mcp(self) -> None:
        section = build_web_search_prompt_section(mcp=False)
        self.assertNotIn(MCP_TOOL_NAME, section)
        self.assertIn("tools/web_search.py", section)

    def test_the_shell_command_survives_alongside_the_tool(self) -> None:
        """The script is the fallback, not a casualty of adding the tool."""
        self.assertIn("tools/web_search.py", build_web_search_prompt_section())
