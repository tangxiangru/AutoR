from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from src.artifact_index import (
    _infer_schema,
    _infer_schema_or_raise,
    format_artifact_index_for_prompt,
    load_artifact_index,
    write_artifact_index,
)
from src.utils import build_run_paths, ensure_run_layout, write_text
from src.writing_manifest import build_writing_manifest


class ArtifactIndexTests(unittest.TestCase):
    def _build_paths(self) -> object:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        return paths

    def test_write_artifact_index_indexes_structured_workspace_artifacts(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "dataset.csv", "id,label\n1,cat\n2,dog\n")
        write_text(
            paths.data_dir / "dataset.csv.schema.json",
            json.dumps({"kind": "table", "columns": ["id", "label"], "primary_key": "id"}),
        )
        write_text(
            paths.results_dir / "metrics.jsonl",
            '{"metric":"accuracy","value":0.9}\n{"metric":"loss","value":0.1}\n',
        )
        (paths.figures_dir / "accuracy.png").write_bytes(b"\x89PNG fake image data")

        index = write_artifact_index(paths)
        self.assertEqual(index.artifact_count, 3)
        self.assertEqual(index.counts_by_category["data"], 1)
        self.assertEqual(index.counts_by_category["results"], 1)
        self.assertEqual(index.counts_by_category["figures"], 1)

        loaded = load_artifact_index(paths.artifact_index)
        self.assertIsNotNone(loaded)
        assert loaded is not None

        by_path = {artifact.rel_path: artifact for artifact in loaded.artifacts}
        self.assertEqual(by_path["data/dataset.csv"].schema["source"], "declared")
        self.assertEqual(
            by_path["data/dataset.csv"].schema["sidecar_path"],
            "data/dataset.csv.schema.json",
        )
        self.assertEqual(by_path["results/metrics.jsonl"].schema["row_count"], 2)
        self.assertIn("metric", by_path["results/metrics.jsonl"].schema["keys"])
        self.assertEqual(by_path["figures/accuracy.png"].schema["kind"], "figure")

        prompt_context = format_artifact_index_for_prompt(loaded)
        self.assertIn("results/metrics.jsonl", prompt_context)
        self.assertIn("rows=2", prompt_context)

    def test_writing_manifest_reuses_artifact_index_metadata(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "study_design.json", '{"dataset":"demo"}')
        write_text(paths.results_dir / "scores.csv", "step,score\n1,0.5\n2,0.7\n")
        (paths.figures_dir / "curve.png").write_bytes(b"\x89PNG fake image data")

        manifest = build_writing_manifest(paths)
        self.assertEqual(manifest["artifact_index_path"], "artifact_index.json")

        result_files = manifest["result_files"]
        assert isinstance(result_files, list)
        self.assertEqual(result_files[0]["rel_path"], "results/scores.csv")
        self.assertEqual(result_files[0]["schema"]["row_count"], 2)

        data_files = manifest["data_files"]
        assert isinstance(data_files, list)
        self.assertEqual(data_files[0]["rel_path"], "data/study_design.json")
        self.assertEqual(data_files[0]["schema"]["kind"], "object")


if __name__ == "__main__":
    unittest.main()


class SchemaInferenceCannotEndARunTest(unittest.TestCase):
    """A byte the scanner cannot decode must cost an index entry, not the run.

    `_infer_schema` is reached from `write_artifact_index`, which the `artifact_index`
    channel calls while a stage prompt is being assembled. So anything it raises leaves
    `_build_stage_prompt` and ends the pipeline.

    Measured, on the `full40_pins` arm: Life_002 wrote a CSV holding byte 0xb0 -- a
    degree sign in the platform encoding -- and the strict UTF-8 read raised
    `UnicodeDecodeError` at Stage 03 of 7, nine hours in. The adapter caught it at the
    top, synthesised a report from what existed, and the batch runner filed the task as
    `completed`. It was scored 22.6 with one approved stage, and that number entered the
    arm looking like every other.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _schema(self, name: str, payload: bytes) -> dict:
        path = self.root / name
        path.write_bytes(payload)
        return _infer_schema(path, "results", self.root)

    def test_a_degree_sign_in_a_csv_does_not_raise(self) -> None:
        schema = self._schema("t.csv", b"temp_C,site\n21.5\xb0,north\n")
        self.assertIsInstance(schema, dict)
        self.assertIn("columns", schema, schema)
        self.assertEqual(schema.get("row_count"), 1)

    def test_an_undecodable_json_is_described_not_raised(self) -> None:
        schema = self._schema("t.json", b'{"a": "\xb0"}')
        self.assertIsInstance(schema, dict)

    def test_the_helpers_decode_leniently_on_their_own(self) -> None:
        """Both layers, held separately.

        The outer guard turns anything into an entry, which means a test that only calls
        `_infer_schema` passes whether or not the decoding was fixed. These call the
        raising variant, so the lenient reads are what is under test.
        """
        for name, payload, kind in (
            ("t.jsonl", b'{"a": 1}\n{"b": "\xff\xfe"}\n', "jsonl"),
            ("t.csv", b"temp_C,site\n21.5\xb0,north\n", "table"),
            ("t.json", b'{"a": "\xb0"}', "object"),
        ):
            with self.subTest(file=name):
                path = self.root / name
                path.write_bytes(payload)
                schema = _infer_schema_or_raise(path, "results", self.root)
                self.assertEqual(schema.get("kind"), kind)

    def test_arbitrary_bytes_under_a_table_suffix_are_survived(self) -> None:
        """The scanner walks whatever the agent wrote, including a mislabelled binary."""
        schema = self._schema("t.tsv", bytes(range(256)) * 8)
        self.assertIsInstance(schema, dict)

    def test_a_helper_that_throws_becomes_an_entry_not_an_exception(self) -> None:
        """The general guarantee, independent of which decode is at fault."""
        with mock.patch(
            "src.artifact_index._infer_schema_or_raise", side_effect=MemoryError("boom")
        ):
            with self.assertRaises(MemoryError):
                _infer_schema(self.root / "x.csv", "results", self.root)
        with mock.patch(
            "src.artifact_index._infer_schema_or_raise", side_effect=ValueError("boom")
        ):
            schema = _infer_schema(self.root / "x.csv", "results", self.root)
        self.assertEqual(schema.get("kind"), "unreadable")
        self.assertEqual(schema.get("error"), "ValueError")

    def test_a_whole_scan_survives_one_bad_file(self) -> None:
        """The entry degrades; its neighbours keep their schemas."""
        paths = build_run_paths(self.root / "run_0001")
        ensure_run_layout(paths)
        (paths.results_dir / "good.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (paths.results_dir / "bad.csv").write_bytes(b"a,b\n21.5\xb0,2\n")
        index = write_artifact_index(paths)
        names = {r.filename for r in index.live_artifacts}
        self.assertIn("good.csv", names)
        self.assertIn("bad.csv", names)
