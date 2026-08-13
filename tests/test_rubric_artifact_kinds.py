"""What `artifact_breadth` can see, and what it must refuse to be paid for.

The criterion read five workspace directories — `data/`, `results/`, `figures/`,
`code/`, `writing/`. Stages 01, 02 and 08 write to none of them. Measured on this
tree before the change, a Stage 08 carrying its whole release bundle scored **0.0**
and was handed the shortfall *"Every artifact in the run predates this stage's
execution"*, which was false: the bundle had been written seconds earlier into
`artifacts/` and `reviews/`, where nothing was looking. Stages 01 and 02 escaped the
number and not the consequence — `min_stage` was 3, so their drafts were ranked on
seven criteria against every later draft's eight.

Widening what the criterion reads opens the failure `is_autor_own_record` was written
for, in three new places: AutoR itself writes into `notes/`, `artifacts/` and
`reviews/` inside a stage's own execution window and *before* the draft is scored. A
criterion that pays a stage for the harness's files measures the harness.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from src.rubric import (
    STAGE_ARTIFACT_KINDS,
    _artifact_kind_dirs,
    _fresh_artifact_kinds,
    _score_artifact_breadth,
    expected_artifact_kinds,
    score_stage,
)
from src.utils import (
    STAGES,
    StageSpec,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    format_stage_template,
    load_prompt_template,
    mark_stage_execution_started,
    write_text,
)

REPO = Path(__file__).resolve().parent.parent
PROMPT_DIR = REPO / "src" / "prompts"
STAGE = {stage.number: stage for stage in STAGES}


def stage_markdown(stage: StageSpec, *, files: str = "- `workspace/notes/plan.md`") -> str:
    return (
        f"# {stage.stage_title}\n\n"
        "## Objective\n\nPrepare the outputs this stage owes.\n\n"
        "## Previously Approved Stage Summaries\n\nNone yet.\n\n"
        "## What I Did\n\nWrote the files listed below.\n\n"
        "## Key Results\n\nThe bundle is complete.\n\n"
        f"## Files Produced\n\n{files}\n\n"
        "## Decision Ledger\n\n"
        "- Open Questions: whether the poster needs a second figure.\n"
        "- Locked Decisions: the release notes name the refuted hypothesis.\n"
        "- Assumptions: the manuscript is final at this revision.\n"
        "- Rejected Alternatives: a press release, which overstates one run.\n"
        "## Suggestions for Refinement\n\n1. a\n2. b\n3. c\n\n"
        "## Your Options\n\n"
        "1. Use suggestion 1\n2. Use suggestion 2\n3. Use suggestion 3\n"
        "4. Refine with your own feedback\n5. Approve and continue\n6. Abort\n"
    )


class ArtifactKindTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def start(self, number: int) -> StageSpec:
        """Open a stage's execution window, so what follows is written inside it."""
        stage = STAGE[number]
        mark_stage_execution_started(self.paths, stage)
        # The freshness cutoff is a marker file's mtime, at whatever resolution the
        # filesystem keeps. Without this, a file written in the same tick as the
        # marker is fresh or stale by luck.
        time.sleep(0.02)
        return stage

    def breadth(self, stage: StageSpec):
        return _score_artifact_breadth(self.paths, stage, None)


