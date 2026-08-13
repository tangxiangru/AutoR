from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.approval_agent import ReviewDecision
from src.manager import ResearchManager
from src.review_policy import (
    MAX_RULES,
    MIN_RULE_CHARS,
    ReviewPolicy,
    ReviewRule,
    format_policy_for_prompt,
    load_policy,
    normalize_rule_text,
    policy_path,
    policy_summary,
    record_correction,
    save_policy,
)
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text


STAGE_01, STAGE_03 = STAGES[0], STAGES[2]
LONG = "The design lacks a stated power analysis and the sample size is unjustified."
OTHER = "Every reported metric must carry a confidence interval computed from the raw data."


class PolicyTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.memory, "# Memory\n")


class RecordCorrectionTest(PolicyTestBase):
    def test_a_correction_becomes_a_standing_rule(self) -> None:
        rule = record_correction(self.paths, stage=STAGE_01, attempt_no=2, text=LONG)
        self.assertIsNotNone(rule)
        self.assertEqual(rule.origin_stage, STAGE_01.slug)
        self.assertEqual(rule.origin_attempt, 2)
        self.assertEqual(load_policy(self.paths).rules[0].text, LONG)

    def test_the_policy_is_an_auditable_artifact_at_the_run_root(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        payload = json.loads(policy_path(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(payload["rules"][0]["origin_stage"], STAGE_01.slug)
        self.assertEqual(payload["rules"][0]["source"], "refinement")

    def test_a_restatement_does_not_manufacture_learning(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        again = record_correction(
            self.paths, stage=STAGE_03, attempt_no=1, text="  The DESIGN lacks a stated power analysis, and the sample size is unjustified!!  "
        )
        self.assertIsNone(again)
        self.assertEqual(len(load_policy(self.paths).rules), 1)

    def test_a_stage_number_does_not_make_two_rules_distinct(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text="Stage 03 must report an effect size for each comparison made.")
        again = record_correction(self.paths, stage=STAGE_03, attempt_no=1, text="Stage 05 must report an effect size for each comparison made.")
        self.assertIsNone(again)

    def test_a_thin_correction_is_not_a_rule(self) -> None:
        self.assertIsNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text="improve it"))
        self.assertIsNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=""))
        self.assertIsNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text="   "))
        self.assertEqual(load_policy(self.paths).rules, [])

    def test_the_rule_set_is_bounded(self) -> None:
        for index in range(MAX_RULES + 5):
            record_correction(
                self.paths, stage=STAGE_01, attempt_no=1,
                text=f"Distinct standing requirement number {index} that is long enough to be checkable.",
            )
        self.assertEqual(len(load_policy(self.paths).rules), MAX_RULES)

    def test_a_rollback_is_recorded_at_its_own_weight(self) -> None:
        rule = record_correction(
            self.paths, stage=STAGE_03, attempt_no=0, text=LONG, source="rollback"
        )
        self.assertEqual(rule.source, "rollback")

    def test_an_unknown_source_falls_back_rather_than_being_stored(self) -> None:
        rule = record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG, source="wishful")
        self.assertEqual(rule.source, "refinement")

    def test_a_corrupt_policy_does_not_take_the_run_down(self) -> None:
        policy_path(self.paths).write_text("not json", encoding="utf-8")
        self.assertEqual(load_policy(self.paths).rules, [])
        self.assertIsNotNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG))

    def test_min_rule_chars_is_actually_enforced_at_the_boundary(self) -> None:
        just_under = "x" * (MIN_RULE_CHARS - 1)
        just_over = "y" * MIN_RULE_CHARS
        self.assertIsNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=just_under))
        self.assertIsNotNone(record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=just_over))


class NormalizeTest(unittest.TestCase):
    def test_casing_spacing_and_punctuation_collapse(self) -> None:
        self.assertEqual(normalize_rule_text("  A  B,  c! "), normalize_rule_text("a b c"))

    def test_stage_numbers_collapse(self) -> None:
        self.assertEqual(normalize_rule_text("Stage 03 needs x"), normalize_rule_text("Stage 07 needs x"))

    def test_genuinely_different_text_stays_different(self) -> None:
        self.assertNotEqual(normalize_rule_text(LONG), normalize_rule_text(OTHER))


