"""What `artifact_breadth` can see, and what it must refuse to be paid for.

The criterion read five workspace directories — `data/`, `results/`, `figures/`,
`code/`, `writing/`. Stages 01 and 02 write to none of them, and Stage 08 writes to
exactly one: `08_dissemination.md` names `{{WORKSPACE_WRITING_DIR}}` alongside the
`artifacts/` and `reviews/` directories nothing was looking at. So a Stage 08 carrying
its whole release bundle was measured on the one third of it the criterion could see.
Replayed against `origin/main@fdded57` with only the bundle written inside the stage
window, that stage scored **0.333**, and dropping the summary under `writing/` scored
**0.0** with the shortfall *"Every artifact in the run predates this stage's
execution"* — which is false: the bundle had been written seconds earlier. Only the two
scores are quoted, because this module does not import on main, so the exact `observed`
transcript cannot be re-derived by anyone reading this later and a quoted one would be
a claim with no instrument behind it.

Stages 01 and 02 escaped the number and not the consequence. `min_stage` was 3, so
their drafts were ranked on five criteria worth 11.0 while Stage 03's were ranked on
six worth 13.0, and `StageScore.comparable_to` guards the rubric version and the stage
slug, not the criterion set. `min_stage` exists for a criterion that *cannot* apply;
Stage 01 and 02 do produce artifacts, so this was not one.

Widening what the criterion reads opens the failure `is_autor_own_record` was written
for, in four new directories: AutoR itself writes into `notes/`, `artifacts/` and
`reviews/` inside a stage's own execution window and *before* the draft is scored. A
criterion that pays a stage for the harness's files measures the harness. Each writer
below is driven for real, and `TheCensusOfWhoWritesUnderAGradedDirectoryTests` refuses
a path in `src/` that nobody has classified.
"""

from __future__ import annotations

import ast
import json
import tempfile
import time
import unittest
from pathlib import Path

