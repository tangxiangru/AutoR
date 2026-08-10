"""An exhausted stage is not necessarily a failed stage.

Observed on a real ResearchClawBench run (Astronomy_000). Stage 06 burned its retry
budget on revision rounds and ended with a complete, validated 7,492-word summary and
thirteen figures on disk. Unattended auto-skip overwrote it with a 301-word stub saying
the work was not done. The next stage detected the loss and restored the draft by hand:

    "the auto-skip stub overwrote a completed 7,492-word summary whose artifacts
     ... are all on disk, so I restored it from 06_analysis.tmp.md"

The cost was not only the summary. The report that reached the benchmark never referenced
Stage 06's figures, so `f1_m33x7_exclusion.png` -- the exclusion curve the task is scored
on -- never got exported, and the judge scored that item 15/100 for its absence.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.manager import ResearchManager
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    initialize_memory,
    write_text,
)

STAGE = STAGES[5]  # 06_analysis, the stage this was observed on


def _valid_summary(stage) -> str:
    return f"""# {stage.stage_title}

## Objective
Characterise the exclusion band.

## Previously Approved Stage Summaries
None yet.

## What I Did
- Computed the exclusion probability curve and wrote it to disk.

## Key Results
- The 95% band is 0.58-2.75 peV.

## Files Produced
- `workspace/results/exclusion.json`

## Decision Ledger
### Open Questions
None.
### Locked Decisions
Level 211 only.
### Assumptions
Non-relativistic rates.
### Rejected Alternatives
The box method.

## Suggestions for Refinement
1. Extend to higher azimuthal levels.
2. Cross-check the rate module against an external package.
3. Report the coupling constant in GeV^-1.

## Your Options
1. Use suggestion 1
2. Use suggestion 2
3. Use suggestion 3
4. Refine with your own feedback
5. Approve and continue
6. Abort
"""


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.paths = build_run_paths(self.root / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        initialize_memory(self.paths, "goal")
        self.manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.root,
            operator=object(),
            unattended=True,
        )

    def _skip(self, kind="auto"):
        with patch.object(self.manager.ui, "show_status"):
            self.manager._skip_stage(
                paths=self.paths, stage=STAGE, attempt_no=9,
                reason="exhausted the retry budget", kind=kind,
            )
        return self.paths.stage_file(STAGE).read_text()

    def _write_draft(self, text):
        write_text(self.paths.stage_tmp_file(STAGE), text)


class ADraftThatWouldHavePassedIsKeptTest(_Harness):
    def setUp(self) -> None:
        super().setUp()
        # `Files Produced` is checked against disk, so the artifact has to be real.
        write_text(self.paths.results_dir / "exclusion.json", '{"band_peV": [0.58, 2.75]}')
        self._write_draft(_valid_summary(STAGE))
        self._gates = patch("src.manager.validate_stage_artifacts", return_value=[])
        self._gates.start(); self.addCleanup(self._gates.stop)

    def test_the_draft_is_promoted_rather_than_the_stub(self) -> None:
        promoted = self._skip()
        self.assertIn("exclusion probability curve", promoted)
        self.assertNotIn("auto-skipped with no human", promoted)

    def test_the_word_count_survives(self) -> None:
        """The observed loss was 7,492 words down to 301."""
        self.assertGreater(len(self._skip().split()), 60)

    def test_the_stub_is_kept_beside_it_for_the_audit_trail(self) -> None:
        self._skip()
        stub = self.paths.stages_dir / f"{STAGE.slug}.skip_stub.md"
        self.assertTrue(stub.exists())
        self.assertIn("auto-skipped", stub.read_text())

    def test_it_is_still_not_recorded_as_approved(self) -> None:
        """Promoting a validated draft is not the same as a reviewer accepting it."""
        from src.manifest import load_run_manifest

        self._skip()
        entry = next(s for s in load_run_manifest(self.paths.run_manifest).stages
                     if s.slug == STAGE.slug)
        self.assertFalse(entry.approved)

    def test_the_reason_says_it_was_never_reviewed(self) -> None:
        from src.manifest import load_run_manifest

        self._skip()
        entry = next(s for s in load_run_manifest(self.paths.run_manifest).stages
                     if s.slug == STAGE.slug)
        self.assertIn("never reviewed", entry.skip_reason or "")


class ADraftThatWouldNotHavePassedIsNotKeptTest(_Harness):
    def test_a_missing_draft_still_gets_the_stub(self) -> None:
        self.assertIn("auto-skipped with no human", self._skip())

    def test_a_draft_failing_the_markdown_gate_still_gets_the_stub(self) -> None:
        """With the artifact gate satisfied, the markdown gate is the only thing left
        standing between a malformed draft and promotion."""
        self._write_draft("# Stage 06: Analysis\n\nnot the contract at all\n")
        with patch("src.manager.validate_stage_artifacts", return_value=[]):
            self.assertIn("auto-skipped with no human", self._skip())

    def test_a_draft_missing_one_required_section_still_gets_the_stub(self) -> None:
        """The realistic near-miss: everything right except the Decision Ledger."""
        write_text(self.paths.results_dir / "exclusion.json", "{}")
        self._write_draft(_valid_summary(STAGE).replace("## Decision Ledger", "## Notes"))
        with patch("src.manager.validate_stage_artifacts", return_value=[]):
            self.assertIn("auto-skipped with no human", self._skip())

    def test_an_empty_draft_is_caught_by_the_markdown_gate(self) -> None:
        self._write_draft("")
        with patch("src.manager.validate_stage_artifacts", return_value=[]):
            self.assertIn("auto-skipped with no human", self._skip())

    def test_a_draft_failing_the_artifact_gate_still_gets_the_stub(self) -> None:
        write_text(self.paths.results_dir / "exclusion.json", "{}")
        self._write_draft(_valid_summary(STAGE))
        with patch("src.manager.validate_stage_artifacts", return_value=["no figures"]):
            self.assertIn("auto-skipped with no human", self._skip())

    def test_no_stub_sidecar_is_written_when_the_stub_is_the_summary(self) -> None:
        self._skip()
        self.assertFalse((self.paths.stages_dir / f"{STAGE.slug}.skip_stub.md").exists())


class OnlyTheUnattendedAutoSkipRescuesTest(_Harness):
    def setUp(self) -> None:
        super().setUp()
        write_text(self.paths.results_dir / "exclusion.json", '{"band_peV": [0.58, 2.75]}')
        self._write_draft(_valid_summary(STAGE))
        self._gates = patch("src.manager.validate_stage_artifacts", return_value=[])
        self._gates.start(); self.addCleanup(self._gates.stop)

    def test_a_human_requested_skip_is_honoured_as_a_skip(self) -> None:
        """`/skip` is a person saying "move past this". Promoting the draft would
        override the instruction they just gave."""
        promoted = self._skip(kind="human")
        self.assertIn("skipped at human direction", promoted)
        self.assertNotIn("exclusion probability curve", promoted)