class PromptRenderingTest(PolicyTestBase):
    def test_an_empty_policy_renders_nothing(self) -> None:
        self.assertEqual(format_policy_for_prompt(ReviewPolicy()), "")

    def test_rules_are_rendered_with_their_provenance(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=2, text=LONG)
        rendered = format_policy_for_prompt(load_policy(self.paths))
        self.assertIn(LONG, rendered)
        self.assertIn("R001", rendered)
        self.assertIn(STAGE_01.slug, rendered)
        self.assertIn("must not be approved", rendered)

    def test_rollbacks_are_grouped_above_routine_refinements(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=OTHER)
        record_correction(self.paths, stage=STAGE_03, attempt_no=0, text=LONG, source="rollback")
        rendered = format_policy_for_prompt(load_policy(self.paths))
        self.assertLess(rendered.index("rolled back"), rendered.index("demanded this correction"))

    def test_a_stage_is_not_judged_against_rules_its_own_retries_invented(self) -> None:
        """The ratchet that made the retry loop non-convergent.

        Every review that demands anything records a rule, and the rules were injected
        into every later review including the *same* stage's next attempt — under a
        prompt saying a stage repeating a corrected mistake "must not be approved". So
        attempt 4 was refused for a requirement invented at attempt 3, and the bar rose
        by one requirement per attempt.

        Measured on the ResearchClawBench batch: `Information_001` learned 8 rules over
        Stage 02's 9 attempts and 7 over Stage 03's 9, and both exhausted the budget with
        `Last validation errors: None recorded`. `Astronomy_003`'s Stage 07 was reviewed
        against 33 rules of which **14 were its own**; it ran 15 attempts, and the task
        took 18.4 hours against 6.0 for the run that accumulated 6 rules.
        """
        record_correction(self.paths, stage=STAGE_01, attempt_no=3, text=LONG)
        record_correction(self.paths, stage=STAGE_03, attempt_no=1, text=OTHER)
        policy = load_policy(self.paths)

        own = format_policy_for_prompt(policy, stage=STAGE_01)
        self.assertNotIn(LONG, own, msg="Stage 01 was judged against its own retry's rule")
        self.assertIn(OTHER, own, msg="a rule from another stage must still bind")

    def test_a_stage_whose_only_rules_are_its_own_gets_no_block_at_all(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=2, text=LONG)
        self.assertEqual(format_policy_for_prompt(load_policy(self.paths), stage=STAGE_01), "")

    def test_cross_stage_accumulation_is_untouched(self) -> None:
        """The mechanism's actual purpose: a correction demanded once binds later stages."""
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        rendered = format_policy_for_prompt(load_policy(self.paths), stage=STAGE_03)
        self.assertIn(LONG, rendered)
        self.assertIn(STAGE_01.slug, rendered)

    def test_omitting_the_stage_still_renders_everything(self) -> None:
        """No caller is forced to scope, so the default cannot silently drop a rule."""
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        self.assertIn(LONG, format_policy_for_prompt(load_policy(self.paths)))

    def test_summary_counts_by_source(self) -> None:
        self.assertIn("no standing review rules", policy_summary(ReviewPolicy()))
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        self.assertIn("1 standing review rule", policy_summary(load_policy(self.paths)))


class ReviewerPromptTest(PolicyTestBase):
    """The loop only closes if the learned rules actually reach the next review."""

    def _reviewer(self):
        from src.approval_agent import AutomatedReviewer

        return AutomatedReviewer("claude", model="opus", fake_mode=True,
                                 ui=TerminalUI(output_stream=io.StringIO(), interactive=False))

    def test_a_learned_rule_reaches_the_next_review_prompt(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=2, text=LONG)
        prompt = self._reviewer()._build_review_prompt(
            paths=self.paths, stage=STAGE_03, attempt_no=1,
            stage_markdown="# Stage 03: Study Design\n", suggestions=["a", "b", "c"],
        )
        self.assertIn("Standing Review Rules", prompt)
        self.assertIn(LONG, prompt)

    def test_no_rules_means_no_section(self) -> None:
        prompt = self._reviewer()._build_review_prompt(
            paths=self.paths, stage=STAGE_01, attempt_no=1,
            stage_markdown="# Stage 01: Literature Survey\n", suggestions=["a", "b", "c"],
        )
        self.assertNotIn("Standing Review Rules", prompt)


class StubOperator:
    model = "stub"
    backend_name = "claude"