from src.rubric import (
    CRITERIA,
    MIN_ARTIFACT_BYTES,
    STAGE_ARTIFACT_KINDS,
    _ARTIFACT_KIND_SUFFIXES,
    _artifact_kind_dirs,
    _fresh_artifact_kinds,
    _harness_written_records,
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

    def files_of_kind(self, kind: str) -> set[Path]:
        return {
            path
            for directory in _artifact_kind_dirs(self.paths, None)[kind]
            for path in directory.rglob("*")
            if path.is_file()
        }


class WhatTheCriterionCanSeeTests(ArtifactKindTestCase):
    def test_stage_08_is_measured_on_the_bundle_it_actually_wrote(self) -> None:
        """The regression, end to end.

        Replayed against `origin/main@fdded57`, this exact tree scores **0.333** —
        `artifacts/` and `reviews/` were invisible, so two thirds of the bundle did
        not exist as far as the criterion was concerned, and only the summary under
        `writing/` counted. The `results/` and `figures/` files are deliberately
        written *before* the window and left stale: they are the run accumulating,
        not this stage working.
        """
        # Padded past MIN_ARTIFACT_BYTES on purpose. The obvious two-key payload is 28
        # bytes, so `results` was never visible at any mtime and the "written before the
        # window and left stale" half of the docstring described an inert line.
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps({"accuracy": 0.5, "f1": 0.6, "seeds": [1, 2, 3], "n": 240}),
        )
        write_text(self.paths.figures_dir / "effect.png", "x" * 200)
        time.sleep(0.05)
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

    def test_stage_01_and_02_face_the_same_criteria_as_the_first_stage_that_did(self) -> None:
        """`min_stage=3` made an early draft's total a different measurement.

        Asserted as a relation between the three stages rather than as a count, so it
        stays true when a criterion is added. `quantification` and `numeric_fidelity`
        still do not reach Stage 01 — those are the two `min_stage` exists for, since
        Stage 01 has no Key Results to quantify and no results file to trace to.
        `artifact_breadth` was never in that category: Stage 01 writes `literature/`.
        """
        applicable = {
            number: frozenset(c.key for c in CRITERIA if c.applies_to(STAGE[number]))
            for number in (1, 2, 3)
        }
        self.assertEqual(applicable[1], applicable[3], "Stage 01 is graded on a different set")
        self.assertEqual(applicable[2], applicable[3], "Stage 02 is graded on a different set")
        self.assertIn("artifact_breadth", applicable[1])

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

        Measured against `origin/main@fdded57`: this tree — a Stage 06 that wrote code
        and notes and no figures — scored 0.333, collecting one of its three for
        `code/`, which the analysis stage does not owe. `notes/` was invisible then.
        The analysis stage owes figures and results, so it now earns neither.
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

    Each case drives the shipped writer rather than hand-placing a file, so renaming
    what a writer emits breaks the test instead of silently reopening the hole. Each
    also asserts, *before* looking at the score, that the writer left behind a file the
    criterion would otherwise have paid for — right directory, readable suffix, over
    `MIN_ARTIFACT_BYTES`. Without that the exclusion could be doing nothing and every
    test here would still pass, on a writer that wrote nothing.
    """

    def assert_the_harness_earned_nothing(self, stage: StageSpec, kind: str, before: set[Path]):
        """Something countable was written, and the stage was not credited for it."""
        allowed = _ARTIFACT_KIND_SUFFIXES[kind]
        produced = sorted(self.files_of_kind(kind) - before)
        countable = [
            path
            for path in produced
            if path.suffix.lower() in allowed and path.stat().st_size >= MIN_ARTIFACT_BYTES
        ]
        self.assertTrue(
            countable,
            f"the writer left nothing this criterion could have paid for: {produced}",
        )
        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn(
            kind,
            fresh,
            f"{kind} was earned by {[p.name for p in countable]}, which AutoR wrote",
        )
        self.assertEqual(self.breadth(stage).score, 0.0)
        return countable

    def panel_deliberation(self, stage: StageSpec, attempt_no: int):
        from src.review_panel import PanelDeliberation, PanelVerdict

        verdict = PanelVerdict(
            role_key="pi",
            role_title="Principal Investigator",
            backend="claude",
            model="sonnet",
            choice="5",
            decision_token="approve",
            blocking=False,
            reason="The release bundle matches what the stage committed to.",
            feedback="",
            concerns=("the second figure may be redundant",),
        )
        return PanelDeliberation(
            stage_slug=stage.slug, attempt_no=attempt_no, rounds=[[verdict]], chair_key="pi"
        )

    def test_a_record_artifact_under_notes_is_still_not_the_stages_output(self) -> None:
        """`RECORD_ARTIFACTS` puts six files under `notes/` and two under `results/`.

        Stage 02's own `hypothesis_manifest.json` is one of them, and `reproducibility`
        already grades the hypothesis set — paying `artifact_breadth` for the same file
        would credit one artifact twice.
        """
        from src.experiment_manifest import RECORD_ARTIFACTS

        self.assertEqual(
            sorted(str(item).split("/")[0] for item in RECORD_ARTIFACTS).count("notes"), 6
        )
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
        """`record_idea_pool` runs while the Stage 02 *prompt* is being built."""
        from src.ideation_panel import IdeaPool, record_idea_pool

        stage = self.start(2)
        before = self.files_of_kind("notes")
        record_idea_pool(self.paths, IdeaPool(candidates=[]), stage, 1)
        self.assert_the_harness_earned_nothing(stage, "notes", before)

    def test_the_writing_triage_the_manager_generates_is_not_stage_07s_artifacts(self) -> None:
        """`07_writing.md` tells the agent this file is "generated for you ... read it,
        do not write it". A criterion that pays for it pays the workflow manager."""
        from src.writing_manifest import generate_report_review

        stage = self.start(7)
        before = self.files_of_kind("artifacts")
        generate_report_review(self.paths)
        self.assert_the_harness_earned_nothing(stage, "artifacts", before)

    def test_the_layout_triage_the_manager_generates_is_not_stage_07s_artifacts(self) -> None:
        """The LaTeX half of the same pair, and the live path for a LaTeX run.

        `generate_report_review` covers markdown output and `generate_layout_review`
        covers LaTeX; the manager calls whichever the run's format selects, so pinning
        only one leaves the other exclusion held by nothing at all.
        """
        from src.writing_manifest import generate_layout_review

        stage = self.start(7)
        before = self.files_of_kind("artifacts")
        generate_layout_review(self.paths)
        self.assert_the_harness_earned_nothing(stage, "artifacts", before)

    def test_the_comment_ledger_is_not_stage_08s_reviews(self) -> None:
        """`record_comment_round` closes an anchored-revision round before scoring.

        Driven through the shipped writer, like every other case in this class. It used
        to hand-place the file, which meant renaming what `record_round` emits would have
        left this green while quietly reopening the hole the class exists to close.
        """
        from src.stage_comments import StageComment, record_round

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        record_round(
            self.paths,
            stage,
            1,
            [
                StageComment(
                    comment_id="C001",
                    quote="x" * 40,
                    comment="The readiness checklist does not name the venue." + "y" * 40,
                    required_change="Name it." + "z" * 40,
                )
            ],
        )
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_panel_transcripts_are_not_stage_08s_reviews(self) -> None:
        """`ReviewPanel._record` writes one transcript pair per stage per attempt.

        It runs from `_collect_review_decision`, which is *after* attempt N is scored
        and therefore before attempt N+1 is. Excluded as a subtree rather than by name
        because the names carry the attempt number, so listing them would leak every
        attempt after the one that was listed.
        """
        from src.review_panel import ReviewPanel

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        panel = ReviewPanel(backend_name="claude", model="sonnet", fake_mode=True)
        panel._record(self.paths, self.panel_deliberation(stage, 2))
        written = self.assert_the_harness_earned_nothing(stage, "reviews", before)
        self.assertTrue(
            any(path.name.endswith("_attempt_02.json") for path in written),
            f"the panel wrote no per-attempt transcript: {[p.name for p in written]}",
        )

    def test_the_panel_effect_ledger_is_not_stage_08s_reviews(self) -> None:
        """The least flattering file the panel writes about itself is still its own."""
        from src.review_panel import record_panel_effect

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        record_panel_effect(self.paths, self.panel_deliberation(stage, 1))
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_effort_ledger_is_not_stage_08s_reviews(self) -> None:
        """`_note_effort_failure` writes it on the branch where the panel refused."""
        from src.effort import EffortPlan, record_plan

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        record_plan(self.paths, EffortPlan(enabled=True))
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_deliberation_ledger_is_not_stage_08s_reviews(self) -> None:
        """`_settle_cruxes` writes it one statement above the call that scores."""
        from src.deliberation import Position, Resolution, parse_requests, record_resolution

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        request = parse_requests(
            {
                "question": "Should the control arm be matched on age?",
                "why_it_matters": "Every downstream estimate is conditioned on it.",
                "already_considered": ["stratifying instead"],
                "working_answer": "match on age",
                "help_wanted": "both",
            },
            stage=stage,
        )[0]
        record_resolution(
            self.paths,
            stage,
            Resolution(
                request=request,
                positions=[
                    Position(
                        voice="theorist",
                        title="Theorist",
                        backend="claude",
                        model="sonnet",
                        answer="Match, and report the unmatched estimate beside it.",
                    )
                ],
                answer="Match, and report the unmatched estimate beside it.",
                reason="The unmatched estimate is the sensitivity check.",
                falsifier="A matched and an unmatched estimate that disagree in sign.",
                dissent="",
                voice_calls=3,
                changed_the_answer=True,
            ),
        )
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_scorecard_is_not_stage_08s_reviews(self) -> None:
        """Excluded on ownership rather than on ordering.

        `_report_optional_machinery` currently runs from `_complete_run`, after the
        last score of the walk. That ordering is not the scorecard's to keep — a
        resumed run re-opens a stage window with this file already on disk — and the
        run's summary of its own optional features was never Stage 08's output.
        """
        from src.scorecard import write_scorecard

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        write_scorecard(self.paths, "standard")
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_validity_review_is_not_the_reviewed_stages_reviews(self) -> None:
        """The adversarial reviewer's findings are *about* the stage, not by it."""
        from src.validity_review import ValidityFinding, ValidityReviewer

        stage = self.start(8)
        before = self.files_of_kind("reviews")
        ValidityReviewer(operator=None)._write_review(
            self.paths,
            stage,
            [
                ValidityFinding(
                    identifier="V1",
                    category="confounding",
                    severity="major",
                    finding="The control arm is not matched on age.",
                    why_it_matters="Every downstream estimate is conditioned on it.",
                    what_would_settle_it="A matched and an unmatched estimate, side by side.",
                )
            ],
            note="one finding",
        )
        self.assert_the_harness_earned_nothing(stage, "reviews", before)

    def test_the_stages_own_review_asset_beside_the_ledger_still_counts(self) -> None:
        """The control, so the exclusion cannot over-broaden into dropping output.

        Every AutoR write the class above drives is in this tree at once, and the one
        file the *stage* wrote still earns the kind on its own.
        """
        from src.effort import EffortPlan, record_plan
        from src.review_panel import record_panel_effect
        from src.scorecard import write_scorecard
        from src.stage_comments import COMMENT_LEDGER_FILENAME

        stage = self.start(8)
        write_text(self.paths.reviews_dir / COMMENT_LEDGER_FILENAME, json.dumps({"rounds": []}))
        record_plan(self.paths, EffortPlan(enabled=True))
        record_panel_effect(self.paths, self.panel_deliberation(stage, 1))
        write_scorecard(self.paths, "standard")
        _, without = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertNotIn("reviews", without)

        write_text(self.paths.reviews_dir / "readiness_checklist.md", "# Readiness\n" + "x" * 200)
        _, fresh = _fresh_artifact_kinds(self.paths, stage, None)
        self.assertIn("reviews", fresh)

    def test_the_agents_answer_to_the_review_is_the_agents(self) -> None:
        """`validity_response_<stage>.json` sits beside `validity_review_<stage>.json`.

        One is written by the reviewer and one by the stage answering it. An exclusion
        that globbed `validity_*` would take both and silently drop real output.
        """
        from src.validity_review import validity_response_path

        stage = self.start(6)
        write_text(
            validity_response_path(self.paths, "05_experimentation"),
            json.dumps({"responses": [{"id": "V1", "answer": "Matched; both estimates shipped."}]}),
        )
        self.assertFalse(_harness_written_records(self.paths).covers(
            validity_response_path(self.paths, "05_experimentation")
        ))


