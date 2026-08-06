"""Stage 02's candidate pool: many agents for divergence, measured as such.

The pool exists to widen what Stage 02 chooses from. So the tests that matter are the ones
that would fail if it stopped widening anything — a pool of five restatements is the
single-pass null in another costume, and the artifact has to be able to say so.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.ideation_panel import (
    ADOPTION_THRESHOLD,
    DEFAULT_LENSES,
    DUPLICATE_THRESHOLD,
    IDEA_POOL_FILENAME,
    Candidate,
    IdeaPool,
    IdeationPanel,
    ProposerLens,
    apply_lens_models,
    format_pool_for_prompt,
    load_idea_pool,
    mark_duplicates,
    measure_adoption,
    record_idea_pool,
    resolve_lenses,
    similarity,
)
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    read_text,
    write_text,
)


STAGE_02 = next(stage for stage in STAGES if stage.slug == "02_hypothesis_generation")

_MECHANISM = (
    "Remittance inflows raise household consumption because they relax liquidity constraints "
    "in credit-poor households."
)
_RESTATED = (
    "Because credit-poor households face liquidity constraints, remittance inflows increase "
    "their consumption."
)
_VARIANT = (
    "Remittance inflows raise household consumption only in economies with shallow financial "
    "markets."
)
_UNRELATED = (
    "The observed correlation is a selection artifact: households that receive remittances "
    "differ systematically in unobserved ways."
)


def _candidate(idea_id: str, proposer: str, statement: str, title: str = "t") -> Candidate:
    return Candidate(
        idea_id=idea_id, proposer=proposer, proposer_title=proposer,
        backend="claude", model="sonnet", title=title, statement=statement,
    )


class SimilarityTests(unittest.TestCase):
    """The threshold is calibrated, so the calibration is what gets pinned."""

    def test_a_rewording_scores_above_the_threshold(self) -> None:
        self.assertGreaterEqual(similarity(_MECHANISM, _RESTATED), DUPLICATE_THRESHOLD)

    def test_a_genuine_variant_scores_below_it(self) -> None:
        self.assertLess(similarity(_MECHANISM, _VARIANT), DUPLICATE_THRESHOLD)

    def test_an_unrelated_claim_scores_near_zero(self) -> None:
        self.assertLess(similarity(_MECHANISM, _UNRELATED), 0.2)

    def test_the_threshold_sits_in_the_gap_it_was_calibrated_for(self) -> None:
        # If someone retunes this, the calibration in the module docstring must move with it.
        self.assertLess(similarity(_MECHANISM, _VARIANT), DUPLICATE_THRESHOLD)
        self.assertGreaterEqual(similarity(_MECHANISM, _RESTATED), DUPLICATE_THRESHOLD)

    def test_similarity_is_symmetric_and_bounded(self) -> None:
        self.assertEqual(similarity(_MECHANISM, _RESTATED), similarity(_RESTATED, _MECHANISM))
        self.assertEqual(similarity(_MECHANISM, _MECHANISM), 1.0)
        self.assertEqual(similarity("", _MECHANISM), 0.0)


class DeduplicationTests(unittest.TestCase):
    def test_a_restatement_collapses_into_the_first_occurrence(self) -> None:
        resolved = mark_duplicates([
            _candidate("mechanism-1", "mechanism", _MECHANISM),
            _candidate("contrarian-1", "contrarian", _RESTATED),
        ])
        self.assertIsNone(resolved[0].duplicate_of)
        self.assertEqual(resolved[1].duplicate_of, "mechanism-1")

    def test_a_different_title_cannot_hide_the_same_claim(self) -> None:
        # Two proposers naming one idea differently is the collapse this must catch, so the
        # title is deliberately excluded from the comparison.
        resolved = mark_duplicates([
            _candidate("mechanism-1", "mechanism", _MECHANISM, title="Liquidity channel"),
            _candidate("contrarian-1", "contrarian", _RESTATED, title="A completely different name"),
        ])
        self.assertEqual(resolved[1].duplicate_of, "mechanism-1")

    def test_a_genuine_variant_survives(self) -> None:
        resolved = mark_duplicates([
            _candidate("mechanism-1", "mechanism", _MECHANISM),
            _candidate("regime-1", "regime", _VARIANT),
        ])
        self.assertIsNone(resolved[1].duplicate_of)

    def test_a_duplicate_never_absorbs_a_later_candidate(self) -> None:
        resolved = mark_duplicates([
            _candidate("a-1", "a", _MECHANISM),
            _candidate("b-1", "b", _RESTATED),
            _candidate("c-1", "c", _RESTATED),
        ])
        # Both restatements point at the original, not at each other.
        self.assertEqual([c.duplicate_of for c in resolved], [None, "a-1", "a-1"])


class PoolEffectTests(unittest.TestCase):
    """The pool must be able to report that the extra proposers added nothing."""

    def test_a_pool_of_restatements_says_it_widened_nothing(self) -> None:
        pool = IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM),
                _candidate("contrarian-1", "contrarian", _RESTATED),
                _candidate("regime-1", "regime", _RESTATED),
            ]),
            baseline_proposer="mechanism",
            proposer_calls=5,
        )
        effect = pool.effect()
        self.assertEqual(effect["distinct"], 1)
        self.assertEqual(effect["collapsed_as_duplicates"], 2)
        self.assertEqual(effect["added_by_other_proposers"], 0)
        self.assertIn("widened nothing", effect["verdict"])

    def test_a_genuinely_diverse_pool_reports_what_was_added(self) -> None:
        pool = IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM),
                _candidate("regime-1", "regime", _VARIANT),
                _candidate("null-1", "null", _UNRELATED),
            ]),
            baseline_proposer="mechanism",
            proposer_calls=5,
        )
        effect = pool.effect()
        self.assertEqual(effect["distinct"], 3)
        self.assertEqual(effect["added_by_other_proposers"], 2)
        self.assertIn("2 of 3 distinct hypotheses", effect["verdict"])

    def test_an_empty_pool_is_reported_rather_than_crashing(self) -> None:
        pool = IdeaPool(baseline_proposer="mechanism", proposer_calls=5)
        self.assertIn("No candidate hypotheses survived", pool.effect()["verdict"])

    def test_ranking_puts_the_best_scored_candidate_first(self) -> None:
        strong = Candidate(**{**_candidate("a-1", "a", _MECHANISM).__dict__,
                              "novelty": 8.0, "feasibility": 9.0, "relevance": 9.0})
        weak = Candidate(**{**_candidate("b-1", "b", _UNRELATED).__dict__,
                            "novelty": 2.0, "feasibility": 3.0, "relevance": 4.0})
        pool = IdeaPool(candidates=[weak, strong], baseline_proposer="a")
        self.assertEqual([c.idea_id for c in pool.ranked()], ["a-1", "b-1"])

    def test_unscored_candidates_sort_after_scored_ones(self) -> None:
        scored = Candidate(**{**_candidate("a-1", "a", _MECHANISM).__dict__, "novelty": 1.0})
        unscored = _candidate("b-1", "b", _UNRELATED)
        pool = IdeaPool(candidates=[unscored, scored], baseline_proposer="a")
        self.assertEqual([c.idea_id for c in pool.ranked()], ["a-1", "b-1"])


class LensTests(unittest.TestCase):
    def test_the_default_lenses_are_five_distinct_mandates(self) -> None:
        self.assertEqual(len(DEFAULT_LENSES), 5)
        self.assertEqual(len({lens.charter for lens in DEFAULT_LENSES}), 5)

    def test_a_subset_keeps_the_callers_order(self) -> None:
        self.assertEqual([l.key for l in resolve_lenses(["null", "mechanism"])], ["null", "mechanism"])

    def test_an_unknown_lens_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            resolve_lenses(["brainstorm"])

    def test_models_can_be_assigned_per_lens(self) -> None:
        lenses = apply_lens_models(DEFAULT_LENSES, ["mechanism=opus", "null=codex:default"])
        by_key = {lens.key: lens for lens in lenses}
        self.assertEqual(by_key["mechanism"].model, "opus")
        self.assertEqual((by_key["null"].backend, by_key["null"].model), ("codex", "default"))
        self.assertIsNone(by_key["regime"].model)

    def test_a_malformed_assignment_is_refused(self) -> None:
        for bad in ("mechanism", "mechanism=", "nobody=opus"):
            with self.assertRaises(ValueError, msg=bad):
                apply_lens_models(DEFAULT_LENSES, [bad])


class PanelRunTests(unittest.TestCase):
    def _panel(self, script: dict[str, object], **kwargs):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Does remittance inflow raise household consumption?")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")

        panel = IdeationPanel(
            kwargs.pop("lenses", DEFAULT_LENSES),
            backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            **kwargs,
        )

        def make(key):
            def run_prompt(*, paths, stage, attempt_no, prompt, label):
                response = script.get("__score__" if label == "ideate_score" else key)
                if response == "__FAIL__":
                    return 1, "", "boom"
                return 0, json.dumps(response if response is not None else {"hypotheses": []}), ""
            return run_prompt

        for lens in panel.lenses:
            panel._members[lens.key].run_prompt = make(lens.key)
        return panel, paths

    def _build(self, script, **kwargs):
        panel, paths = self._panel(script, **kwargs)
        return panel.build_pool(paths=paths, stage=STAGE_02, attempt_no=1), paths

    def test_candidates_from_every_lens_reach_the_pool(self) -> None:
        script = {
            lens.key: {"hypotheses": [{"title": lens.key, "statement": f"Claim {lens.key} " + lens.key * 6}]}
            for lens in DEFAULT_LENSES
        }
        script["__score__"] = {"scores": []}
        pool, _ = self._build(script)
        self.assertEqual(len(pool.distinct), 5)

    def test_an_empty_list_is_recorded_as_an_abstention(self) -> None:
        script = {lens.key: {"hypotheses": []} for lens in DEFAULT_LENSES}
        script["mechanism"] = {"hypotheses": [{"title": "m", "statement": _MECHANISM}]}
        script["__score__"] = {"scores": []}
        pool, _ = self._build(script)
        self.assertEqual(len(pool.abstentions), 4)
        self.assertEqual(len(pool.distinct), 1)

    def test_an_unreachable_proposer_does_not_stop_the_pool(self) -> None:
        script = {lens.key: {"hypotheses": [{"title": "t", "statement": f"Claim {lens.key * 8}"}]}
                  for lens in DEFAULT_LENSES}
        script["regime"] = "__FAIL__"
        script["__score__"] = {"scores": []}
        pool, _ = self._build(script)
        self.assertEqual(pool.unreachable, ["regime"])
        self.assertEqual(len(pool.distinct), 4)

    def test_ideas_per_proposer_is_a_cap(self) -> None:
        many = {"hypotheses": [{"title": f"t{i}", "statement": f"Distinct claim number {i} " + "word" * i}
                               for i in range(6)]}
        script = {lens.key: many for lens in DEFAULT_LENSES}
        script["__score__"] = {"scores": []}
        pool, _ = self._build(script, lenses=resolve_lenses(["mechanism"]), ideas_per_proposer=2)
        self.assertEqual(len(pool.candidates), 2)

    def test_scores_land_on_the_right_candidates(self) -> None:
        script = {
            "mechanism": {"hypotheses": [{"title": "m", "statement": _MECHANISM}]},
            "null": {"hypotheses": [{"title": "n", "statement": _UNRELATED}]},
            "__score__": {"scores": [
                {"idea_id": "mechanism-1", "novelty": 4, "feasibility": 9, "relevance": 9},
                {"idea_id": "null-1", "novelty": 3, "feasibility": 8, "relevance": 9},
            ]},
        }
        pool, _ = self._build(script, lenses=resolve_lenses(["mechanism", "null"]))
        by_id = {c.idea_id: c for c in pool.distinct}
        self.assertEqual(by_id["mechanism-1"].feasibility, 9.0)
        self.assertEqual(by_id["null-1"].novelty, 3.0)

    def test_a_failed_scoring_call_leaves_the_pool_usable(self) -> None:
        script = {
            "mechanism": {"hypotheses": [{"title": "m", "statement": _MECHANISM}]},
            "__score__": "__FAIL__",
        }
        pool, _ = self._build(script, lenses=resolve_lenses(["mechanism"]))
        self.assertEqual(len(pool.distinct), 1)
        self.assertIsNone(pool.distinct[0].novelty)

    def test_an_out_of_range_score_is_clamped(self) -> None:
        script = {
            "mechanism": {"hypotheses": [{"title": "m", "statement": _MECHANISM}]},
            "__score__": {"scores": [{"idea_id": "mechanism-1", "novelty": 99, "feasibility": -4,
                                      "relevance": "not a number"}]},
        }
        pool, _ = self._build(script, lenses=resolve_lenses(["mechanism"]))
        candidate = pool.distinct[0]
        self.assertEqual((candidate.novelty, candidate.feasibility, candidate.relevance), (10.0, 0.0, None))

    def test_a_candidate_with_no_statement_is_dropped(self) -> None:
        script = {
            "mechanism": {"hypotheses": [{"title": "empty"}, {"title": "m", "statement": _MECHANISM}]},
            "__score__": {"scores": []},
        }
        pool, _ = self._build(script, lenses=resolve_lenses(["mechanism"]))
        self.assertEqual(len(pool.candidates), 1)

    def test_fake_mode_returns_an_empty_pool_without_calling_anything(self) -> None:
        panel, paths = self._panel({}, fake_mode=True)
        pool = panel.build_pool(paths=paths, stage=STAGE_02, attempt_no=1)
        self.assertEqual(pool.candidates, [])
        self.assertEqual(pool.proposer_calls, 0)

    def test_an_empty_roster_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            IdeationPanel((), backend_name="claude", model="sonnet")


class ArtifactTests(unittest.TestCase):
    def _paths_with_pool(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.memory, "# Approved Run Memory\n")
        pool = IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM, title="Liquidity channel"),
                _candidate("contrarian-1", "contrarian", _RESTATED),
                _candidate("null-1", "null", _UNRELATED, title="Selection artifact"),
            ]),
            abstentions=["regime"],
            baseline_proposer="mechanism",
            proposer_calls=5,
        )
        return paths, pool

    def test_the_pool_is_written_where_stage_02_artifacts_live(self) -> None:
        paths, pool = self._paths_with_pool()
        record_idea_pool(paths, pool, STAGE_02, 1)
        payload = json.loads(read_text(paths.notes_dir / IDEA_POOL_FILENAME))
        self.assertEqual(payload["stage"], STAGE_02.slug)
        self.assertEqual(payload["effect"]["collapsed_as_duplicates"], 1)
        self.assertTrue((paths.notes_dir / "idea_pool.md").exists())

    def test_the_verdict_reaches_the_run_log(self) -> None:
        paths, pool = self._paths_with_pool()
        record_idea_pool(paths, pool, STAGE_02, 1)
        self.assertIn("distinct hypotheses came from proposers", read_text(paths.logs))

    def test_the_prompt_block_presents_material_not_a_decision(self) -> None:
        _paths, pool = self._paths_with_pool()
        rendered = format_pool_for_prompt(pool)
        self.assertIn("material, not a decision", rendered)
        self.assertIn("Liquidity channel", rendered)
        self.assertIn("Selection artifact", rendered)
        # The restatement is folded in, and the fact that it was is disclosed.
        self.assertNotIn("contrarian-1", rendered)
        self.assertIn("folded in as restatements", rendered)
        self.assertIn("regime", rendered)

    def test_an_empty_pool_tells_the_stage_to_proceed_normally(self) -> None:
        rendered = format_pool_for_prompt(IdeaPool(baseline_proposer="mechanism"))
        self.assertIn("Generate hypotheses", rendered)


class ManagerIntegrationTests(unittest.TestCase):
    def test_the_pool_is_injected_into_the_stage_02_prompt(self) -> None:
        import io as _io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        root = Path(tmp_dir.name)
        runs_dir = root / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n\n## Approved Stage Summaries\n\n_None yet._\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")

        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=_io.StringIO(), interactive=False),
        )
        panel = IdeationPanel(
            resolve_lenses(["mechanism"]), backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=_io.StringIO(), interactive=False),
        )
        panel._members["mechanism"].run_prompt = lambda **kw: (
            0, json.dumps({"hypotheses": [{"title": "m", "statement": _MECHANISM}]}), ""
        ) if kw["label"] != "ideate_score" else (0, json.dumps({"scores": []}), "")
        manager.ideation_panel = panel

        prompt = manager._build_stage_prompt(paths, STAGE_02, None, False)

        self.assertIn("Candidate Hypothesis Pool", prompt)
        self.assertIn(_MECHANISM, prompt)
        self.assertTrue((paths.notes_dir / IDEA_POOL_FILENAME).exists())

    def test_a_failing_panel_does_not_stop_the_stage(self) -> None:
        import io as _io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        root = Path(tmp_dir.name)
        runs_dir = root / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")

        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=_io.StringIO(), interactive=False),
        )
        broken = IdeationPanel(
            resolve_lenses(["mechanism"]), backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=_io.StringIO(), interactive=False),
        )

        def explode(**_kwargs):
            raise RuntimeError("panel is down")

        broken.build_pool = explode
        manager.ideation_panel = broken

        prompt = manager._build_stage_prompt(paths, STAGE_02, None, False)

        # The pool is material, not a dependency.
        self.assertIn("did not run", prompt)
        self.assertIn("panel is down", read_text(paths.logs))


if __name__ == "__main__":
    unittest.main()


class AdoptionTests(unittest.TestCase):
    """Widening the pool and being used are different claims, and only one was measured.

    Havranek and Irsova had authors rank perceived usefulness and say plainly it is "not
    realized improvement"; AgentPanel ends on its ideas being "speculative candidates that
    require expert validation". A pool that widened the options and was then ignored has not
    helped, so the outcome is measured rather than assumed.
    """

    def _pool(self) -> IdeaPool:
        return IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM),
                _candidate("null-1", "null", _UNRELATED),
            ]),
            baseline_proposer="mechanism",
            proposer_calls=5,
        )

    def test_a_hypothesis_the_stage_developed_counts_as_adopted(self) -> None:
        pool = measure_adoption(self._pool(), (
            "# Stage 02\n\n## Key Results\n\n"
            "H1: We hypothesise that remittance inflows increase consumption in credit-poor "
            "households by relaxing their liquidity constraints, and will test it against the "
            "transitory-income alternative.\n"
        ))
        by_id = {c.idea_id: c for c in pool.distinct}
        self.assertTrue(by_id["mechanism-1"].adopted)
        self.assertFalse(by_id["null-1"].adopted)

    def test_a_stage_that_ignored_the_pool_is_reported_as_such(self) -> None:
        pool = measure_adoption(self._pool(), (
            "# Stage 02\n\n## Key Results\n\n"
            "H1: Trade openness drives productivity convergence across regions, which we will "
            "test with a gravity specification on the panel of bilateral flows.\n"
        ))
        effect = pool.effect()
        self.assertTrue(effect["adoption_measured"])
        self.assertEqual(effect["adopted"], 0)
        self.assertIn("adopted none of them", effect["verdict"])
        self.assertIn("cost its calls and changed nothing", effect["verdict"])

    def test_adoption_only_from_the_baseline_says_a_single_pass_would_have_done(self) -> None:
        pool = measure_adoption(self._pool(), (
            "# Stage 02\n\n## Key Results\n\n"
            "H1: Remittance inflows increase household consumption in credit-poor households "
            "because they relax liquidity constraints.\n"
        ))
        self.assertIn("a single pass would have supplied", pool.effect()["verdict"])

    def test_adoption_beyond_the_baseline_is_credited(self) -> None:
        pool = measure_adoption(self._pool(), (
            "# Stage 02\n\n## Key Results\n\n"
            "H1: Remittance inflows increase consumption in credit-poor households by relaxing "
            "liquidity constraints.\n\n"
            "H2: The observed correlation may be a selection artifact, since households that "
            "receive remittances differ systematically in unobserved ways; we will test this "
            "with household fixed effects.\n"
        ))
        effect = pool.effect()
        self.assertEqual(effect["adopted"], 2)
        self.assertEqual(effect["adopted_from_other_proposers"], 1)
        self.assertIn("1 of them from proposers beyond the baseline", effect["verdict"])

    def test_before_measurement_the_verdict_does_not_claim_usefulness(self) -> None:
        effect = self._pool().effect()
        self.assertFalse(effect["adoption_measured"])
        self.assertIn("not yet measured", effect["verdict"])

    def test_a_duplicate_is_never_credited_with_adoption(self) -> None:
        pool = IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM),
                _candidate("contrarian-1", "contrarian", _RESTATED),
            ]),
            baseline_proposer="mechanism",
        )
        measure_adoption(pool, f"# Stage 02\n\n## Key Results\n\n{_MECHANISM}\n")
        folded = next(c for c in pool.candidates if c.duplicate_of is not None)
        self.assertIsNone(folded.adopted)

    def test_a_short_fragment_cannot_be_mistaken_for_adoption(self) -> None:
        """The length floor is load-bearing, and this is the case that shows it.

        A hypothesis with few content words is easy to falsely match: the fragment
        "Reported class-size effect" scores 0.57 against the statement below, well over the
        0.35 bar, purely because Jaccard's union is small. Only the length floor stops a
        heading fragment from being read as the stage having adopted the idea.
        """
        short = "Publication bias inflates the reported class-size effect."
        pool = IdeaPool(
            candidates=[_candidate("a-1", "mechanism", short)],
            baseline_proposer="mechanism",
        )
        # The fragment on its own would clear the bar; as a heading it must not.
        self.assertGreater(similarity(short, "Reported class-size effect"), ADOPTION_THRESHOLD)

        measure_adoption(pool, "# Stage 02\n\n## Reported class-size effect\n\n## Files Produced\n")

        self.assertEqual(pool.effect()["adopted"], 0)

    def test_boilerplate_headings_alone_are_never_adoption(self) -> None:
        pool = measure_adoption(self._pool(), "# Stage 02\n\n## Key Results\n\n## Files Produced\n")
        self.assertEqual(pool.effect()["adopted"], 0)


class PoolRoundTripTests(unittest.TestCase):
    def _written(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.memory, "# Approved Run Memory\n")
        pool = IdeaPool(
            candidates=mark_duplicates([
                _candidate("mechanism-1", "mechanism", _MECHANISM),
                _candidate("contrarian-1", "contrarian", _RESTATED),
                _candidate("null-1", "null", _UNRELATED),
            ]),
            abstentions=["regime"],
            baseline_proposer="mechanism",
            proposer_calls=5,
        )
        record_idea_pool(paths, pool, STAGE_02, 1)
        return paths

    def test_a_written_pool_can_be_read_back(self) -> None:
        paths = self._written()
        pool = load_idea_pool(paths)
        self.assertIsNotNone(pool)
        assert pool is not None
        self.assertEqual(len(pool.distinct), 2)
        self.assertEqual(pool.baseline_proposer, "mechanism")
        self.assertEqual(pool.proposer_calls, 5)
        self.assertEqual(pool.abstentions, ["regime"])

    def test_duplicate_marks_survive_the_round_trip(self) -> None:
        pool = load_idea_pool(self._written())
        assert pool is not None
        folded = next(c for c in pool.candidates if c.idea_id == "contrarian-1")
        self.assertEqual(folded.duplicate_of, "mechanism-1")

    def test_a_missing_or_corrupt_pool_reads_as_none(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        self.assertIsNone(load_idea_pool(paths))
        write_text(paths.notes_dir / IDEA_POOL_FILENAME, "{ not json")
        self.assertIsNone(load_idea_pool(paths))

    def test_the_measured_outcome_is_written_back(self) -> None:
        paths = self._written()
        pool = load_idea_pool(paths)
        assert pool is not None
        measure_adoption(pool, f"# Stage 02\n\n## Key Results\n\n{_MECHANISM} We will test it.\n")
        record_idea_pool(paths, pool, STAGE_02, 0)

        payload = json.loads(read_text(paths.notes_dir / IDEA_POOL_FILENAME))
        self.assertTrue(payload["effect"]["adoption_measured"])
        self.assertEqual(payload["effect"]["adopted"], 1)
        self.assertIn("a single pass would have supplied", payload["effect"]["verdict"])


class AdoptionIntegrationTests(unittest.TestCase):
    def _manager_and_paths(self):
        import io as _io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
        ensure_run_config(paths, model="sonnet", venue="neurips_2025")

        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=_io.StringIO(), interactive=False),
        )
        return manager, paths

    def test_approving_stage_02_measures_the_pool(self) -> None:
        manager, paths = self._manager_and_paths()
        record_idea_pool(
            paths,
            IdeaPool(
                candidates=mark_duplicates([_candidate("mechanism-1", "mechanism", _MECHANISM)]),
                baseline_proposer="mechanism",
                proposer_calls=5,
            ),
            STAGE_02,
            1,
        )

        manager._measure_pool_adoption(
            paths, STAGE_02,
            f"# Stage 02\n\n## Key Results\n\n{_MECHANISM} We will test it against the alternative.\n",
        )

        payload = json.loads(read_text(paths.notes_dir / IDEA_POOL_FILENAME))
        self.assertTrue(payload["effect"]["adoption_measured"])
        self.assertEqual(payload["effect"]["adopted"], 1)

    def test_a_run_with_no_pool_is_a_no_op(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._measure_pool_adoption(paths, STAGE_02, "# Stage 02\n\nNo pool was ever written.\n")
        self.assertFalse((paths.notes_dir / IDEA_POOL_FILENAME).exists())

    def test_a_corrupt_pool_cannot_disturb_an_approval(self) -> None:
        manager, paths = self._manager_and_paths()
        write_text(paths.notes_dir / IDEA_POOL_FILENAME, "{ not json")
        manager._measure_pool_adoption(paths, STAGE_02, "# Stage 02\n\nApproved.\n")
        self.assertEqual(read_text(paths.notes_dir / IDEA_POOL_FILENAME), "{ not json\n")