class WhatTheCriterionCanSeeTests(ArtifactKindTestCase):
    def test_stage_08_is_measured_on_the_bundle_it_actually_wrote(self) -> None:
        """The regression, end to end: this exact tree scored 0.0 before the change."""
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"a": 0.5, "b": 0.6}))
        write_text(self.paths.figures_dir / "effect.png", "x" * 200)
        stage = self.start(8)
        write_text(self.paths.reviews_dir / "readiness_checklist.md", "# Readiness\n" + "x" * 200)
        write_text(self.paths.artifacts_dir / "release_notes.md", "# Release\n" + "x" * 200)
        write_text(self.paths.writing_dir / "external_summary.md", "# Summary\n" + "x" * 200)

        score = self.breadth(stage)
        self.assertEqual(score.score, 1.0)
        self.assertEqual(score.shortfall, "")
        self.assertIn("artifacts", score.observed)
        self.assertIn("reviews", score.observed)

    def test_a_stage_that_produced_something_is_not_told_it_produced_nothing(self) -> None:
        """The false shortfall, on its own.

        `predates this stage's execution` is a claim about the run, and it was being
        made to a stage whose output was on disk with a fresh mtime.
        """
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"a": 0.5}))
        stage = self.start(8)
        write_text(self.paths.reviews_dir / "readiness_checklist.md", "# Readiness\n" + "x" * 200)

        score = self.breadth(stage)
        self.assertGreater(score.score, 0.0)
        self.assertNotIn("predates", score.shortfall)
        self.assertIn("workspace/artifacts/", score.shortfall)
        self.assertIn("workspace/writing/", score.shortfall)

    def test_the_predates_shortfall_survives_for_the_stage_it_is_true_of(self) -> None:
        """The control. It was the *wrong* diagnosis, not a wrong message."""
        write_text(self.paths.artifacts_dir / "release_notes.md", "# Release\n" + "x" * 200)
        time.sleep(0.02)
        stage = self.start(8)

        score = self.breadth(stage)
        self.assertEqual(score.score, 0.0)
        self.assertIn("predates", score.shortfall)

    def test_stage_01_is_scored_on_its_literature_directory(self) -> None:
        stage = self.start(1)
        write_text(
            self.paths.literature_dir / "sources.json",
            json.dumps({"sources": [{"source_id": "s1", "title": "A long enough title"}]}),
        )
        score = self.breadth(stage)
        self.assertEqual(score.score, 1.0)

    def test_stage_01_and_02_are_ranked_on_the_same_criteria_as_every_later_stage(self) -> None:
        """`min_stage=3` made an early draft's total a different measurement.

        `StageScore.comparable_to` guards the rubric version and the stage slug, so
        nothing refuses to compare a seven-criterion total with an eight-criterion one.
        """
        for number in (1, 2):
            score = score_stage(
                paths=self.paths, stage=STAGE[number], markdown=stage_markdown(STAGE[number])
            )
            self.assertIn("artifact_breadth", score.by_key, msg=f"stage {number:02d}")

    def test_a_stage_cannot_climb_by_writing_more_of_the_kind_it_already_had(self) -> None:
        stage = self.start(6)
        write_text(self.paths.figures_dir / "one.png", "x" * 200)
        one = self.breadth(stage).score
        for index in range(2, 8):
            write_text(self.paths.figures_dir / f"more_{index}.png", "x" * 200)
        self.assertEqual(self.breadth(stage).score, one)

    def test_a_kind_the_stage_was_never_asked_for_earns_nothing(self) -> None:
        """Scored against the expected set, not against a count of any kinds at all.

        A Stage 06 that wrote code and notes and no figures used to collect two of its
        three; the analysis stage owes figures and results.
        """
        stage = self.start(6)
        write_text(self.paths.code_dir / "plot.py", "print('x')\n" * 5)
        write_text(self.paths.notes_dir / "analysis.md", "# Analysis\n" + "x" * 200)
        score = self.breadth(stage)
        self.assertEqual(score.score, 0.0)
        self.assertIn("workspace/figures/", score.shortfall)
        self.assertIn("workspace/results/", score.shortfall)

    def test_a_stage_nobody_declared_kinds_for_is_not_scored_as_a_failure(self) -> None:
        """The same rule as `min_stage`: an expectation nobody wrote is not a failure."""
        invented = StageSpec(9, "09_invented", "Invented Stage")
        self.assertEqual(expected_artifact_kinds(invented), frozenset())
        self.assertEqual(self.breadth(invented).score, 1.0)