# ---------------------------------------------------------------------------
# The census
# ---------------------------------------------------------------------------

#: Directory attributes on ``RunPaths`` that ``artifact_breadth`` now reads and that
#: ``RECORD_ARTIFACTS`` does not already cover. ``data``/``results``/``figures``/
#: ``code``/``writing`` are excluded: the criterion read them before this change and
#: the experiment bundle's own exclusion list is what guards them.
GRADED_DIR_ATTRS = {
    "literature_dir": "literature",
    "notes_dir": "notes",
    "artifacts_dir": "artifacts",
    "reviews_dir": "reviews",
}

#: What the scan prints where a path segment is built at runtime.
DYNAMIC = "{*}"

#: Who owns every ``<paths>.<graded>_dir / <name>`` expression in ``src/``.
#:
#: ``harness`` — AutoR's own machinery writes it, so ``_harness_written_records`` must
#: hide it from ``artifact_breadth``. ``agent`` — the run produced it, or nothing in
#: ``src/`` writes it at all, and the criterion is supposed to see it if it appears.
#: The third column is a concrete relative path to assert against, needed only where
#: the scan found a name assembled at runtime.
#:
#: This table is the point of the census. A new file under a graded directory forces
#: the ownership call in the same commit that adds it, instead of arriving as a free
#: artifact kind nobody noticed — which is exactly how five of the entries below were
#: missing when this criterion first learned to read ``reviews/``.
PATH_OWNERS: tuple[tuple[str, str, str], ...] = (
    # -- the harness's own bookkeeping ------------------------------------------
    ("artifacts/layout_review.json", "harness", ""),
    ("artifacts/report_review.json", "harness", ""),
    # `_load_review_summary(paths, filename)` reads one of the two above.
    ("artifacts/{*}", "harness", "artifacts/report_review.json"),
    ("notes/idea_pool.json", "harness", ""),
    ("notes/idea_pool.md", "harness", ""),
    ("reviews/comment_ledger.json", "harness", ""),
    ("reviews/deliberations.json", "harness", ""),
    ("reviews/effort.json", "harness", ""),
    ("reviews/panel", "harness", "reviews/panel/08_dissemination_attempt_02.json"),
    ("reviews/panel/panel_effect.json", "harness", ""),
    ("reviews/scorecard.json", "harness", ""),
    ("reviews/scorecard.md", "harness", ""),
    ("reviews/validity_review_{*}.json", "harness", "reviews/validity_review_06_analysis.json"),
    # -- the run's own output ----------------------------------------------------
    ("artifacts/build.log", "agent", ""),
    ("artifacts/build_log.txt", "agent", ""),
    ("artifacts/citation_verification.json", "agent", ""),
    ("artifacts/deliverables_coverage.json", "agent", ""),
    ("artifacts/paper.pdf", "agent", ""),
    ("artifacts/paper_package", "agent", ""),
    ("artifacts/paper_package/build.log", "agent", ""),
    ("artifacts/paper_package/paper.pdf", "agent", ""),
    ("artifacts/release_package", "agent", ""),
    ("artifacts/self_review.json", "agent", ""),
    # Written at Stage 01 by a run following `draw-the-source-figure-panel-for-panel`,
    # and read by `source_figure_coverage`. Agent-owned on purpose: the criterion is a
    # gradient for runs that record what the source published, and absent it scores 1.0.
    ("notes/source_figures.json", "agent", ""),
    ("literature/claims.json", "agent", ""),
    ("literature/sources.json", "agent", ""),
    # Written by `--fake-operator`, which stands in for the agent. Excluding these
    # would make a scripted run score differently from the real one it simulates.
    ("notes/autor_intro.md", "agent", ""),
    ("notes/{*}_fake_operator_note.md", "agent", "notes/03_study_design_fake_operator_note.md"),
    ("notes/deliberation_request.json", "agent", ""),
    ("notes/hypotheses.md", "agent", ""),
    ("reviews/readiness_review.json", "agent", ""),
    ("reviews/release_package", "agent", ""),
    ("reviews/validity_response_{*}.json", "agent", "reviews/validity_response_05_experimentation.json"),
    # `settled_reasoning.rejected_candidates` reads the ideation pool from `reviews/`
    # while `record_idea_pool` writes it to `notes/`, so nothing in the tree produces
    # this path. Recorded rather than repaired: the reader is a separate defect and
    # this census says where a name is addressed, not whether the address is right.
    ("reviews/idea_pool.json", "agent", ""),
)


