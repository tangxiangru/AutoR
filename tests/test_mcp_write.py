"""The write surface, and the two things that make it safe to offer on every stage.

`src.provenance` attributes a stage's writes by comparing the workspace across a boundary,
because the agent writes files directly. This server closes the gap for writes that come
through it: attributed at the moment they happen, to the stage the manifest says is
running, with the previous bytes stored before the new ones land.

The tests that matter most are the refusals. A tool that fails has to leave the agent a way
forward, and the way forward is the ordinary file write -- still attributed, still
withdrawable, just less exactly. A refusal that reads as a protocol error instead would end
the call with nothing the model can act on.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.effects import load_accumulator
from src.manifest import ensure_run_manifest, mark_stage_running_manifest
from src.mcp_write import (
    RUN_ROOT_ENV,
    TOOLS,
    build_mcp_server_entry,
    call_tool,
    current_stage,
    handle_message,
    resolve_run_root,
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
        self.run_root = self.paths.run_root

    def running(self, stage) -> None:
        mark_stage_running_manifest(self.paths, stage, 1)

    def call(self, name: str, arguments: dict) -> dict:
        return call_tool(name, arguments, run_root=self.run_root)


class ProtocolTests(WriteServerTestCase):
    def test_tools_list_answers_with_every_tool(self) -> None:
        response = handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

        assert response is not None
        self.assertEqual(len(response["result"]["tools"]), len(TOOLS))

    def test_initialize_echoes_the_client_protocol_version(self) -> None:
        """MCP negotiates down; a server that insists on its favourite stops working the
        next time the CLI updates."""

        response = handle_message(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2099-01-01"},
            }
        )

        assert response is not None
        self.assertEqual(response["result"]["protocolVersion"], "2099-01-01")

    def test_a_notification_is_answered_with_silence(self) -> None:
        """Answering a notification is itself a protocol error."""

        self.assertIsNone(handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_an_unknown_tool_is_a_protocol_error(self) -> None:
        response = handle_message(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "rm_rf"}}
        )

        assert response is not None
        self.assertIn("error", response)

    def test_unparseable_input_does_not_take_the_session_down(self) -> None:
        import io

        out = io.StringIO()
        code = serve(io.StringIO("not json\n\n"), out, run_root=self.run_root)

        self.assertEqual(code, 0)
        self.assertEqual(out.getvalue(), "")


class AttributionTests(WriteServerTestCase):
    def test_the_stage_is_read_from_the_manifest_at_call_time(self) -> None:
        """The config is written once per run and this process outlives any one stage, so a
        captured value would attribute Stage 05's writes to Stage 01 for the rest of the
        run."""

        self.running(STAGE_01)
        self.assertEqual(current_stage(self.paths), STAGE_01)

        self.running(STAGE_05)
        self.assertEqual(current_stage(self.paths), STAGE_05)

    def test_a_write_is_attributed_to_the_stage_that_is_running(self) -> None:
        self.running(STAGE_05)
        result = self.call("autor_record_result", {"path": "metrics.json", "content": "{}\n"})

        self.assertFalse(result["isError"])
        self.assertEqual(
            [record.rel_path for record in load_accumulator(self.paths, STAGE_05)],
            ["results/metrics.json"],
        )

    def test_the_write_lands_and_carries_its_inverse(self) -> None:
        self.running(STAGE_05)
        self.call("autor_set_artifact", {"path": "data/counts.csv", "content": "id\n1\n"})

        self.assertTrue((self.paths.data_dir / "counts.csv").exists())
        inverse = load_accumulator(self.paths, STAGE_05)[0].inverse
        self.assertEqual(inverse.kind, "delete_path")

    def test_a_table_entry_is_withdrawable_on_its_own(self) -> None:
        self.running(STAGE_01)
        self.call("autor_append_source", {"source": {"id": "S1", "title": "one"}})
        self.call("autor_append_source", {"source": {"id": "S2", "title": "two"}})

        records = load_accumulator(self.paths, STAGE_01)
        self.assertEqual([record.inverse.payload["entry_id"] for record in records], ["S1", "S2"])
        self.assertEqual({record.key for record in records}, {"literature.sources"})


class RefusalTests(WriteServerTestCase):
    def test_a_refusal_is_a_result_the_model_can_act_on_not_a_protocol_error(self) -> None:
        self.running(STAGE_01)
        result = self.call("autor_append_source", {"source": {"title": "no id"}})

        self.assertTrue(result["isError"])
        self.assertIn("id", result["content"][0]["text"])

    def test_no_running_stage_refuses_and_names_the_way_forward(self) -> None:
        """A write with no stage cannot be attributed, and a refusal that leaves the agent
        stuck is worse than one that tells it to write the file directly."""

        result = self.call("autor_record_result", {"path": "m.json", "content": "{}"})

        self.assertTrue(result["isError"])
        self.assertIn("directly", result["content"][0]["text"])

    def test_no_run_root_refuses_rather_than_writing_somewhere(self) -> None:
        result = call_tool("autor_set_artifact", {"path": "a", "content": "b"}, run_root=None)

        self.assertTrue(result["isError"])
        self.assertIn(RUN_ROOT_ENV, result["content"][0]["text"])

    def test_a_result_path_cannot_escape_the_results_directory(self) -> None:
        self.running(STAGE_05)
        result = self.call(
            "autor_record_result", {"path": "../../../etc/passwd", "content": "x"}
        )

        self.assertFalse(result["isError"], "the traversal is normalised away, not refused")
        written = [record.rel_path for record in load_accumulator(self.paths, STAGE_05)]
        self.assertEqual(written, ["results/etc/passwd"])
        self.assertTrue(str(self.paths.results_dir) in str((self.paths.workspace_root / written[0])))


class ConfigTests(WriteServerTestCase):
    def test_the_server_block_names_the_run_it_writes_into(self) -> None:
        entry = build_mcp_server_entry(self.paths)
        block = next(iter(entry.values()))

        self.assertEqual(block["args"], ["-m", "src.mcp_write"])
        self.assertEqual(block["env"][RUN_ROOT_ENV], str(self.run_root.resolve()))

    def test_the_run_root_comes_from_the_environment(self) -> None:
        self.assertEqual(resolve_run_root({RUN_ROOT_ENV: "/tmp/x"}), Path("/tmp/x"))
        self.assertIsNone(resolve_run_root({}))
        self.assertIsNone(resolve_run_root({RUN_ROOT_ENV: "   "}))

    def test_the_operator_hands_the_agent_both_servers(self) -> None:
        """Search is conditional on the deployment; the write surface is not."""

        from src.operator import ClaudeOperator

        operator = ClaudeOperator.__new__(ClaudeOperator)
        operator.web_search_mcp = False
        destination = operator._mcp_config_path(self.paths)

        assert destination is not None
        servers = json.loads(destination.read_text(encoding="utf-8"))["mcpServers"]
        self.assertIn("autor-write", servers)


if __name__ == "__main__":
    unittest.main()