class TheHarnessMustNotEarnTheStageItsScoreTests(ArtifactKindTestCase):
    """AutoR's own writes into the four directories this criterion now reads.

    Each of these lands inside the stage's execution window and before the draft is
    scored, so without an exclusion the stage collects the kind for doing nothing.
    """

    def test_a_record_artifact_under_notes_is_still_not_the_stages_output(self) -> None:
        """`RECORD_ARTIFACTS` puts five files under `notes/` and two under `results/`.

        Stage 02's own `hypothesis_manifest.json` is one of them, and `reproducibility`
        already grades the hypothesis set — paying `artifact_breadth` for the same file
        would credit one artifact twice.
        """
        stage = self.start(2)
        write_text(
            self.paths.hypothesis_manifest,
            json.dumps({"empirical_hypotheses": [{"id": "H1", "decision_rule": "r"}]}),
        )
        write_text(self.paths.report_plan, json.dumps({"slots": []}))
        write_text(self.paths.experimental_protocol, json.dumps({"baselines": []}))
        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn("notes", fresh)
        self.assertEqual(self.breadth(stage).score, 0.0)

    def test_the_ideation_pool_the_panel_writes_is_not_stage_02s_notes(self) -> None:
        """`record_idea_pool` runs while the Stage 02 *prompt* is being built.

        Written by the shipped writer rather than by hand, so renaming the file it
        emits breaks this test instead of silently reopening the hole.
        """
        from src.ideation_panel import IdeaPool, record_idea_pool

        stage = self.start(2)
        record_idea_pool(self.paths, IdeaPool(candidates=[]), stage, 1)
        self.assertTrue(any(self.paths.notes_dir.iterdir()), "the panel wrote nothing to score")

        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn("notes", fresh)

    def test_the_writing_triage_the_manager_generates_is_not_stage_07s_artifacts(self) -> None:
        """`07_writing.md` tells the agent this file is "generated for you ... read it,
        do not write it". A criterion that pays for it pays the workflow manager."""
        from src.writing_manifest import generate_report_review

        stage = self.start(7)
        generate_report_review(self.paths)
        self.assertTrue(
            (self.paths.artifacts_dir / "report_review.json").exists(),
            "the manager wrote no triage artifact to score",
        )

        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn("artifacts", fresh)

    def test_the_comment_ledger_is_not_stage_08s_reviews(self) -> None:
        """`record_comment_round` closes an anchored-revision round before scoring."""
        from src.stage_comments import COMMENT_LEDGER_FILENAME

        stage = self.start(8)
        write_text(
            self.paths.reviews_dir / COMMENT_LEDGER_FILENAME,
            json.dumps({"rounds": [{"stage": stage.slug, "comments": []}]}),
        )
        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn("reviews", fresh)

    def test_the_stages_own_review_asset_beside_the_ledger_still_counts(self) -> None:
        """The control, so the exclusion cannot over-broaden into dropping output."""
        from src.stage_comments import COMMENT_LEDGER_FILENAME

        stage = self.start(8)
        write_text(self.paths.reviews_dir / COMMENT_LEDGER_FILENAME, json.dumps({"rounds": []}))
        write_text(self.paths.reviews_dir / "readiness_checklist.md", "# Readiness\n" + "x" * 200)
        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertIn("reviews", fresh)


class TheExpectationComesFromTheStagesOwnPromptTests(ArtifactKindTestCase):
    """A rubric may not ask for work the run was never told to do.

    Re-derived rather than reviewed: the prompt is rendered with this run's real paths
    and a kind counts as "asked for" when the directory it reads appears in the
    rendered text. No hand-written map of placeholders to kinds sits between the two,
    so a prompt that stops naming a directory fails here.
    """

    def rendered_prompt(self, stage: StageSpec) -> str:
        ensure_run_config(self.paths)
        texts = []
        for output_format in (None, "markdown", "latex"):
            template = load_prompt_template(PROMPT_DIR, stage, output_format)
            texts.append(format_stage_template(template, stage, self.paths))
        return "\n".join(texts)

    def kinds_named_by(self, stage: StageSpec) -> set[str]:
        text = self.rendered_prompt(stage)
        return {
            kind
            for kind, directories in _artifact_kind_dirs(self.paths, None).items()
            if any(str(directory.resolve()) in text for directory in directories)
        }

    def test_every_expected_kind_is_a_directory_the_stages_prompt_names(self) -> None:
        for number, expected in sorted(STAGE_ARTIFACT_KINDS.items()):
            named = self.kinds_named_by(STAGE[number])
            self.assertLessEqual(
                expected,
                named,
                msg=(
                    f"stage {number:02d} is graded on {sorted(expected - named)}, which its "
                    f"prompt never asks for; it names {sorted(named)}"
                ),
            )

    def test_study_design_is_not_asked_for_code(self) -> None:
        """The one place the obvious grouping is wrong.

        `03_study_design.md` names the data and notes directories and never the code
        directory — implementation is Stage 04's job — so expecting `code` at 03 would
        dock a compliant design stage a third of the criterion and send its polish
        round after code it should not write.
        """
        self.assertNotIn("code", expected_artifact_kinds(STAGE[3]))
        self.assertNotIn("code", self.kinds_named_by(STAGE[3]))
        self.assertIn("code", expected_artifact_kinds(STAGE[4]))

    def test_every_stage_of_the_graph_declares_an_expectation(self) -> None:
        self.assertEqual(sorted(STAGE_ARTIFACT_KINDS), [stage.number for stage in STAGES])


if __name__ == "__main__":
    unittest.main()
