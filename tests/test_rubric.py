"""The fitness function, and the property the self-improvement loop rests on.

Most of these are about what the rubric *refuses* to reward. A score that only
goes up when the work gets better is not demonstrated by scoring good work highly;
it is demonstrated by scoring padded prose, invented numbers and a rewritten
conclusion exactly as low as they deserve. The last of those is the one that
matters: a scored loop pointed at a fitness function that notices which way a
result went is an automated p-hacker with a budget.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from src.rubric import (
    RUBRIC_VERSION,
    CRITERIA_BY_KEY,
    StageScore,
    format_score_for_prompt,
    score_stage,
    verdict_digest,
)
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    mark_stage_execution_started,
    read_text,
    write_text,
)
from tests import prereg_support


STAGE_01 = next(stage for stage in STAGES if stage.number == 1)
STAGE_05 = next(stage for stage in STAGES if stage.number == 5)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)


def stage_markdown(
    stage,
    *,
    what_i_did: str = "Ran the sweep in `workspace/code/run_sweep.py` over five seeds.",
    key_results: str = "Accuracy reached 74.1% against a 58.2% baseline over 5 seeds.",
    files: str = "- `workspace/results/metrics.json`\n- `workspace/code/run_sweep.py`",
    ledger: str | None = None,
) -> str:
    ledger = ledger or (
        "- Open Questions: whether the effect survives a larger context window.\n"
        "- Locked Decisions: the held-out split is frozen at the 2024 partition.\n"
        "- Assumptions: the retrieval index is complete for the evaluation period.\n"
        "- Rejected Alternatives: fine-tuning the base model, which the budget cannot cover.\n"
    )
    return (
        f"# {stage.stage_title}\n\n"
        "## Objective\n\nEstablish the effect.\n\n"
        "## Previously Approved Stage Summaries\n\nNone yet.\n\n"
        f"## What I Did\n\n{what_i_did}\n\n"
        f"## Key Results\n\n{key_results}\n\n"
        f"## Files Produced\n\n{files}\n\n"
        f"## Decision Ledger\n\n{ledger}\n"
        "## Suggestions for Refinement\n\n"
        "1. Add a second baseline.\n2. Widen the sweep.\n3. Record per-seed variance.\n\n"
        "## Your Options\n\n"
        "1. Use suggestion 1\n2. Use suggestion 2\n3. Use suggestion 3\n"
        "4. Refine with your own feedback\n5. Approve and continue\n6. Abort\n"
    )


class RubricTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def build_complete_run(self) -> None:
        """A run carrying every artifact the validity chain expects at Stage 06."""
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.write_experimental_protocol(self.paths)
        write_text(self.paths.code_dir / "run_sweep.py", "print('sweep')\n" * 5)
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps({"baseline": 0.582, "treatment": 0.741, "seeds": 5}),
        )
        write_text(self.paths.data_dir / "splits.json", json.dumps({"test": list(range(40))}))
        write_text(self.paths.figures_dir / "effect.png", "x" * 200)
        write_text(
            self.paths.literature_dir / "evidence_ledger.json",
            json.dumps({"entries": [{"claim": "prior work", "source": "smith2024"}]}),
        )
        prereg_support.freeze_preregistration(self.paths)
        write_text(
            self.paths.experiment_manifest,
            json.dumps({"experiments": [{"id": "e1", "command": "python run_sweep.py", "seeds": 5}]}),
        )
        self.write_outcomes("supported")

    def write_outcomes(self, verdict: str) -> None:
        prereg = json.loads(self.paths.preregistration.read_text(encoding="utf-8"))
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps(
                {
                    "preregistration_digest": prereg["digest"],
                    "outcomes": [
                        {
                            "id": prereg_support.HYPOTHESIS_ID,
                            "verdict": verdict,
                            "rationale": "The held-out gap exceeds the decision rule threshold.",
                            "evidence": ["results/metrics.json"],
                        }
                    ],
                }
            ),
        )

    # -- the property the loop depends on ------------------------------------

    def test_flipping_every_verdict_does_not_move_the_score(self) -> None:
        """Outcome blindness, measured end to end rather than argued for.

        The construction guard in `_verdict_blind_outcomes` is where the property
        is enforced; this is the control that proves the guard is on the path a
        real score takes. Written against the artifact on disk, so a criterion
        added later that reads `hypothesis_outcomes.json` directly fails here.
        """
        self.build_complete_run()
        markdown = stage_markdown(STAGE_06)

        totals = {}
        for verdict in ("supported", "refuted", "inconclusive", "not_tested"):
            self.write_outcomes(verdict)
            totals[verdict] = score_stage(
                paths=self.paths, stage=STAGE_06, markdown=markdown
            ).total

        self.assertEqual(
            len(set(round(value, 9) for value in totals.values())),
            1,
            msg=f"the rubric preferred an outcome: {totals}",
        )

    def test_the_verdict_digest_moves_when_a_verdict_does(self) -> None:
        """Drift detection is only useful if it detects drift.

        The mirror of the test above: the *score* must not move and the *digest*
        must. One without the other is a loop that either cannot improve evidence
        or cannot notice a rewritten conclusion.
        """
        self.build_complete_run()
        before = verdict_digest(self.paths)
        self.write_outcomes("refuted")
        self.assertNotEqual(before, verdict_digest(self.paths))
        self.assertTrue(before)

    # -- criteria that must not be gameable ----------------------------------

    def test_padding_prose_does_not_raise_the_score(self) -> None:
        self.build_complete_run()
        lean = stage_markdown(STAGE_06)
        padded = stage_markdown(
            STAGE_06,
            what_i_did=(
                "Ran the sweep in `workspace/code/run_sweep.py` over five seeds. "
                + "The methodology was applied with considerable care and rigour throughout. " * 40
            ),
        )
        self.assertLessEqual(
            score_stage(paths=self.paths, stage=STAGE_06, markdown=padded).total,
            score_stage(paths=self.paths, stage=STAGE_06, markdown=lean).total + 1e-9,
        )

    def test_a_number_that_appears_in_no_artifact_is_caught(self) -> None:
        """The deep-review check: a fluent write-up quoting a metric nothing measured.

        Every other gate passes this draft. Its sections are present, the files it
        names exist, the prose is quantified — the number is simply invented.
        """
        self.build_complete_run()
        honest = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results="Accuracy reached 74.1% from 58.2%."),
        )
        invented = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results="Accuracy reached 91.7% from 58.2%."),
        )
        self.assertEqual(honest.by_key["numeric_fidelity"].score, 1.0)
        self.assertLess(invented.by_key["numeric_fidelity"].score, 1.0)
        self.assertIn("91.7", invented.by_key["numeric_fidelity"].shortfall)

    def test_a_percentage_is_matched_against_its_fraction(self) -> None:
        """`74.1%` is the same measurement as `0.741`, and a rubric that says
        otherwise would send every polish round after a number that is already right."""
        self.build_complete_run()
        score = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results="Accuracy reached 74.1%, over 58.2%."),
        )
        self.assertEqual(score.by_key["numeric_fidelity"].score, 1.0)

    def test_a_reference_that_does_not_resolve_lowers_grounding(self) -> None:
        self.build_complete_run()
        resolving = score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        broken = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(
                STAGE_06,
                what_i_did="Wrote `workspace/results/ablation.json`, which does not exist.",
            ),
        )
        self.assertLess(broken.by_key["grounding"].score, resolving.by_key["grounding"].score)
        self.assertIn("ablation.json", broken.by_key["grounding"].shortfall)

    def test_a_decision_ledger_repeating_itself_scores_below_a_real_one(self) -> None:
        self.build_complete_run()
        real = score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        repeated = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(
                STAGE_06,
                ledger=(
                    "- Open Questions: the approach seems reasonable overall.\n"
                    "- Locked Decisions: the approach seems reasonable overall.\n"
                    "- Assumptions: the approach seems reasonable overall.\n"
                    "- Rejected Alternatives: None\n"
                ),
            ),
        )
        self.assertLess(
            repeated.by_key["traceability"].score, real.by_key["traceability"].score
        )

    def test_a_stage_describing_intentions_scores_below_one_reporting_work(self) -> None:
        self.build_complete_run()
        done = score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        planned = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(
                STAGE_06,
                what_i_did=(
                    "We will run the sweep in `workspace/code/run_sweep.py`. We plan to measure "
                    "accuracy. The design is intended to isolate the effect and should improve "
                    "over the baseline. The ablation is to be run next."
                ),
            ),
        )
        self.assertLess(planned.by_key["commitment"].score, done.by_key["commitment"].score)

    def test_autors_own_bookkeeping_is_not_the_stages_output(self) -> None:
        """`write_experiment_manifest` runs on the way *into* every stage from 05 on —
        `information_flow` declares the manifest as an inbound channel — so it is
        rewritten inside the stage's own execution window on every run. Counted as
        output, a Stage 05 that produced literally nothing scored a third of
        `artifact_breadth` off a file whose own body reads `result_artifact_count: 0`.

        `_score_reproducibility` already read the same file's empty `result_artifacts`
        and penalised the stage for it, so the rubric was crediting and debiting one
        artifact at once.
        """
        from src.experiment_manifest import write_experiment_manifest

        mark_stage_execution_started(self.paths, STAGE_05)
        time.sleep(0.02)
        write_experiment_manifest(self.paths)

        manifest = json.loads(read_text(self.paths.experiment_manifest))
        self.assertEqual(manifest.get("result_artifacts"), [])
        score = score_stage(paths=self.paths, stage=STAGE_05, markdown=stage_markdown(STAGE_05))
        self.assertEqual(score.by_key["artifact_breadth"].score, 0.0)

    def test_a_real_result_beside_the_bookkeeping_still_counts(self) -> None:
        """The control, so the exclusion cannot over-broaden into dropping output."""
        from src.experiment_manifest import write_experiment_manifest

        mark_stage_execution_started(self.paths, STAGE_05)
        time.sleep(0.02)
        write_experiment_manifest(self.paths)
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps({"baseline": 0.58, "treatment": 0.74, "seeds": [1, 2, 3, 4, 5]}),
        )
        score = score_stage(paths=self.paths, stage=STAGE_05, markdown=stage_markdown(STAGE_05))
        self.assertGreater(score.by_key["artifact_breadth"].score, 0.0)

    # -- structure -----------------------------------------------------------

    def test_criteria_that_cannot_apply_are_not_scored_as_failures(self) -> None:
        """Stage 01 has no experiment manifest to produce and must not be graded as
        if it failed to produce one, or the ratchet would prefer late stages for a
        reason with nothing to do with their quality."""
        score = score_stage(paths=self.paths, stage=STAGE_01, markdown=stage_markdown(STAGE_01))
        self.assertNotIn("numeric_fidelity", score.by_key)
        self.assertNotIn("artifact_breadth", score.by_key)
        self.assertIn("grounding", score.by_key)

    def test_weakest_orders_by_recoverable_weight_not_raw_score(self) -> None:
        score = StageScore(
            stage_slug="06_analysis",
            attempt_no=1,
            rubric_version=RUBRIC_VERSION,
            criteria=(
                _criterion("traceability", 0.4, weight=1.5),
                _criterion("grounding", 0.6, weight=3.0),
                _criterion("contract", 1.0, weight=2.0),
            ),
            total=0.6,
        )
        weakest = score.weakest()
        self.assertEqual([item.key for item in weakest], ["grounding", "traceability"])
        self.assertNotIn("contract", [item.key for item in weakest])

    def test_a_saturated_criterion_carries_no_shortfall(self) -> None:
        """A directive built from a criterion at full marks asks for churn."""
        self.build_complete_run()
        score = score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        for item in score.criteria:
            if item.score >= 1.0:
                self.assertEqual(item.shortfall, "", msg=f"{item.key} is saturated but asks for work")

    def test_a_score_round_trips_through_json(self) -> None:
        self.build_complete_run()
        score = score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        restored = StageScore.from_dict(json.loads(json.dumps(score.to_dict())))
        self.assertEqual(restored.rubric_version, score.rubric_version)
        self.assertAlmostEqual(restored.total, score.total, places=4)
        self.assertEqual(
            {item.key: round(item.score, 4) for item in restored.criteria},
            {item.key: round(item.score, 4) for item in score.criteria},
        )

    def test_the_prompt_rendering_names_the_shortfall_not_only_the_number(self) -> None:
        self.build_complete_run()
        score = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results="Accuracy reached 91.7%."),
        )
        rendered = format_score_for_prompt(score)
        self.assertIn("91.7", rendered)
        self.assertIn("Where the points are", rendered)

    def test_scoring_does_not_write_anything(self) -> None:
        """The rubric is read by a loop that reverts drafts. A scorer with a side
        effect would make the measurement depend on how many times it was taken."""
        self.build_complete_run()
        before = sorted(p.relative_to(self.paths.run_root).as_posix() for p in self.paths.run_root.rglob("*"))
        score_stage(paths=self.paths, stage=STAGE_06, markdown=stage_markdown(STAGE_06))
        after = sorted(p.relative_to(self.paths.run_root).as_posix() for p in self.paths.run_root.rglob("*"))
        self.assertEqual(before, after)


class FabricationMustNotPayTest(RubricTestCase):
    """Inventing numbers scored two weighted points above honestly reporting none.

    `quantification` counts numbers in Key Results; `numeric_fidelity` checks them
    against artifacts the draft did not write. Scored independently and summed, a
    draft quoting six invented metrics collected the first and merely failed to
    collect the second — so the composite *paid* for fabrication, and the champion
    ratchet in `src.evolution` promotes on the composite. That is the failure the
    module docstring says the whole design exists to prevent.
    """

    SILENT = "The method is better than the baseline on the held-out split."
    NUMBERS = (
        "Accuracy reached 0.912 against a baseline of 0.874, a gain of 3.8 points "
        "over 5 seeds with a standard deviation of 0.007."
    )

    def _total(self, key_results: str, *, metrics: dict | None) -> float:
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps(metrics if metrics is not None else {"note": "nothing citable"}),
        )
        return score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results=key_results),
        ).total

    def test_invented_numbers_score_no_higher_than_saying_nothing(self) -> None:
        silent = self._total(self.SILENT, metrics=None)
        invented = self._total(self.NUMBERS, metrics=None)
        self.assertLessEqual(invented, silent)

    def test_numbers_that_check_out_still_score_higher_than_both(self) -> None:
        silent = self._total(self.SILENT, metrics=None)
        real = self._total(
            self.NUMBERS,
            metrics={"accuracy": 0.912, "baseline": 0.874, "gain": 3.8, "seeds": 5, "std": 0.007},
        )
        self.assertGreater(real, silent)

    def test_the_cap_is_recorded_rather_than_silent(self) -> None:
        """A stage told only the capped number cannot tell which half to fix."""
        self._total(self.NUMBERS, metrics=None)
        score = score_stage(
            paths=self.paths,
            stage=STAGE_06,
            markdown=stage_markdown(STAGE_06, key_results=self.NUMBERS),
        )
        quantification = next(c for c in score.criteria if c.key == "quantification")
        self.assertIn("capped at numeric fidelity", quantification.observed)

    def test_stage_04_is_not_capped_because_fidelity_does_not_apply_there(self) -> None:
        """Implementation reports parameter counts before any result exists."""
        stage_04 = next(stage for stage in STAGES if stage.number == 4)
        score = score_stage(
            paths=self.paths,
            stage=stage_04,
            markdown=stage_markdown(stage_04, key_results=self.NUMBERS),
        )
        self.assertNotIn("numeric_fidelity", {c.key for c in score.criteria})
        quantification = next(c for c in score.criteria if c.key == "quantification")
        self.assertGreater(quantification.score, 0.0)


def _criterion(key: str, score: float, *, weight: float):
    from src.rubric import CriterionScore

    return CriterionScore(
        key=key,
        title=CRITERIA_BY_KEY[key].title,
        weight=weight,
        score=score,
        observed="synthetic",
        shortfall="raise it",
    )


if __name__ == "__main__":
    unittest.main()
