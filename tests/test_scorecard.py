"""Reading five honest ledgers into one answer.

The bug this file mostly guards against is a scorecard that reports "changed nothing" when it
actually means "I could not read the file". That failure would be worse than no scorecard: it
would make an unbroken feature look useless with the same confidence it uses for a real null.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.scorecard import (
    DROP,
    KEEP,
    SCORECARD_JSON,
    SCORECARD_MD,
    UNPROVEN,
    UNREADABLE,
    UNUSED,
    build_scorecard,
    render_markdown,
    write_scorecard,
)
from src.scorecard import FEATURES
from src.utils import build_run_paths, ensure_run_layout, read_text, write_text


def _ledger_path(paths, key: str) -> Path:
    """Where the producer for `key` actually writes.

    Every fixture here used to go to `paths.reviews_dir / <filename>`. Four of the five
    producers do write there; `record_panel_effect` writes to `reviews_dir / "panel" / ...`,
    so the review-panel half of this file was green against a path that never occurs in a
    run, while the scorecard reported the panel `unused` on every real one. Routing the
    fixtures through the same `locate` the reader uses makes a future divergence fail here.
    """
    feature = next(f for f in FEATURES if f["key"] == key)
    path = feature["locate"](paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _paths(testcase: unittest.TestCase):
    tmp_dir = tempfile.TemporaryDirectory()
    testcase.addCleanup(tmp_dir.cleanup)
    paths = build_run_paths(Path(tmp_dir.name) / "run")
    ensure_run_layout(paths)
    paths.reviews_dir.mkdir(parents=True, exist_ok=True)
    return paths


def _verdict_for(paths, key: str) -> str:
    return next(r for r in build_scorecard(paths).features if r.key == key).verdict


def _panel(**overrides) -> str:
    summary = {
        "gates_reviewed": 8,
        "gates_where_the_panel_changed_the_decision": 0,
        "panel_calls": 40,
        "verdict": "same decision at all 8 gates",
    }
    summary.update(overrides)
    return json.dumps({"summary": summary})


class UnusedVersusNullTests(unittest.TestCase):
    """The distinction the whole artifact turns on."""

    def test_a_feature_that_never_ran_is_unused_not_a_failure(self) -> None:
        paths = _paths(self)
        for report in build_scorecard(paths).features:
            self.assertEqual(report.verdict, UNUSED, report.key)

    def test_an_unreadable_ledger_is_never_reported_as_no_effect(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), "{ not json")
        # "I could not measure this" must not wear the same badge as "this did nothing".
        self.assertEqual(_verdict_for(paths, "review_panel"), UNREADABLE)

    def test_a_ledger_of_the_wrong_shape_is_unreadable_too(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), json.dumps(["not", "a", "dict"]))
        self.assertEqual(_verdict_for(paths, "review_panel"), UNREADABLE)

    def test_a_ledger_missing_its_summary_does_not_crash_the_card(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), json.dumps({"gates": []}))
        # No summary means no gates reviewed, which is unproven rather than a null result.
        self.assertEqual(_verdict_for(paths, "review_panel"), UNPROVEN)


class ReviewPanelTests(unittest.TestCase):
    def test_a_panel_that_changed_nothing_is_dropped(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), _panel())
        self.assertEqual(_verdict_for(paths, "review_panel"), DROP)

    def test_a_panel_that_changed_a_decision_is_kept(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"),
                   _panel(gates_where_the_panel_changed_the_decision=2))
        self.assertEqual(_verdict_for(paths, "review_panel"), KEEP)

    def test_a_panel_that_never_reached_a_gate_is_unproven(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), _panel(gates_reviewed=0))
        self.assertEqual(_verdict_for(paths, "review_panel"), UNPROVEN)


class IdeationTests(unittest.TestCase):
    def _pool(self, **effect) -> str:
        base = {"proposer_calls": 6, "adoption_measured": True,
                "adopted_from_other_proposers": 0, "verdict": "v"}
        base.update(effect)
        return json.dumps({"effect": base})

    def test_a_pool_nobody_adopted_beyond_the_baseline_is_dropped(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "ideation_panel"), self._pool())
        self.assertEqual(_verdict_for(paths, "ideation_panel"), DROP)

    def test_a_pool_adopted_beyond_the_baseline_is_kept(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "ideation_panel"), self._pool(adopted_from_other_proposers=2))
        self.assertEqual(_verdict_for(paths, "ideation_panel"), KEEP)

    def test_widening_without_uptake_measured_is_unproven_not_a_win(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "ideation_panel"),
                   self._pool(adoption_measured=False, adopted_from_other_proposers=3))
        # Widening is not usefulness; the pool itself says so until Stage 02 is approved.
        self.assertEqual(_verdict_for(paths, "ideation_panel"), UNPROVEN)

    def test_the_pool_is_found_in_the_notes_directory(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "ideation_panel"), self._pool(adopted_from_other_proposers=1))
        # It lives beside Stage 02's artifacts, not with the reviews.
        self.assertEqual(_verdict_for(paths, "ideation_panel"), KEEP)


class DeliberationTests(unittest.TestCase):
    def _ledger(self, **summary) -> str:
        base = {"cruxes_raised": 2, "changed_the_agents_answer": 0,
                "confirmed_the_agents_answer": 2, "voice_calls": 12, "verdict": "v"}
        base.update(summary)
        return json.dumps({"summary": base})

    def test_escalations_that_only_confirmed_the_agent_are_dropped(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "deliberation"), self._ledger())
        self.assertEqual(_verdict_for(paths, "deliberation"), DROP)

    def test_a_changed_answer_is_kept(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "deliberation"), self._ledger(changed_the_agents_answer=1))
        self.assertEqual(_verdict_for(paths, "deliberation"), KEEP)

    def test_no_crux_raised_is_unproven(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "deliberation"),
                   self._ledger(cruxes_raised=0, confirmed_the_agents_answer=0))
        self.assertEqual(_verdict_for(paths, "deliberation"), UNPROVEN)

    def test_escalated_with_no_working_answer_is_unproven(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "deliberation"),
                   self._ledger(confirmed_the_agents_answer=0))
        # Nothing to compare against is not the same as nothing changed.
        self.assertEqual(_verdict_for(paths, "deliberation"), UNPROVEN)


class EffortTests(unittest.TestCase):
    def _ledger(self, *, enabled=True, routine=3, planned=8, concentration=None) -> str:
        payload = {"enabled": enabled, "summary": {
            "stages_planned": planned, "run_as_routine": routine, "verdict": "v"}}
        if concentration:
            payload["concentration"] = concentration
        return json.dumps(payload)

    def test_tiering_switched_off_reads_as_unused(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "effort_tiers"), self._ledger(enabled=False))
        self.assertEqual(_verdict_for(paths, "effort_tiers"), UNUSED)

    def test_a_run_that_tiered_nothing_routine_is_dropped(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "effort_tiers"), self._ledger(routine=0))
        # Everything deliberative is the state tiering exists to move away from.
        self.assertEqual(_verdict_for(paths, "effort_tiers"), DROP)

    def test_the_concentration_verdict_is_folded_into_the_detail(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "effort_tiers"),
                   self._ledger(concentration={"verdict": "All 5 rounds went to deliberative."}))
        report = next(r for r in build_scorecard(paths).features if r.key == "effort_tiers")
        self.assertEqual(report.verdict, KEEP)
        self.assertIn("All 5 rounds went to deliberative.", report.detail)


class HeadlineTests(unittest.TestCase):
    def test_a_run_with_nothing_enabled_says_so(self) -> None:
        self.assertIn("No optional machinery", build_scorecard(_paths(self)).headline())

    def test_the_headline_totals_the_extra_calls(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), _panel(panel_calls=40))
        write_text(_ledger_path(paths, "deliberation"), json.dumps({"summary": {
            "cruxes_raised": 1, "changed_the_agents_answer": 1, "voice_calls": 12, "verdict": "v"}}))
        card = build_scorecard(paths)
        self.assertEqual(card.optional_calls, 52)
        self.assertIn("52 extra model call(s)", card.headline())
        self.assertIn("1 changed an outcome", card.headline())
        self.assertIn("can be turned off", card.headline())

    def test_an_unreadable_ledger_is_not_counted_as_a_feature_that_ran(self) -> None:
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), "{ not json")
        self.assertIn("No optional machinery", build_scorecard(paths).headline())


class RenderTests(unittest.TestCase):
    def _mixed(self):
        paths = _paths(self)
        write_text(_ledger_path(paths, "review_panel"), _panel())
        write_text(_ledger_path(paths, "deliberation"), json.dumps({"summary": {
            "cruxes_raised": 1, "changed_the_agents_answer": 1, "voice_calls": 12,
            "verdict": "changed one answer"}}))
        write_text(_ledger_path(paths, "ideation_panel"), json.dumps({"effect": {
            "proposer_calls": 6, "adoption_measured": False, "verdict": "not yet measured"}}))
        return paths

    def test_the_drop_section_names_the_flag_to_turn_off(self) -> None:
        rendered = render_markdown(build_scorecard(self._mixed()))
        self.assertIn("## Turn these off", rendered)
        self.assertIn("`--review-panel`", rendered)

    def test_unproven_is_explicitly_not_a_pass(self) -> None:
        rendered = render_markdown(build_scorecard(self._mixed()))
        self.assertIn("Unproven is not a pass", rendered)

    def test_features_that_never_ran_get_no_section(self) -> None:
        rendered = render_markdown(build_scorecard(self._mixed()))
        self.assertNotIn("## Not enabled", rendered)

    def test_both_files_are_written_where_the_reviews_live(self) -> None:
        paths = self._mixed()
        write_scorecard(paths)
        self.assertTrue((paths.reviews_dir / SCORECARD_JSON).exists())
        self.assertTrue((paths.reviews_dir / SCORECARD_MD).exists())
        payload = json.loads(read_text(paths.reviews_dir / SCORECARD_JSON))
        self.assertEqual(payload["drop"], ["review_panel"])
        self.assertEqual(payload["keep"], ["deliberation"])
        self.assertEqual(payload["unproven"], ["ideation_panel"])


class ManagerIntegrationTests(unittest.TestCase):
    def _manager_and_paths(self):
        import io
        from unittest.mock import MagicMock
        from src.manager import ResearchManager
        from src.terminal_ui import TerminalUI

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        operator = MagicMock()
        operator.model = "sonnet"
        operator.backend_name = "claude"
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=runs_dir,
            operator=operator,
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        return manager, paths

    def test_a_finished_run_writes_the_scorecard(self) -> None:
        manager, paths = self._manager_and_paths()
        write_text(_ledger_path(paths, "review_panel"), _panel())
        manager._report_optional_machinery(paths)
        self.assertTrue((paths.reviews_dir / SCORECARD_MD).exists())
        self.assertIn("scorecard", read_text(paths.logs))

    def test_a_run_with_no_optional_features_stays_quiet(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._report_optional_machinery(paths)
        # Nothing to weigh, so nothing is announced.
        self.assertNotIn("scorecard", read_text(paths.logs))

    def test_a_broken_scorecard_cannot_make_a_finished_run_look_unfinished(self) -> None:
        manager, paths = self._manager_and_paths()
        import src.manager as manager_module

        original = manager_module.write_scorecard
        manager_module.write_scorecard = lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("card broke"))
        try:
            manager._report_optional_machinery(paths)
        finally:
            manager_module.write_scorecard = original
        self.assertIn("card broke", read_text(paths.logs))


if __name__ == "__main__":
    unittest.main()


class LedgerLocationsMatchTheProducersTests(unittest.TestCase):
    """The reader's idea of where a ledger lives, checked against the writer's.

    `scorecard._load` used to guess -- `reviews_dir` then `notes_dir` -- and the guess was
    wrong for the review panel, which writes into `reviews_dir/panel/`. The consequence was
    not a crash: `_load` returned "no file", `_report` turned that into `unused` / "Not
    enabled on this run.", and the feature this whole module leads with was reported as
    switched off on every run where it was switched on. Every existing test in this file
    wrote its fixture to the reader's path, so all of them agreed with the reader and none
    with the writer.

    Rather than assert a list of paths -- the same guess written a third time -- each case
    drives the actual producer and asks the scorecard whether it found anything.
    """

    def test_the_review_panel_ledger_is_found_where_the_panel_writes_it(self) -> None:
        from src.review_panel import PanelDeliberation, record_panel_effect

        paths = _paths(self)
        record_panel_effect(
            paths,
            PanelDeliberation(stage_slug="01_literature_survey", attempt_no=1, chair_key="pi"),
        )

        report = next(r for r in build_scorecard(paths).features if r.key == "review_panel")
        self.assertNotEqual(
            report.verdict,
            UNUSED,
            "the panel wrote a ledger and the scorecard called the feature never-enabled",
        )

    def test_every_feature_is_looked_for_where_something_could_write_it(self) -> None:
        """A `locate` pointing outside the run tree is the same defect in a new shape."""
        paths = _paths(self)
        for feature in FEATURES:
            with self.subTest(feature=feature["key"]):
                path = feature["locate"](paths)
                self.assertEqual(path.name, feature["filename"])
                self.assertTrue(
                    str(path).startswith(str(paths.run_root)),
                    f"{feature['key']} is looked for outside the run directory: {path}",
                )

    def test_a_ledger_at_the_wrong_path_is_not_silently_treated_as_absent(self) -> None:
        """Pins the failure mode, not just today's instance of it.

        A file at a path the reader does not check is indistinguishable from no file, and
        `unused` is the most misleading of the five verdicts to land on: it says the feature
        was never switched on. If a refactor reintroduces a search, this is what it has to
        get past.
        """
        paths = _paths(self)
        feature = next(f for f in FEATURES if f["key"] == "review_panel")
        correct = feature["locate"](paths)
        wrong = paths.reviews_dir / feature["filename"]
        self.assertNotEqual(correct, wrong, "the panel ledger no longer sits in a subdirectory")

        wrong.parent.mkdir(parents=True, exist_ok=True)
        write_text(wrong, _panel())
        self.assertEqual(
            _verdict_for(paths, "review_panel"),
            UNUSED,
            "a ledger at the reader's old path should read as absent, not as a measurement",
        )

        write_text(correct, _panel(gates_where_the_panel_changed_the_decision=2))
        self.assertEqual(_verdict_for(paths, "review_panel"), KEEP)
