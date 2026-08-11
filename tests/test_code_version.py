"""A run has to be able to say which code produced it.

`run_manifest.json` had the run id, timestamps, status and stages. `_meta.json` had the
model and the duration. Neither had a version of any kind, which is fine until the checkout
moves -- and on a shared clone it moves constantly. During one 12-run ResearchClawBench
batch this repository advanced twelve commits under the running processes, so the first six
runs and the last six did not use the same code and nothing on disk recorded which was
which. The provenance had to be reconstructed by hand from shell history.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import src.utils as utils
from src.rcb import write_run_meta
from src.utils import (
    UNKNOWN_CODE_VERSION,
    build_run_paths,
    code_version,
    ensure_run_layout,
    initialize_run_config,
    load_run_config,
)


class CodeVersionTest(unittest.TestCase):
    def setUp(self) -> None:
        utils._code_version_cache = None
        self.addCleanup(setattr, utils, "_code_version_cache", None)

    def test_it_reports_a_commit_in_this_repository(self) -> None:
        version = code_version()
        self.assertNotEqual(version, UNKNOWN_CODE_VERSION)
        self.assertRegex(version, r"^[0-9a-f]{12}(\+(dirty|unknown))?$")

    def test_it_is_never_blank(self) -> None:
        """A field that is sometimes absent and sometimes empty is one readers guess about."""
        self.assertTrue(code_version().strip())

    def test_a_modified_tree_says_so(self) -> None:
        """A run from a dirty tree is not reproducible from its sha, and must not claim to be."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abcdef0123456789\n"),
                mock.Mock(returncode=0, stdout=" M src/utils.py\n"),
            ]
            self.assertEqual(code_version(), "abcdef012345+dirty")

    def test_a_clean_tree_carries_no_suffix(self) -> None:
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abcdef0123456789\n"),
                mock.Mock(returncode=0, stdout=""),
            ]
            self.assertEqual(code_version(), "abcdef012345")

    def test_a_status_that_could_not_be_read_is_not_reported_as_clean(self) -> None:
        """Failing to ask whether the tree is dirty is not the same as it being clean."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abcdef0123456789\n"),
                mock.Mock(returncode=128, stdout=""),
            ]
            self.assertEqual(code_version(), "abcdef012345+unknown")

    def test_a_checkout_with_no_git_is_unknown_rather_than_an_error(self) -> None:
        """A tarball install must not fail a run over metadata."""
        with mock.patch("subprocess.run", side_effect=FileNotFoundError("git")):
            self.assertEqual(code_version(), UNKNOWN_CODE_VERSION)

    def test_a_non_repository_is_unknown(self) -> None:
        with mock.patch("subprocess.run", return_value=mock.Mock(returncode=128, stdout="")):
            self.assertEqual(code_version(), UNKNOWN_CODE_VERSION)

    def test_a_hung_git_does_not_hang_the_run(self) -> None:
        with mock.patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            self.assertEqual(code_version(), UNKNOWN_CODE_VERSION)

    def test_it_is_computed_once_per_process(self) -> None:
        """Every run start would otherwise pay for two subprocesses."""
        with mock.patch("subprocess.run") as run:
            run.side_effect = [
                mock.Mock(returncode=0, stdout="abcdef0123456789\n"),
                mock.Mock(returncode=0, stdout=""),
            ]
            first = code_version()
        self.assertEqual(code_version(), first)


class StampedOnTheRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_the_run_config_records_it(self) -> None:
        paths = build_run_paths(self.root / "run_0001")
        ensure_run_layout(paths)
        config = initialize_run_config(paths, model="opus", venue=None)
        self.assertEqual(config["code_version"], code_version())
        self.assertEqual(load_run_config(paths)["code_version"], code_version())

    def test_the_benchmark_metadata_records_it(self) -> None:
        """`_meta.json` is what the scorer and the leaderboard importer read."""
        workspace = self.root / "Physics_000_20260811_120000"
        workspace.mkdir()
        write_run_meta(
            workspace, task_id="Physics_000", run_id="Physics_000_20260811_120000",
            status="completed", duration_seconds=42, model="opus",
        )
        meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["code_version"], code_version())

    def test_a_config_predating_the_field_is_unknown_not_todays_commit(self) -> None:
        """Recomputing on load would answer "which code is reading this", not "which ran"."""
        paths = build_run_paths(self.root / "run_0002")
        ensure_run_layout(paths)
        initialize_run_config(paths, model="opus", venue=None)
        payload = json.loads(paths.run_config.read_text(encoding="utf-8"))
        payload.pop("code_version")
        paths.run_config.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(load_run_config(paths)["code_version"], UNKNOWN_CODE_VERSION)

    def test_a_recorded_version_is_read_back_verbatim(self) -> None:
        paths = build_run_paths(self.root / "run_0003")
        ensure_run_layout(paths)
        initialize_run_config(paths, model="opus", venue=None)
        payload = json.loads(paths.run_config.read_text(encoding="utf-8"))
        payload["code_version"] = "0000deadbeef+dirty"
        paths.run_config.write_text(json.dumps(payload), encoding="utf-8")
        self.assertEqual(load_run_config(paths)["code_version"], "0000deadbeef+dirty")

    def test_a_resume_does_not_rewrite_which_code_started_the_run(self) -> None:
        """save_run_config dropped the field, so a resume lost it -- caught by an existing test."""
        from src.utils import save_run_config

        paths = build_run_paths(self.root / "run_0004")
        ensure_run_layout(paths)
        initialize_run_config(paths, model="opus", venue=None)
        config = load_run_config(paths)
        config["code_version"] = "0000deadbeef"
        save_run_config(paths, config)
        self.assertEqual(load_run_config(paths)["code_version"], "0000deadbeef")

    def test_a_re_export_records_the_code_that_re_exported(self) -> None:
        """Unlike `agent_cmd`, this is last-wins: new code over an old workspace is the news."""
        workspace = self.root / "Physics_000_20260811_120000"
        workspace.mkdir()
        (workspace / "_meta.json").write_text(
            json.dumps({"agent_cmd": "autor", "code_version": "0000deadbeef"}), encoding="utf-8"
        )
        write_run_meta(
            workspace, task_id="Physics_000", run_id="Physics_000_20260811_120000",
            status="completed", duration_seconds=42, model="opus",
        )
        meta = json.loads((workspace / "_meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["code_version"], code_version())
        self.assertEqual(meta["agent_cmd"], "autor")


if __name__ == "__main__":
    unittest.main()