class ManagerRecordingTest(PolicyTestBase):
    """Corrections must be recorded from the real decision funnel, not a test-only path."""

    def _manager(self) -> ResearchManager:
        return ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.paths.run_root.parent,
            operator=StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )

    def _record(self, choice, *, feedback="", reason="", suggestions=None):
        self._manager()._record_review_correction(
            paths=self.paths, stage=STAGE_01, attempt_no=2,
            decision=ReviewDecision(choice=choice, decision_token="t", reason=reason, feedback=feedback),
            suggestions=suggestions or [LONG, OTHER, "third suggestion that is long enough to count"],
        )
        return load_policy(self.paths).rules

    def test_a_selected_suggestion_is_recorded(self) -> None:
        self.assertEqual(self._record("1")[0].text, LONG)

    def test_the_second_suggestion_is_recorded_when_chosen(self) -> None:
        self.assertEqual(self._record("2")[0].text, OTHER)

    def test_custom_feedback_is_recorded(self) -> None:
        self.assertEqual(self._record("4", feedback=OTHER)[0].text, OTHER)

    def test_an_approval_teaches_nothing(self) -> None:
        self.assertEqual(self._record("5", reason="looks good"), [])

    def test_a_verdict_nobody_could_read_teaches_nothing(self) -> None:
        """Unattended, an unreadable answer arrives here as choice "4" like a real refusal.

        The feedback on it is AutoR's own stand-in text, not something a reviewer asked
        for. Recorded as a rule it becomes a standing instruction injected into every later
        review in the run -- one transport failure permanently teaching a lesson nobody
        taught. Eleven of forty benchmark runs took this path.
        """
        from src.approval_agent import UNREADABLE_REASON

        rules = self._record(
            "4",
            reason=UNREADABLE_REASON + " AutoR stopped instead of approving blindly.",
            feedback="The automated reviewer could not be run, so this stage was not approved. "
                     "Re-examine the draft against the stage contract.",
        )
        self.assertEqual(rules, [])

    def test_a_crashed_reviewer_teaches_nothing(self) -> None:
        from src.approval_agent import CRASHED_REASON

        self.assertEqual(
            self._record("4", reason=CRASHED_REASON + " It exited -1.", feedback=OTHER), []
        )

    def test_an_unsupported_token_teaches_nothing(self) -> None:
        from src.approval_agent import UNSUPPORTED_REASON

        self.assertEqual(self._record("4", reason=UNSUPPORTED_REASON, feedback=OTHER), [])

    def test_a_real_refusal_still_teaches(self) -> None:
        """The exemption is for degraded verdicts only, not for refusals generally."""
        self.assertEqual(self._record("4", feedback=OTHER, reason="the ledger is wrong")[0].text, OTHER)

    def test_an_abort_teaches_nothing(self) -> None:
        self.assertEqual(self._record("6", reason="blocked"), [])

    def test_the_learned_rule_is_written_to_the_run_log(self) -> None:
        self._record("1")
        self.assertIn("review_rule_learned", read_text(self.paths.logs))

    def test_an_out_of_range_suggestion_index_does_not_crash(self) -> None:
        self.assertEqual(self._record("3", suggestions=["only one"]), [])


class RecursionTest(PolicyTestBase):
    def test_the_gate_is_monotonically_harder_across_stages(self) -> None:
        """The defining property: each correction permanently raises the bar."""
        rendered_sizes = []
        for index, stage in enumerate(STAGES[:4]):
            record_correction(
                self.paths, stage=stage, attempt_no=1,
                text=f"Requirement {index}: every claim must cite an artifact produced in this run.".replace(
                    "every claim", f"every claim of kind {index}"
                ),
            )
            rendered_sizes.append(len(format_policy_for_prompt(load_policy(self.paths))))
        self.assertEqual(rendered_sizes, sorted(rendered_sizes))
        self.assertEqual(len(load_policy(self.paths).rules), 4)

    def test_rules_survive_a_reload_so_later_stages_inherit_them(self) -> None:
        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=LONG)
        reloaded = ReviewPolicy.from_dict(load_policy(self.paths).to_dict())
        self.assertEqual(reloaded.rules[0].text, LONG)

    def test_a_hand_written_policy_round_trips(self) -> None:
        policy = ReviewPolicy(rules=[ReviewRule("R001", LONG, STAGE_01.slug, 1, "rollback")])
        save_policy(self.paths, policy)
        self.assertEqual(load_policy(self.paths).rules[0].source, "rollback")


if __name__ == "__main__":
    unittest.main()
