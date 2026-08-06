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
    DEFAULT_LENSES,
    DUPLICATE_THRESHOLD,
    IDEA_POOL_FILENAME,
    Candidate,
    IdeaPool,
    IdeationPanel,
    ProposerLens,
    apply_lens_models,
    format_pool_for_prompt,
    mark_duplicates,
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
