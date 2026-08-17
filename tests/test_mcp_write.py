"""The write server: protocol, attribution, and the failure modes that must not raise.

Verified against the real binary once, which is the check a protocol test cannot make.
``claude --mcp-config <cfg> -p "list your autor tools"`` returned::

    mcp__autor-write__autor_append_claim
    mcp__autor-write__autor_append_source
    mcp__autor-write__autor_record_result
    mcp__autor-write__autor_register_hypothesis
    mcp__autor-write__autor_set_artifact

so the config shape, the server name and the tool names reach the model's tool list as
``mcp__<server>__<tool>``. Everything below is the part that can be held green.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.effects import load_accumulator
from src.manifest import ensure_run_manifest, mark_stage_running_manifest, update_manifest_run_status
from src.mcp_write import (
    RUN_ROOT_ENV,
    SERVER_NAME,
    TOOLS,
    build_mcp_server_entry,
    call_tool,
    current_stage,
    handle_message,
    serve,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout

STAGE_01, STAGE_05 = STAGES[0], STAGES[4]


class WriteServerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        ensure_run_manifest(self.paths)

    def running(self, stage) -> None:
        mark_stage_running_manifest(self.paths, stage, 1)

    def call(self, name: str, arguments: dict) -> dict:
        return call_tool(name, arguments, run_root=self.paths.run_root)


class ProtocolTests(WriteServerTestCase):
    def test_initialize_echoes_the_client_version(self) -> None:
        """MCP negotiates down; a server that insists on its favourite stops working the
        next time the CLI updates."""

        response = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "9999-01-01"}},
            run_root=self.paths.run_root,
        )
        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], "9999-01-01")
        self.assertEqual(response["result"]["serverInfo"]["name"], SERVER_NAME)

    def test_every_advertised_tool_is_dispatchable(self) -> None:
        response = handle_message(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, run_root=self.paths.run_root
        )
        assert response is not None
        advertised = {tool["name"] for tool in response["result"]["tools"]}
        self.assertEqual(advertised, {tool["name"] for tool in TOOLS})

        self.running(STAGE_05)
        for name in advertised:
            reply = handle_message(
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": {}}},
                run_root=self.paths.run_root,
            )
            assert reply is not None
            self.assertIn("result", reply, f"{name} is advertised and not dispatched")

    def test_a_notification_is_answered_with_silence(self) -> None:
        """Answering a notification is itself a protocol error."""

        self.assertIsNone(
            handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}, run_root=None)
        )

    def test_an_unknown_tool_is_a_protocol_error_and_an_unknown_method_too(self) -> None:
        for message in (
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}},
            {"jsonrpc": "2.0", "id": 5, "method": "does/not/exist"},
        ):
            response = handle_message(message, run_root=self.paths.run_root)
            assert response is not None
            self.assertIn("error", response)

    def test_unparseable_input_does_not_stop_the_loop(self) -> None:
        stdin = io.StringIO('not json\n{"jsonrpc":"2.0","id":9,"method":"ping"}\n')
        stdout = io.StringIO()

        serve(stdin=stdin, stdout=stdout, run_root=self.paths.run_root)

        replies = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
        self.assertEqual([reply["id"] for reply in replies], [9])


class AttributionTests(WriteServerTestCase):
    def test_the_stage_comes_from_the_manifest_rather_than_the_arguments(self) -> None:
        """The config is written once per run and outlives any one stage."""

        self.running(STAGE_05)
        self.assertEqual(current_stage(self.paths).slug, STAGE_05.slug)

        self.running(STAGE_01)
        self.assertEqual(current_stage(self.paths).slug, STAGE_01.slug)

    def test_a_write_between_stages_is_refused_rather_than_guessed(self) -> None:
        """A write attributed to the wrong stage is withdrawn by the wrong rollback."""

        update_manifest_run_status(
            self.paths, run_status="pending", last_event="stage.approved", current_stage_slug=None
        )

        result = self.call("autor_set_artifact", {"path": "data/x.csv", "content": "a\n"})

        self.assertTrue(result["isError"])
        self.assertFalse((self.paths.data_dir / "x.csv").exists())

    def test_a_write_lands_and_accumulates_its_inverse_against_the_running_stage(self) -> None:
        self.running(STAGE_05)

        result = self.call("autor_set_artifact", {"path": "data/x.csv", "content": "a\n"})

        self.assertFalse(result["isError"])
        self.assertEqual((self.paths.data_dir / "x.csv").read_text(encoding="utf-8"), "a\n")
        records = load_accumulator(self.paths, STAGE_05)
        self.assertEqual([record.inverse.kind for record in records], ["delete_path"])

    def test_an_appended_entry_is_withdrawable_on_its_own(self) -> None:
        """The grain the observed path cannot reach: one entry, not the whole file."""

        self.running(STAGE_01)
        self.call("autor_append_source", {"source": {"id": "S1", "title": "first"}})
        self.call("autor_append_source", {"source": {"id": "S2", "title": "second"}})

        records = load_accumulator(self.paths, STAGE_01)
        self.assertEqual([record.inverse.payload["entry_id"] for record in records], ["S1", "S2"])
        self.assertEqual([record.key for record in records], ["literature.sources"] * 2)

    def test_a_result_cannot_be_written_outside_the_results_directory(self) -> None:
        """The family the forward gates count is the one this tool writes into."""

        self.running(STAGE_05)
        self.call("autor_record_result", {"path": "../../escaped.json", "content": "{}\n"})

        self.assertTrue((self.paths.results_dir / "escaped.json").exists())
        self.assertFalse((self.paths.run_root.parent / "escaped.json").exists())


class FailuresComeBackAsResultsTests(WriteServerTestCase):
    def test_a_missing_identifier_is_reported_rather_than_raised(self) -> None:
        """The model can act on "that needs an id"; a protocol error ends the call."""

        self.running(STAGE_01)
        result = self.call("autor_append_source", {"source": {"title": "no id"}})

        self.assertTrue(result["isError"])
        self.assertIn("id", result["content"][0]["text"])

    def test_a_missing_argument_is_reported_rather_than_raised(self) -> None:
        self.running(STAGE_05)
        for name, arguments in (
            ("autor_set_artifact", {"content": "a\n"}),
            ("autor_record_result", {"content": "a\n"}),
            ("autor_append_source", {"source": "not an object"}),
        ):
            result = self.call(name, arguments)
            self.assertTrue(result["isError"], name)


class ConfigTests(WriteServerTestCase):
    def test_the_server_is_told_which_run_to_write_into(self) -> None:
        entry = build_mcp_server_entry(self.paths)[SERVER_NAME]

        self.assertEqual(entry["env"][RUN_ROOT_ENV], str(self.paths.run_root.resolve()))

    def test_it_runs_under_autors_own_interpreter(self) -> None:
        """Not whatever ``python3`` the agent's PATH finds: the child has to resolve
        ``src.effects`` the way the parent already verified."""

        import sys

        entry = build_mcp_server_entry(self.paths)[SERVER_NAME]
        self.assertEqual(entry["command"], sys.executable or "python3")
        self.assertIn("PYTHONPATH", entry["env"])


if __name__ == "__main__":
    unittest.main()