def _string_constants(tree: ast.Module) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, which is how filenames are declared."""
    constants: dict[str, str] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
        ):
            constants[target.id] = value.value
    return constants


def _imported_constants(tree: ast.Module) -> dict[str, str]:
    """Follow ``from .effort import LEDGER_FILENAME as EFFORT_FILENAME`` one hop.

    One hop is enough because every filename in this repo is declared at the module
    that writes it, and an alias that resolves to nothing simply reads as dynamic —
    which the table then has to declare explicitly rather than silently skip.
    """
    resolved: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level == 0 or not node.module:
            continue
        source = REPO / "src" / (node.module.replace(".", "/") + ".py")
        if not source.is_file():
            continue
        origin = _string_constants(ast.parse(source.read_text(encoding="utf-8")))
        for alias in node.names:
            if alias.name in origin:
                resolved[alias.asname or alias.name] = origin[alias.name]
    return resolved


def _segment(node: ast.expr, names: dict[str, str]) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return names.get(node.id, DYNAMIC)
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else DYNAMIC for part in node.values
        )
    return DYNAMIC


def census_of_graded_paths() -> dict[str, list[str]]:
    """Every path expression in ``src/`` rooted at a graded directory, and where it is.

    Read off the syntax rather than off a list of writers, because the thing that goes
    wrong is a writer nobody remembered. Reads are included as well as writes: telling
    them apart statically is unreliable, and a read is the cheapest evidence that a
    name exists at all.
    """
    found: dict[str, list[str]] = {}
    for path in sorted((REPO / "src").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {**_imported_constants(tree), **_string_constants(tree)}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)):
                continue
            segments = [node.right]
            base = node.left
            while isinstance(base, ast.BinOp) and isinstance(base.op, ast.Div):
                segments.insert(0, base.right)
                base = base.left
            if not (isinstance(base, ast.Attribute) and base.attr in GRADED_DIR_ATTRS):
                continue
            key = "/".join(
                [GRADED_DIR_ATTRS[base.attr]] + [_segment(item, names) for item in segments]
            )
            found.setdefault(key, []).append(f"{path.relative_to(REPO)}:{node.lineno}")
    return found


class TheCensusOfWhoWritesUnderAGradedDirectoryTests(unittest.TestCase):
    """The exclusion list was incomplete, and nothing could have said so.

    `_harness_written_records` is a list someone has to remember to extend. This class
    is the thing that remembers: it re-derives, from `src/` itself, every name addressed
    under a directory `artifact_breadth` grades, and refuses one that `PATH_OWNERS` has
    not classified — in either direction, so an over-broad exclusion that swallows the
    run's own output fails here too.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")

    def sample_path(self, key: str, sample: str) -> Path:
        return self.paths.run_root / "workspace" / (sample or key)

    def test_every_path_under_a_graded_directory_has_a_declared_owner(self) -> None:
        found = census_of_graded_paths()
        declared = {key for key, _, _ in PATH_OWNERS}

        undeclared = sorted(set(found) - declared)
        self.assertEqual(
            undeclared,
            [],
            "\n".join(
                f"{key} is addressed at {', '.join(sorted(set(found[key])))} and PATH_OWNERS "
                "does not say whether AutoR or the run writes it"
                for key in undeclared
            ),
        )
        stale = sorted(declared - set(found))
        self.assertEqual(stale, [], f"PATH_OWNERS names paths nothing addresses: {stale}")

    def test_every_harness_path_is_hidden_and_every_agent_path_is_not(self) -> None:
        harness = _harness_written_records(self.paths)
        for key, owner, sample in PATH_OWNERS:
            with self.subTest(path=key):
                covered = harness.covers(self.sample_path(key, sample))
                if owner == "harness":
                    self.assertTrue(
                        covered,
                        f"{key} is AutoR's own record and artifact_breadth would pay a stage "
                        "for it",
                    )
                else:
                    self.assertFalse(
                        covered,
                        f"{key} is the run's output and the exclusion has swallowed it",
                    )

    def test_the_census_finds_the_writers_this_class_exists_for(self) -> None:
        """A scan that resolved nothing would pass every assertion above vacuously."""
        found = census_of_graded_paths()
        for key in (
            "reviews/effort.json",
            "reviews/deliberations.json",
            "reviews/scorecard.json",
            "reviews/panel",
            "notes/idea_pool.json",
            "artifacts/layout_review.json",
        ):
            self.assertIn(key, found, "the scan stopped resolving module constants")
        self.assertIn(
            "src/effort.py",
            " ".join(found["reviews/effort.json"]),
            "the scan no longer reaches the module that writes the effort ledger",
        )
        self.assertLess(
            sum(1 for key in found if DYNAMIC in key),
            len(found) / 2,
            "over half the scan is unresolved; the resolver has stopped working",
        )


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

    def test_stage_08_was_always_writing_to_one_of_the_five_old_directories(self) -> None:
        """The premise, stated precisely: 08 was half-visible, not invisible.

        `08_dissemination.md` names the writing directory as well as `artifacts/` and
        `reviews/`, so the criterion could see one third of what the stage produces.
        The module docstring says so, and this is the assertion behind that sentence.
        """
        named = self.kinds_named_by(STAGE[8])
        self.assertEqual(named & {"data", "results", "figures", "code", "writing"}, {"writing"})
        self.assertEqual(self.kinds_named_by(STAGE[1]) & {"data", "results", "figures", "code", "writing"}, set())
        self.assertEqual(self.kinds_named_by(STAGE[2]) & {"data", "results", "figures", "code", "writing"}, set())

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
