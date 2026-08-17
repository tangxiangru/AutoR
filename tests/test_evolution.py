"""The ratchet: what may stand, what is reverted, and what is never allowed to win.

The three properties worth having are all negative. A round that scores worse does
not survive. A round that changed the run's conclusion does not survive whatever it
scores. And a round a *person* asked for survives whatever it scores, because the
measurement is not entitled to overrule the human whose project this is.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.evolution import EvolutionConfig, EvolutionController, load_run_fitness
from src.pareto import complementary_pair, dominates, frontier, insert
from src.rubric import RUBRIC_VERSION, CriterionScore, StageScore
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text
from tests import prereg_support
from tests.test_rubric import stage_markdown


STAGE_06 = next(stage for stage in STAGES if stage.number == 6)


class RatchetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        self.controller = EvolutionController(EvolutionConfig(rounds=3))
        self.build_run()

    def build_run(self) -> None:
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.write_experimental_protocol(self.paths)
        write_text(self.paths.code_dir / "run_sweep.py", "print('x')\n" * 4)
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps({"baseline": 0.582, "treatment": 0.741, "seeds": 5}),
        )
        write_text(self.paths.data_dir / "splits.json", json.dumps({"test": [1, 2, 3]}))
        write_text(self.paths.figures_dir / "effect.png", "x" * 128)
        write_text(
            self.paths.literature_dir / "evidence_ledger.json", json.dumps({"entries": [{"claim": "c"}]})
        )
        write_text(
            self.paths.experiment_manifest,
            json.dumps({"experiments": [{"id": "e1", "command": "python run_sweep.py"}]}),
        )
        prereg_support.freeze_preregistration(self.paths)
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
                            "rationale": "The gap sits either side of the decision rule.",
                            "evidence": ["results/metrics.json"],
                        }
                    ],
                }
            ),
        )

    def offer(
        self, markdown: str, attempt_no: int, *, polish: bool = True, directed_by: str = "human"
    ):
        draft = self.paths.stage_tmp_file(STAGE_06)
        write_text(draft, markdown)
        return self.controller.consider(
            paths=self.paths,
            stage=STAGE_06,
            attempt_no=attempt_no,
            draft_path=draft,
            is_polish_round=polish,
            directed_by=directed_by,
        )

    # -- the ratchet ---------------------------------------------------------

    def test_a_worse_polish_round_is_reverted_to_the_champion(self) -> None:
        strong = stage_markdown(STAGE_06)
        self.offer(strong, 1, polish=False)

        weak = stage_markdown(
            STAGE_06,
            key_results="Things improved.",
            what_i_did="We will run the sweep and should improve the baseline.",
        )
        outcome = self.offer(weak, 2)

        self.assertEqual(outcome.verdict, "regressed")
        self.assertTrue(outcome.reverted)
        self.assertEqual(read_text(self.paths.stage_tmp_file(STAGE_06)).strip(), strong.strip())

    def test_a_better_polish_round_becomes_the_champion(self) -> None:
        self.offer(
            stage_markdown(STAGE_06, key_results="Things improved.", files="- `workspace/results/metrics.json`"),
            1,
            polish=False,
        )
        outcome = self.offer(stage_markdown(STAGE_06), 2)
        self.assertEqual(outcome.verdict, "promoted")
        self.assertGreater(outcome.delta, 0)
        self.assertFalse(outcome.reverted)

    def test_a_polish_round_that_moves_a_verdict_is_rejected_whatever_it_scores(self) -> None:
        """The failure a scored loop introduces and nothing else in AutoR would see.

        The rubric is blind to verdicts, so a rewritten conclusion scores the same;
        that is exactly why the drift check cannot be a score comparison.
        """
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        self.write_outcomes("refuted")
        outcome = self.offer(stage_markdown(STAGE_06), 2)

        self.assertEqual(outcome.verdict, "verdict_drift")
        self.assertTrue(outcome.reverted)
        rows = [
            json.loads(line)
            for line in read_text(self.controller.ledger_file(self.paths)).splitlines()
            if line.strip()
        ]
        self.assertEqual(rows[-1]["verdict"], "verdict_drift")

    def test_a_directed_revision_stands_even_when_it_measures_worse(self) -> None:
        """A human asking for a change is direction, not an optimisation step.

        AutoR silently reverting a requested edit because a rubric preferred the
        previous wording is the opposite of the arrangement this project is built
        on. The delta is still recorded, so the ledger says whether it helped.
        """
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        weak = stage_markdown(STAGE_06, key_results="Things improved.")
        outcome = self.offer(weak, 2, polish=False)

        self.assertEqual(outcome.verdict, "directed")
        self.assertFalse(outcome.reverted)
        self.assertLess(outcome.delta, 0)
        self.assertEqual(read_text(self.paths.stage_tmp_file(STAGE_06)).strip(), weak.strip())

    def test_an_automated_reviewers_worse_revision_is_reverted(self) -> None:
        """The exemption above is a human's, and a bot was spending it.

        Measured over 41 ResearchClawBench runs, the automated reviewer directed 1115
        revisions; 142 of them scored *below* the draft they replaced and every one was
        promoted, because the branch could not tell a person's judgement from another
        instance of the same model reading the same draft.
        """
        strong = stage_markdown(STAGE_06)
        self.offer(strong, 1, polish=False)
        weak = stage_markdown(STAGE_06, key_results="Things improved.")
        outcome = self.offer(weak, 2, polish=False, directed_by="reviewer")

        self.assertEqual(outcome.verdict, "directed_regressed")
        self.assertTrue(outcome.reverted)
        self.assertLess(outcome.delta, 0)
        self.assertEqual(read_text(self.paths.stage_tmp_file(STAGE_06)).strip(), strong.strip())

    def test_an_automated_reviewers_flat_revision_still_stands(self) -> None:
        """71% of those 1115 rounds measured exactly 0.000, and those are the case the
        exemption is for: a request the rubric cannot see is not a request that failed.
        Reverting them would make the rubric the reviewer."""
        markdown = stage_markdown(STAGE_06)
        self.offer(markdown, 1, polish=False)
        outcome = self.offer(markdown, 2, polish=False, directed_by="reviewer")

        self.assertEqual(outcome.delta, 0.0)
        self.assertEqual(outcome.verdict, "directed")
        self.assertFalse(outcome.reverted)

    def test_an_automated_reviewers_better_revision_stands(self) -> None:
        weak = stage_markdown(STAGE_06, key_results="Things improved.")
        self.offer(weak, 1, polish=False)
        strong = stage_markdown(STAGE_06)
        outcome = self.offer(strong, 2, polish=False, directed_by="reviewer")

        self.assertEqual(outcome.verdict, "directed")
        self.assertFalse(outcome.reverted)
        self.assertGreater(outcome.delta, 0)

    def test_the_reverted_reviewer_round_spends_patience(self) -> None:
        """Otherwise a reviewer could hold a stage open forever: `should_continue` stops
        on `flat_rounds >= patience`, and a round that resets the counter is a round that
        buys the next one."""
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        before = self.controller.state(self.paths, STAGE_06).flat_rounds
        self.offer(
            stage_markdown(STAGE_06, key_results="Things improved."),
            2, polish=False, directed_by="reviewer",
        )
        self.assertEqual(self.controller.state(self.paths, STAGE_06).flat_rounds, before + 1)

    def test_a_reverted_reviewer_round_does_not_move_the_recorded_verdict(self) -> None:
        """The champion is what stands, so the digest that describes it must not advance
        past it -- a drift check comparing against a digest no draft on disk holds would
        fire on the next round for a change this one already undid."""
        strong = stage_markdown(STAGE_06)
        self.offer(strong, 1, polish=False)
        digest = self.controller.state(self.paths, STAGE_06).verdict_digest
        self.offer(
            stage_markdown(STAGE_06, key_results="Things improved."),
            2, polish=False, directed_by="reviewer",
        )
        self.assertEqual(self.controller.state(self.paths, STAGE_06).verdict_digest, digest)

    def test_an_automated_reviewer_may_not_move_a_verdict_either(self) -> None:
        """The exemption covered the drift check too, and `docs/framework.md` §5.4 lists
        that as a known hole: "a model-directed revision can move a verdict without
        meeting the check". Verdict-blindness removes the incentive to improve the answer
        and drift rejection removes the reward; a party that steps around one makes both
        decorative. Measured, this fires on 4 of 388 adjacent candidate pairs."""
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        self.write_outcomes("refuted")
        outcome = self.offer(stage_markdown(STAGE_06), 2, polish=False, directed_by="reviewer")

        self.assertEqual(outcome.verdict, "verdict_drift")
        self.assertTrue(outcome.reverted)

    def test_a_human_may_still_move_a_verdict(self) -> None:
        """Unchanged, and deliberately: the ratchet governs AutoR's own rounds, not the
        direction it is given by the person whose project this is."""
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        self.write_outcomes("refuted")
        outcome = self.offer(stage_markdown(STAGE_06), 2, polish=False)

        self.assertEqual(outcome.verdict, "directed")
        self.assertFalse(outcome.reverted)

    def test_a_flat_reviewer_round_does_not_reset_autors_patience(self) -> None:
        """`should_continue` stops a stage on `flat_rounds >= patience`. A directed round
        used to reset that counter unconditionally, so an automated reviewer sending a
        stage back every other round switched the stop off as a side effect -- and 71% of
        its rounds measured exactly 0.000, which makes that the usual case."""
        markdown = stage_markdown(STAGE_06)
        self.offer(markdown, 1, polish=False)
        self.offer(stage_markdown(STAGE_06, key_results="Things improved."), 2)
        flat = self.controller.state(self.paths, STAGE_06).flat_rounds
        self.assertGreater(flat, 0)

        self.offer(markdown, 3, polish=False, directed_by="reviewer")
        self.assertEqual(self.controller.state(self.paths, STAGE_06).flat_rounds, flat)

    def test_a_human_round_still_resets_patience(self) -> None:
        markdown = stage_markdown(STAGE_06)
        self.offer(markdown, 1, polish=False)
        self.offer(stage_markdown(STAGE_06, key_results="Things improved."), 2)
        self.assertGreater(self.controller.state(self.paths, STAGE_06).flat_rounds, 0)

        self.offer(markdown, 3, polish=False)
        self.assertEqual(self.controller.state(self.paths, STAGE_06).flat_rounds, 0)

    def test_a_reviewer_round_that_gains_resets_patience(self) -> None:
        weak = stage_markdown(STAGE_06, key_results="Things improved.")
        self.offer(weak, 1, polish=False)
        self.offer(weak, 2)
        self.assertGreater(self.controller.state(self.paths, STAGE_06).flat_rounds, 0)

        self.offer(stage_markdown(STAGE_06), 3, polish=False, directed_by="reviewer")
        self.assertEqual(self.controller.state(self.paths, STAGE_06).flat_rounds, 0)

    def test_every_candidate_is_kept_including_the_ones_that_lost(self) -> None:
        """A discarded candidate is the only evidence that anything was discarded."""
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        self.offer(stage_markdown(STAGE_06, key_results="Things improved."), 2)
        candidates = sorted(
            (self.controller.stage_dir(self.paths, STAGE_06) / "candidates").glob("attempt_*.md")
        )
        self.assertEqual(len(candidates), 2)

    # -- round scheduling ----------------------------------------------------

    def test_the_round_budget_is_respected(self) -> None:
        controller = EvolutionController(EvolutionConfig(rounds=2))
        self.controller = controller
        self.offer(stage_markdown(STAGE_06, key_results="Things improved."), 1, polish=False)
        spent = 0
        while controller.should_continue(self.paths, STAGE_06):
            controller.begin_round(self.paths, STAGE_06)
            spent += 1
            self.assertLess(spent, 10, msg="should_continue never went false")
        self.assertEqual(spent, 2)

    def test_a_stage_that_stops_responding_stops_being_polished(self) -> None:
        """Most stages are done after one targeted fix. Spending the rest of the
        budget rewording a draft at the ceiling is the common waste."""
        controller = EvolutionController(EvolutionConfig(rounds=8, patience=2))
        self.controller = controller
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        flat = stage_markdown(STAGE_06, key_results="Things improved.")
        controller.begin_round(self.paths, STAGE_06)
        self.offer(flat, 2)
        controller.begin_round(self.paths, STAGE_06)
        self.offer(flat, 3)
        self.assertFalse(controller.should_continue(self.paths, STAGE_06))

    def test_the_directive_names_the_failing_criterion_and_not_the_saturated_ones(self) -> None:
        self.offer(stage_markdown(STAGE_06, key_results="Accuracy reached 91.7%."), 1, polish=False)
        directive = self.controller.next_directive(self.paths, STAGE_06)
        self.assertIn("91.7", directive)
        self.assertIn("Do not change any hypothesis verdict", directive)
        self.assertIn("Do not lengthen a section", directive)

    def test_a_config_that_excludes_a_stage_does_not_polish_it(self) -> None:
        controller = EvolutionController(
            EvolutionConfig(rounds=3, stages=("05_experimentation",))
        )
        self.assertFalse(controller.should_continue(self.paths, STAGE_06))

    # -- persistence ---------------------------------------------------------

    def test_a_resumed_run_keeps_its_champion(self) -> None:
        """Without this the next draft wins by default and the best work the
        earlier session produced is discarded with nothing recording it."""
        strong = stage_markdown(STAGE_06)
        self.offer(strong, 1, polish=False)

        resumed = EvolutionController(EvolutionConfig(rounds=3))
        state = resumed.state(self.paths, STAGE_06)
        self.assertIsNotNone(state.champion)

        draft = self.paths.stage_tmp_file(STAGE_06)
        write_text(draft, stage_markdown(STAGE_06, key_results="Things improved."))
        outcome = resumed.consider(
            paths=self.paths, stage=STAGE_06, attempt_no=2, draft_path=draft, is_polish_round=True
        )
        self.assertEqual(outcome.verdict, "regressed")
        self.assertEqual(read_text(draft).strip(), strong.strip())

    def test_a_champion_from_another_rubric_version_is_discarded_not_defended(self) -> None:
        stale = StageScore(
            stage_slug=STAGE_06.slug,
            attempt_no=1,
            rubric_version="rubric-from-last-year",
            criteria=(),
            total=0.99,
        )
        write_text(
            self.controller.stage_dir(self.paths, STAGE_06) / "champion.json",
            json.dumps(stale.to_dict()),
        )
        fresh = EvolutionController(EvolutionConfig(rounds=1))
        self.assertIsNone(fresh.state(self.paths, STAGE_06).champion)

    def test_the_run_summary_omits_stages_that_were_never_measured(self) -> None:
        """An absent stage averaged in as a failure would drag a topology variant's
        fitness down for work it never did."""
        self.offer(stage_markdown(STAGE_06), 1, polish=False)
        self.controller.finalize_stage(self.paths, STAGE_06)
        fitness = load_run_fitness(self.paths)
        self.assertEqual(set(fitness), {STAGE_06.slug})


def _score(attempt: int, **criteria: float) -> StageScore:
    items = tuple(
        CriterionScore(key, key, weight=1.0, score=value, observed="", shortfall="more")
        for key, value in criteria.items()
    )
    return StageScore(
        stage_slug="06_analysis",
        attempt_no=attempt,
        rubric_version=RUBRIC_VERSION,
        criteria=items,
        total=sum(criteria.values()) / len(criteria),
    )


class FrontierTests(unittest.TestCase):
    """A scalar picks one winner. Two drafts can differ by shape instead of quality."""

    def test_a_draft_better_everywhere_dominates(self) -> None:
        self.assertTrue(dominates(_score(2, a=0.9, b=0.9), _score(1, a=0.5, b=0.5)))
        self.assertFalse(dominates(_score(1, a=0.9, b=0.2), _score(2, a=0.2, b=0.9)))

    def test_an_identical_rerun_does_not_dominate_and_does_not_enter(self) -> None:
        """Floating-point noise on a rerun that changed nothing must not read as a
        strict improvement."""
        first = _score(1, a=0.6, b=0.4)
        self.assertFalse(dominates(_score(2, a=0.6, b=0.4), first))
        self.assertEqual(insert([first], _score(2, a=0.6, b=0.4)).verdict, "duplicate")

    def test_a_specialist_survives_a_lower_total(self) -> None:
        allrounder = _score(1, a=0.7, b=0.7)
        specialist = _score(2, a=1.0, b=0.2)
        kept = frontier([allrounder, specialist])
        self.assertEqual(len(kept), 2)
        self.assertEqual(insert([allrounder], specialist).verdict, "entered")

    def test_scores_from_different_rubric_versions_are_refused_not_coerced(self) -> None:
        """A reweight would otherwise read as every archived draft having moved."""
        current = _score(1, a=0.6, b=0.6)
        other = StageScore("06_analysis", 2, "9", current.criteria, 0.9)
        self.assertFalse(dominates(other, current))
        self.assertEqual(insert([current], other).verdict, "incomparable")

    def test_a_complementary_pair_names_what_each_draft_owns(self) -> None:
        pair = complementary_pair([_score(1, a=1.0, b=0.2), _score(2, a=0.2, b=1.0)])
        self.assertIsNotNone(pair)
        self.assertEqual(pair.left_wins, ("a",))
        self.assertEqual(pair.right_wins, ("b",))
        self.assertGreater(pair.headroom, 0)

    def test_no_complement_when_one_draft_simply_wins(self) -> None:
        self.assertIsNone(complementary_pair([_score(1, a=0.9, b=0.9), _score(2, a=0.5, b=0.5)]))


if __name__ == "__main__":
    unittest.main()
