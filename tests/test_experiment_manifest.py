from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tests.prereg_support import write_validity_chain
from src.experiment_manifest import (
    format_experiment_manifest_for_prompt,
    load_experiment_manifest,
    write_experiment_manifest,
)
from src.utils import STAGES, build_run_paths, ensure_run_layout, validate_stage_artifacts, write_text


STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")


class ExperimentManifestTests(unittest.TestCase):
    def _build_paths(self) -> object:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        run_root = Path(tmp_dir.name) / "run"
        paths = build_run_paths(run_root)
        ensure_run_layout(paths)
        return paths

    def test_write_experiment_manifest_collects_results_code_and_notes(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "design.json", '{"task":"demo"}')
        write_text(paths.code_dir / "train.py", "print('train')\n")
        write_text(paths.notes_dir / "experiment_note.md", "# Note\n")
        write_text(paths.results_dir / "scores.csv", "step,score\n1,0.7\n2,0.8\n")
        write_validity_chain(paths, evidence="results/scores.csv")

        manifest = write_experiment_manifest(paths)
        self.assertTrue(manifest.ready_for_analysis)
        self.assertEqual(manifest.summary["result_artifact_count"], 1)
        self.assertEqual(manifest.summary["code_artifact_count"], 1)
        self.assertEqual(manifest.summary["note_artifact_count"], 1)

        loaded = load_experiment_manifest(paths.experiment_manifest)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.result_artifacts[0]["rel_path"], "results/scores.csv")
        self.assertEqual(loaded.result_artifacts[0]["schema"]["row_count"], 2)

        prompt_context = format_experiment_manifest_for_prompt(loaded)
        self.assertIn("results/scores.csv", prompt_context)
        self.assertIn("code/train.py", prompt_context)
        self.assertIn("notes/experiment_note.md", prompt_context)

    def test_stage05_validation_requires_experiment_manifest(self) -> None:
        paths = self._build_paths()
        write_text(paths.data_dir / "design.json", '{"task":"demo"}')
        write_text(paths.results_dir / "scores.csv", "step,score\n1,0.7\n")
        write_validity_chain(paths, evidence="results/scores.csv")

        problems = validate_stage_artifacts(STAGE_05, paths)
        self.assertTrue(any("experiment_manifest.json" in problem for problem in problems))

        write_experiment_manifest(paths)
        self.assertEqual(validate_stage_artifacts(STAGE_05, paths), [])

    def test_load_preserves_non_integer_summary_fields_without_crashing(self) -> None:
        paths = self._build_paths()
        write_text(
            paths.experiment_manifest,
            """
{
  "generated_at": "2026-04-13T09:00:00",
  "ready_for_analysis": true,
  "result_artifacts": [{"rel_path": "results/scores.csv", "schema": {"row_count": 2}}],
  "code_artifacts": ["code/train.py"],
  "note_artifacts": ["notes/run.md"],
  "summary": {
    "result_artifact_count": 1,
    "code_artifact_count": 1,
    "note_artifact_count": 1,
    "primary_finding": "Null result under all settings.",
    "hypotheses_status": {"H1": "not_supported"}
  }
}
            """.strip(),
        )

        manifest = load_experiment_manifest(paths.experiment_manifest)

        assert manifest is not None
        self.assertEqual(manifest.summary["result_artifact_count"], 1)
        self.assertEqual(manifest.summary_extras["primary_finding"], "Null result under all settings.")
        self.assertEqual(manifest.summary_extras["hypotheses_status"], {"H1": "not_supported"})

    def test_write_preserves_existing_summary_extras(self) -> None:
        paths = self._build_paths()
        write_text(paths.code_dir / "train.py", "print('train')\n")
        write_text(paths.notes_dir / "experiment_note.md", "# Note\n")
        write_text(paths.results_dir / "scores.csv", "step,score\n1,0.7\n2,0.8\n")
        write_text(
            paths.experiment_manifest,
            """
{
  "generated_at": "2026-04-13T09:00:00",
  "ready_for_analysis": true,
  "result_artifacts": [],
  "code_artifacts": [],
  "note_artifacts": [],
  "summary": {
    "result_artifact_count": 0,
    "code_artifact_count": 0,
    "note_artifact_count": 0,
    "primary_finding": "All settings censored."
  }
}
            """.strip(),
        )

        manifest = write_experiment_manifest(paths)
        reloaded = load_experiment_manifest(paths.experiment_manifest)

        self.assertEqual(manifest.summary_extras["primary_finding"], "All settings censored.")
        assert reloaded is not None
        self.assertEqual(reloaded.summary_extras["primary_finding"], "All settings censored.")
        prompt_context = format_experiment_manifest_for_prompt(reloaded)
        self.assertIn("Additional Summary Fields", prompt_context)
        self.assertIn("primary_finding: All settings censored.", prompt_context)


if __name__ == "__main__":
    unittest.main()
