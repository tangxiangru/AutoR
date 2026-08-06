"""Spending effort unevenly, and admitting when the spend was wrong.

Tiering is a bet made per stage. The tests that matter are the ones about losing the bet:
does a routine stage that keeps failing recover, and does the ledger say so afterwards.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.effort import (
    DEFAULT_TIERS,
    DELIBERATIVE,
    LEDGER_FILENAME,
    PROMOTE_AFTER_FAILURES,
    ROUTINE,
    EffortPlan,
    normalize_tier,
    parse_declaration,
    record_plan,
    summarize,
    tier_notice,
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


STAGE_03 = next(s for s in STAGES if s.slug == "03_study_design")
STAGE_04 = next(s for s in STAGES if s.slug == "04_implementation")
STAGE_08 = next(s for s in STAGES if s.slug == "08_dissemination")


class TierBasicsTests(unittest.TestCase):
    def test_the_defaults_split_deciding_from_carrying_out(self) -> None:
        # Framing, hypotheses, design and interpretation decide things; implementation,
        # execution and packaging carry decisions out.
        self.assertEqual(DEFAULT_TIERS["03_study_design"], DELIBERATIVE)
        self.assertEqual(DEFAULT_TIERS["06_analysis"], DELIBERATIVE)
        self.assertEqual(DEFAULT_TIERS["04_implementation"], ROUTINE)
        self.assertEqual(DEFAULT_TIERS["08_dissemination"], ROUTINE)
        self.assertEqual(set(DEFAULT_TIERS), {stage.slug for stage in STAGES})

    def test_normalize_accepts_only_real_tiers(self) -> None:
        self.assertEqual(normalize_tier(" Routine "), ROUTINE)
        self.assertIsNone(normalize_tier("medium"))
        self.assertIsNone(normalize_tier(None))

    def test_a_disabled_plan_treats_everything_as_deliberative(self) -> None:
        # Off means the old behaviour exactly: nothing gets a cheaper path by accident.
        plan = EffortPlan(enabled=False)
        self.assertEqual(plan.tier_for(STAGE_04), DELIBERATIVE)
        self.assertFalse(plan.is_routine(STAGE_04))

    def test_an_enabled_plan_uses_the_defaults(self) -> None:
        plan = EffortPlan(enabled=True)
        self.assertTrue(plan.is_routine(STAGE_04))
        self.assertFalse(plan.is_routine(STAGE_03))


class DeclarationTests(unittest.TestCase):
    def test_a_stage_can_set_the_next_stages_tier(self) -> None:
        parsed = parse_declaration(
            "## Decision Ledger\n- Locked: ...\n\nNext stage effort: routine — the design is settled.\n"
        )
        self.assertEqual(parsed, (ROUTINE, "the design is settled."))

    def test_the_declaration_is_case_insensitive_and_reason_optional(self) -> None:
        self.assertEqual(parse_declaration("NEXT STAGE EFFORT: Deliberative"), (DELIBERATIVE, ""))

    def test_an_unknown_tier_is_not_a_declaration(self) -> None:
        self.assertIsNone(parse_declaration("Next stage effort: whenever"))

    def test_a_summary_with_no_declaration_parses_as_none(self) -> None:
        self.assertIsNone(parse_declaration("# Stage 03\n\n## Key Results\n\nDone.\n"))
        self.assertIsNone(parse_declaration(""))

    def test_a_declaration_overrides_the_default(self) -> None:
        plan = EffortPlan(enabled=True)
        self.assertTrue(plan.is_routine(STAGE_04))
        plan.declare(STAGE_04.slug, DELIBERATIVE, "the loader design is still open")
        self.assertFalse(plan.is_routine(STAGE_04))
        self.assertEqual(plan.decision_for(STAGE_04).chosen_by, "prior stage")


class PromotionTests(unittest.TestCase):
    """Cheap is a bet; this is what happens when the bet loses."""

    def test_a_routine_stage_that_keeps_failing_is_promoted(self) -> None:
        plan = EffortPlan(enabled=True)
        self.assertTrue(plan.is_routine(STAGE_04))
        for _ in range(PROMOTE_AFTER_FAILURES - 1):
            self.assertFalse(plan.note_failure(STAGE_04))
        self.assertTrue(plan.note_failure(STAGE_04))
        self.assertFalse(plan.is_routine(STAGE_04))

    def test_one_failure_is_not_enough(self) -> None:
        # A single failed gate is ordinary and often a formatting problem.
        plan = EffortPlan(enabled=True)
        plan.note_failure(STAGE_04)
        self.assertTrue(plan.is_routine(STAGE_04))

    def test_the_promotion_records_what_it_came_from_and_why(self) -> None:
        plan = EffortPlan(enabled=True)
        for _ in range(PROMOTE_AFTER_FAILURES):
            plan.note_failure(STAGE_04)
        decision = plan.decision_for(STAGE_04)
        self.assertEqual(decision.promoted_from, ROUTINE)
        self.assertEqual(decision.chosen_by, "promotion")
        self.assertIn("harder than the previous stage expected", decision.reason)

    def test_a_deliberative_stage_is_never_promoted(self) -> None:
        plan = EffortPlan(enabled=True)
        for _ in range(PROMOTE_AFTER_FAILURES + 2):
            self.assertFalse(plan.note_failure(STAGE_03))
        self.assertEqual(plan.decision_for(STAGE_03).promoted_from, "")

    def test_a_promotion_outranks_a_later_declaration(self) -> None:
        plan = EffortPlan(enabled=True)
        for _ in range(PROMOTE_AFTER_FAILURES):
            plan.note_failure(STAGE_04)
        plan.declare(STAGE_04.slug, ROUTINE, "still think it is easy")
        # Evidence beats a guess.
        self.assertFalse(plan.is_routine(STAGE_04))

    def test_a_disabled_plan_never_promotes(self) -> None:
        plan = EffortPlan(enabled=False)
        for _ in range(PROMOTE_AFTER_FAILURES + 1):
            self.assertFalse(plan.note_failure(STAGE_04))


class NoticeTests(unittest.TestCase):
    def test_a_routine_stage_is_told_not_to_re_open_settled_questions(self) -> None:
        notice = tier_notice(STAGE_04, ROUTINE, STAGE_08)
        self.assertIn("Effort Tier: routine", notice)
        self.assertIn("do not re-open settled questions", notice)
        # …but it must be able to say the premise was wrong.
        self.assertIn("Open Questions", notice)

    def test_a_deliberative_stage_is_told_to_take_the_time(self) -> None:
        notice = tier_notice(STAGE_03, DELIBERATIVE, STAGE_04)
        self.assertIn("Effort Tier: deliberative", notice)
        self.assertIn("Take the time", notice)

    def test_the_notice_asks_for_the_next_stages_tier_by_name(self) -> None:
        notice = tier_notice(STAGE_03, DELIBERATIVE, STAGE_04)
        self.assertIn(STAGE_04.stage_title, notice)
        self.assertIn("Next stage effort:", notice)

    def test_the_last_stage_is_not_asked_to_set_a_successor(self) -> None:
        self.assertNotIn("Next stage effort:", tier_notice(STAGE_08, ROUTINE, None))


class LedgerTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        return paths

    def test_both_directions_of_waste_are_reported(self) -> None:
        plan = EffortPlan(enabled=True)
        plan.decision_for(STAGE_04)                 # routine, fine
        for _ in range(PROMOTE_AFTER_FAILURES):     # routine, mis-called
            plan.note_failure(STAGE_08)
        plan.note_outcome(STAGE_03, attempts=1, contested=False)  # deliberative, over-spent

        summary = summarize(plan)
        self.assertEqual(summary["promoted_after_failing"], 1)
        self.assertEqual(summary["deliberative_but_uncontested"], 1)
        self.assertIn("that call was wrong", summary["verdict"])
        self.assertIn("bought nothing", summary["verdict"])

    def test_a_run_that_tiered_nothing_routine_is_called_out(self) -> None:
        plan = EffortPlan(enabled=True)
        plan.note_outcome(STAGE_03, attempts=2, contested=True)
        summary = summarize(plan)
        self.assertEqual(summary["run_as_routine"], 0)
        self.assertIn("which is the thing tiering exists to avoid", summary["verdict"])

    def test_a_clean_run_says_nothing_was_mis_tiered(self) -> None:
        plan = EffortPlan(enabled=True)
        plan.note_outcome(STAGE_04, attempts=1, contested=False)   # routine, cheap, passed
        plan.note_outcome(STAGE_03, attempts=2, contested=True)    # deliberative, contested
        self.assertIn("no stage was mis-tiered", summarize(plan)["verdict"])

    def test_the_plan_is_written_where_stage_08_reads_reviews(self) -> None:
        paths = self._paths()
        plan = EffortPlan(enabled=True)
        plan.declare(STAGE_04.slug, ROUTINE, "engineering only")
        payload = record_plan(paths, plan)
        on_disk = json.loads(read_text(paths.reviews_dir / LEDGER_FILENAME))
        self.assertEqual(on_disk["summary"], payload["summary"])
        self.assertEqual(on_disk["stages"][0]["reason"], "engineering only")

    def test_an_empty_plan_does_not_divide_by_zero(self) -> None:
        self.assertIn("No stages were tiered", summarize(EffortPlan(enabled=True))["verdict"])


class ManagerIntegrationTests(unittest.TestCase):
    def _manager_and_paths(self, *, enabled: bool = True):
        from unittest.mock import MagicMock
        from src.manager import ResearchManager

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
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
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        manager.effort_plan = EffortPlan(enabled=enabled)
        return manager, paths

    def test_a_routine_stage_prompt_is_told_it_is_routine(self) -> None:
        manager, paths = self._manager_and_paths()
        prompt = manager._build_stage_prompt(paths, STAGE_04, None, False)
        self.assertIn("Effort Tier: routine", prompt)

    def test_a_routine_stage_is_not_offered_the_crux_escalation(self) -> None:
        from src.deliberation import CruxPanel, DEFAULT_VOICES

        manager, paths = self._manager_and_paths()
        manager.crux_panel = CruxPanel(
            DEFAULT_VOICES, backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        routine = manager._build_stage_prompt(paths, STAGE_04, None, False)
        deliberative = manager._build_stage_prompt(paths, STAGE_03, None, False)

        # A stage whose decisions are made has nothing to escalate; offering it the option is
        # how a routine stage stops being one.
        self.assertNotIn("Raising A Crux", routine)
        self.assertIn("Raising A Crux", deliberative)

    def test_tiering_off_leaves_the_prompt_exactly_as_before(self) -> None:
        manager, paths = self._manager_and_paths(enabled=False)
        prompt = manager._build_stage_prompt(paths, STAGE_04, None, False)
        self.assertNotIn("Effort Tier", prompt)

    def test_a_declaration_in_an_approved_summary_sets_the_next_stage(self) -> None:
        manager, paths = self._manager_and_paths()
        manager._settle_effort(
            paths, STAGE_03, 1,
            "# Stage 03\n\n## Decision Ledger\n\nNext stage effort: deliberative — the loader "
            "design is still open.\n",
        )
        self.assertFalse(manager.effort_plan.is_routine(STAGE_04))
        self.assertIn("effort_declaration", read_text(paths.logs))

    def test_repeated_refusals_promote_a_routine_stage(self) -> None:
        manager, paths = self._manager_and_paths()
        for _ in range(PROMOTE_AFTER_FAILURES):
            manager._note_effort_failure(paths, STAGE_04)
        self.assertFalse(manager.effort_plan.is_routine(STAGE_04))
        self.assertIn("effort_promoted", read_text(paths.logs))

    def test_a_broken_plan_cannot_disturb_an_approval(self) -> None:
        manager, paths = self._manager_and_paths()

        def explode(*_args, **_kwargs):
            raise RuntimeError("plan blew up")

        manager.effort_plan.note_outcome = explode
        manager._settle_effort(paths, STAGE_03, 1, "# Stage 03\n")
        self.assertIn("plan blew up", read_text(paths.logs))

    def test_a_routine_stage_does_not_pay_for_the_ideation_pool(self) -> None:
        from src.information_flow import ChannelContext
        from src.information_flow import _idea_pool  # noqa: PLC2701

        manager, paths = self._manager_and_paths()
        built: list[str] = []
        manager.ideation_panel = object()  # presence is all the channel checks
        manager._build_idea_pool = lambda p, st, a: built.append(st.slug) or "pool"

        stage_02 = next(s for s in STAGES if s.slug == "02_hypothesis_generation")
        manager.effort_plan.declare(stage_02.slug, ROUTINE, "hypotheses were settled upstream")
        self.assertIsNone(
            _idea_pool(ChannelContext(paths=paths, stage=stage_02, attempt_no=1, manager=manager))
        )
        self.assertEqual(built, [])

        manager.effort_plan.declare(stage_02.slug, DELIBERATIVE, "still open")
        self.assertEqual(
            _idea_pool(ChannelContext(paths=paths, stage=stage_02, attempt_no=1, manager=manager)),
            "pool",
        )

    def test_a_routine_stage_gates_with_the_solo_reviewer(self) -> None:
        from src.approval_agent import AutomatedReviewer, ReviewDecision

        manager, paths = self._manager_and_paths()
        calls: list[str] = []

        class Recorder(AutomatedReviewer):
            def __init__(self, tag):
                super().__init__("claude", model="sonnet", fake_mode=True)
                self.tag = tag

            def review_stage(self, **_kwargs):
                calls.append(self.tag)
                return ReviewDecision(choice="5", decision_token="approve")

        manager.reviewer = Recorder("panel")
        manager.solo_reviewer = Recorder("solo")
        manager._display_stage_output = lambda *a, **k: None

        manager._collect_review_decision(
            paths=paths, stage=STAGE_04, attempt_no=1,
            stage_markdown="# Stage 04\n", suggestions=["a", "b", "c"],
        )
        manager._collect_review_decision(
            paths=paths, stage=STAGE_03, attempt_no=1,
            stage_markdown="# Stage 03\n", suggestions=["a", "b", "c"],
        )

        # Routine goes to the cheap gate; deliberative keeps the configured one.
        self.assertEqual(calls, ["solo", "panel"])


if __name__ == "__main__":
    unittest.main()
