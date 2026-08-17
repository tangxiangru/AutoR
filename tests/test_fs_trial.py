"""The FrontierScience paired trial's decisions, none of which touch a process.

Everything in :mod:`src.fs_trial` is a pure function of already-parsed data, so all of
it can be tested at the cost of a dictionary rather than at the cost of a multi-day
kill-and-restart. What that buys is the part of the apparatus nobody can afford to
exercise for real: the ten admission clauses, the freeze-time refusals that exist
because a report-time refusal costs a whole trial, the duplicate-row fold, the
publication gate, and the state machine's answer to a driver that died with runs in
flight.

Every scanning assertion here carries a control, and every clause carries a negative
case as well as a positive one -- a clause tested only against a fixture built to
satisfy it is a clause that would still pass if its body were ``return True``.
"""

from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path

from src.frontierscience import (
    FS_FALLBACK_MARKER,
    FS_IDEATE_STAGE,
    FS_MAX_ANSWER_CHARS,
    FS_MIN_ANSWER_CHARS,
    FS_REFUSAL_ANSWER_IS_A_PLAN,
    FS_SOURCE_FALLBACK,
    FS_TASK_INSTRUCTION_SHA256,
)
from src.fs_trial import (
    FS_ADMISSION_CLAUSES,
    FS_FAKE_FAULTS,
    FS_MAX_REFUSAL_RATE,
    FS_STAGES_APPROVED_BY_KIND,
    FsAction,
    FsArmEvidence,
    FsArmSpec,
    FsRefusal,
    FsRunEnvironment,
    FsTrialPlan,
    admit_fs_arm,
    classify_fs_run,
    collect_fs_pairs,
    compare_fs_arms,
    fold_duplicate_rows,
    format_fs_trial_report,
    fs_arm_order,
    minimum_detectable_effect,
    next_actions,
    paired_difference_sd,
    subject_rollup,
    to_fs_run_record,
    wilson_interval,
)
from src.trials import DECLARED_OUTCOMES, FS_TOTAL

REPO = Path(__file__).resolve().parent.parent

#: A full-length commit, so the prefix relation the gate applies is exercised against
#: something a real ``git rev-parse`` would produce rather than against a seven-character
#: string that trivially equals the arm's.
SHA = "0b64ab8dda4c1e5f3a2b6d7e8f90112233445566"

CONTROL = FsArmSpec(
    label="direct-opus", kind="direct", model="opus", answer_guidance="minimal"
)
TREATMENT = FsArmSpec(
    label=f"{SHA[:7]}-autor-ideate",
    kind="autor",
    model="opus",
    answer_guidance="minimal",
    worktree="/tmp/worktree",
    sha=SHA[:7],
    review_model="opus",
    profile="ideate",
)


def env(**overrides) -> FsRunEnvironment:
    values = dict(
        dataset_sha256="96c0434a",
        judge_model="gpt-5.1",
        judge_reasoning_effort="high",
        answer_model="opus",
        answer_guidance="minimal",
        task_instruction_sha256=FS_TASK_INSTRUCTION_SHA256,
        disallowed_tools=("WebFetch", "WebSearch"),
        answer_attempts=1,
        judge_replicates=1,
    )
    values.update(overrides)
    return FsRunEnvironment(**values)


def facts(spec: FsArmSpec, **overrides) -> dict:
    """A fact set that every clause accepts, so a negative case is one edit away."""
    values = {
        "meta_status": "completed",
        "meta_pipeline_completed": True,
        "meta_stages_approved": list(FS_STAGES_APPROVED_BY_KIND[spec.kind]),
        "meta_auto_skipped_stages": [],
        "meta_answer_source": "agent",
        "answer_first_line_is_fallback": False,
        "answer_chars": 5_000,
        "answer_refusals": [],
        "operator": "claude",
        "truncated": False,
        "browsing_tool_calls": 0,
        "meta_model": spec.model,
        "revision_at_launch": SHA,
        "revision_at_finish": SHA,
        "worktree_dirty": False,
        "backend_calls": 4,
        "output_tokens_total": 12_000,
        "duration_seconds": 900,
    }
    values.update(overrides)
    return values


def evidence(
    spec: FsArmSpec = CONTROL,
    *,
    task="fs:000",
    points=(3.0,),
    subject="physics",
    duplicate_of=None,
    requested=1,
    environment=None,
    **fact_overrides,
) -> FsArmEvidence:
    total = sum(points) / len(points) if points else 0.0
    return FsArmEvidence(
        task_key=task,
        spec=spec,
        run_id=f"{task}-{spec.label}",
        workspace=f"/tmp/{task}",
        env=environment or env(),
        total_points=total,
        published_total=total,
        draw_points=tuple(points),
        draws_requested=requested,
        subject=subject,
        row_index=int(task.rsplit(":", 1)[-1]),
        duplicate_of=duplicate_of,
        facts=facts(spec, **fact_overrides),
    )


def plan(**overrides) -> FsTrialPlan:
    payload = {
        "capability": "fs_ideate_vs_direct_opus",
        "cost_note": "The treatment arm's per-task cost is UNMEASURED.",
        "dataset": "/tmp/research_test.jsonl",
        "dataset_sha256": "96c0434a",
        "tasks": ["fs:000", "fs:001"],
        "control": CONTROL.to_dict(),
        "treatment": TREATMENT.to_dict(),
        "state_dir": "/tmp/state",
    }
    payload.update(overrides)
    return FsTrialPlan.from_dict(payload)


def trial_of(*evidences, planned=1, **kwargs):
    return collect_fs_pairs(
        evidences,
        capability="fs_ideate_vs_direct_opus",
        control=CONTROL,
        treatment=TREATMENT,
        planned_pairs=planned,
        **kwargs,
    )


class TheGateRefusesAPairAndSaysWhichClauseDidTests(unittest.TestCase):
    """Ten clauses, each with a case that passes it and a case that does not.

    The negative cases are the point. A clause whose only fixture is one built to
    satisfy it would keep passing if its body were replaced by ``return True``, and the
    ledger would keep printing a zero beside its name.
    """

    def test_the_clause_list_is_the_ten_the_design_names(self) -> None:
        """The control for every subTest below: a shortened list would make them vacuous."""
        self.assertEqual(
            [clause.name for clause in FS_ADMISSION_CLAUSES],
            [
                "meta_status_completed",
                "pipeline_completed",
                "stages_approved_exactly",
                "answer_not_fallback",
                "no_auto_skips",
                "answer_within_bounds",
                "answer_not_truncated",
                "no_browsing",
                "producer_matches_arm",
                "every_draw_judged",
            ],
        )

    def test_a_clean_run_of_either_kind_is_admitted(self) -> None:
        for spec in (CONTROL, TREATMENT):
            with self.subTest(kind=spec.kind):
                admitted, failed = admit_fs_arm(evidence(spec))
                self.assertTrue(admitted, failed)

    def test_each_clause_refuses_exactly_the_run_it_is_about(self) -> None:
        broken = {
            "meta_status_completed": {"meta_status": "failed"},
            "pipeline_completed": {"meta_pipeline_completed": False},
            "stages_approved_exactly": {"meta_stages_approved": ["01_literature"]},
            "answer_not_fallback": {"meta_answer_source": FS_SOURCE_FALLBACK},
            "no_auto_skips": {"meta_auto_skipped_stages": ["02_hypothesis_generation"]},
            "answer_within_bounds": {"answer_chars": FS_MIN_ANSWER_CHARS - 1},
            "answer_not_truncated": {"truncated": True},
            "no_browsing": {"browsing_tool_calls": 3},
            "producer_matches_arm": {"meta_model": "sonnet"},
        }
        for name, override in broken.items():
            with self.subTest(clause=name):
                admitted, failed = admit_fs_arm(evidence(**override))
                self.assertFalse(admitted)
                self.assertIn(name, failed)

    def test_a_draw_the_judge_never_produced_refuses_the_pair(self) -> None:
        """`every_draw_judged` is the one clause a fact dictionary cannot express."""
        short = evidence(points=(3.0,), requested=3)
        self.assertIn("every_draw_judged", admit_fs_arm(short)[1])
        failed = replace(evidence(), judge_failures=("the judge returned no verdict",))
        self.assertIn("every_draw_judged", admit_fs_arm(failed)[1])

    def test_the_pipeline_clause_catches_the_abort_that_leaves_no_auto_skip(self) -> None:
        """The blocker regression, and the reason two clauses read one idea.

        `_route_to_deliverable` returns False when the final stage is the one already
        reached, which aborts the run with `auto_skipped_stages` still empty. So
        `no_auto_skips` is satisfied, and `pipeline_completed` is the only field that
        separates a pipeline that walked its stage from one that never entered it.
        """
        aborted = evidence(
            TREATMENT, meta_pipeline_completed=False, meta_auto_skipped_stages=[]
        )
        _admitted, failed = admit_fs_arm(aborted)
        self.assertEqual(failed, ["pipeline_completed"])

    def test_a_direct_arm_that_approved_a_stage_is_not_a_direct_arm(self) -> None:
        """The other half of the same blocker, in the direction that costs a control arm.

        The design table wrote this clause as "stages_approved is exactly
        `[02_hypothesis_generation]`" without qualification. Applied to an arm that has
        no manager and no reviewer, that refuses every control run of every pair -- so
        the expectation is per kind, and both halves are asserted here.
        """
        self.assertNotIn("stages_approved_exactly", admit_fs_arm(evidence(CONTROL))[1])
        self.assertIn(
            "stages_approved_exactly",
            admit_fs_arm(evidence(CONTROL, meta_stages_approved=[FS_IDEATE_STAGE]))[1],
        )
        self.assertIn(
            "stages_approved_exactly",
            admit_fs_arm(evidence(TREATMENT, meta_stages_approved=[]))[1],
        )

    def test_the_fallback_marker_refuses_a_run_whose_metadata_says_otherwise(self) -> None:
        """Two independent witnesses, because one of them is written by the party gated."""
        lying = evidence(meta_answer_source="agent", answer_first_line_is_fallback=True)
        self.assertIn("answer_not_fallback", admit_fs_arm(lying)[1])

    def test_a_null_browsing_witness_refuses_rather_than_passing(self) -> None:
        """None is not zero. A run that produced no transcript produced no testimony."""
        self.assertIn("no_browsing", admit_fs_arm(evidence(browsing_tool_calls=None))[1])
        self.assertNotIn("no_browsing", admit_fs_arm(evidence(browsing_tool_calls=0))[1])

    def test_a_boolean_cannot_stand_in_for_a_count(self) -> None:
        """`False == 0` in Python, so a field that turned into a flag would pass."""
        self.assertIn("no_browsing", admit_fs_arm(evidence(browsing_tool_calls=False))[1])

    def test_truncation_is_read_where_each_backend_says_it(self) -> None:
        claude = evidence(operator="claude", truncated=False)
        self.assertNotIn("answer_not_truncated", admit_fs_arm(claude)[1])
        responses = evidence(
            operator="codex",
            truncated=None,
            responses_status="completed",
            responses_incomplete_reason=None,
        )
        self.assertNotIn("answer_not_truncated", admit_fs_arm(responses)[1])
        cut = evidence(
            operator="codex",
            responses_status="incomplete",
            responses_incomplete_reason="max_output_tokens",
        )
        self.assertIn("answer_not_truncated", admit_fs_arm(cut)[1])

    def test_a_backend_that_recorded_neither_witness_is_refused(self) -> None:
        """The cost of the safe direction, asserted rather than left as a surprise."""
        silent = evidence(operator="codex", truncated=None)
        self.assertIn("answer_not_truncated", admit_fs_arm(silent)[1])

    def test_an_answer_that_is_a_plan_is_refused_at_a_legal_length(self) -> None:
        planlike = evidence(
            answer_chars=FS_MIN_ANSWER_CHARS + 50,
            answer_refusals=[FS_REFUSAL_ANSWER_IS_A_PLAN],
        )
        self.assertIn("answer_within_bounds", admit_fs_arm(planlike)[1])

    def test_the_length_bounds_are_the_adapter_s_and_not_a_second_copy(self) -> None:
        self.assertNotIn(
            "answer_within_bounds", admit_fs_arm(evidence(answer_chars=FS_MIN_ANSWER_CHARS))[1]
        )
        self.assertIn(
            "answer_within_bounds",
            admit_fs_arm(evidence(answer_chars=FS_MAX_ANSWER_CHARS + 1))[1],
        )

    def test_an_autor_arm_whose_worktree_moved_or_was_dirty_is_refused(self) -> None:
        for override in (
            {"revision_at_finish": "ffffffff" * 5},
            {"worktree_dirty": True},
            {"revision_at_launch": "", "revision_at_finish": ""},
        ):
            with self.subTest(**override):
                self.assertIn(
                    "producer_matches_arm", admit_fs_arm(evidence(TREATMENT, **override))[1]
                )

    def test_a_short_sha_inside_a_longer_one_is_not_a_prefix_match(self) -> None:
        """`0b64ab8` appearing somewhere inside a forty-character sha is chance."""
        elsewhere = "cc" + SHA[:7] + "dd" * 16
        self.assertIn(
            "producer_matches_arm",
            admit_fs_arm(
                evidence(TREATMENT, revision_at_launch=elsewhere, revision_at_finish=elsewhere)
            )[1],
        )


class TheRecordIsTheSeamAndRefusesWhatItCannotCarryTests(unittest.TestCase):
    def test_an_admitted_arm_becomes_one_stage_key_carrying_the_digest(self) -> None:
        item = evidence()
        record = to_fs_run_record(item, capability="cap")
        self.assertEqual(list(record.stage_fitness), [f"fs:000|{item.env.digest[:12]}"])
        self.assertEqual(record.stage_fitness[f"fs:000|{item.env.digest[:12]}"], 3.0)

    def test_the_decomposition_is_empty_and_that_is_the_claim(self) -> None:
        self.assertEqual(to_fs_run_record(evidence(), capability="cap").criterion_fitness, {})

    def test_a_refused_arm_cannot_reach_an_average_by_another_route(self) -> None:
        with self.assertRaises(ValueError) as caught:
            to_fs_run_record(evidence(meta_status="failed"), capability="cap")
        self.assertIn("not a measurement", str(caught.exception))

    def test_a_total_off_the_rubric_s_scale_is_refused(self) -> None:
        """Where the sibling checks that weights sum to 1.0, this checks the scale.

        A FrontierScience rubric sums to 10.0 and the judge returns a scalar, so there is
        no weighting to verify; what is verifiable is that the scalar is on the scale it
        claims to be on, which a parse of the judge's prose need not be.
        """
        for total in (-0.5, 10.5):
            with self.subTest(total=total):
                bad = replace(evidence(), total_points=total, published_total=total)
                with self.assertRaises(ValueError) as caught:
                    to_fs_run_record(bad, capability="cap")
                self.assertIn("outside", str(caught.exception))

    def test_the_two_readers_of_one_number_have_to_agree(self) -> None:
        drifted = replace(evidence(), published_total=4.0)
        with self.assertRaises(ValueError) as caught:
            to_fs_run_record(drifted, capability="cap")
        self.assertIn("reconcile", str(caught.exception))

    def test_a_total_inside_the_scale_reconciled_is_accepted(self) -> None:
        """The control for the two refusals above."""
        ok = replace(evidence(points=(9.75,)), published_total=9.75)
        self.assertEqual(
            list(to_fs_run_record(ok, capability="cap").stage_fitness.values()), [9.75]
        )


class TheMeasureIsDeclaredByTheProducerTests(unittest.TestCase):
    def test_the_outcome_is_in_the_registry(self) -> None:
        self.assertIs(DECLARED_OUTCOMES["fs_research_total"], FS_TOTAL)
        self.assertEqual(FS_TOTAL.selected_on_by, frozenset())

    def test_the_trial_declares_it_and_the_caller_cannot(self) -> None:
        result = trial_of(evidence(CONTROL), evidence(TREATMENT)).result
        self.assertEqual(result.outcome, FS_TOTAL)
        self.assertNotIn(
            "outcome", collect_fs_pairs.__code__.co_varnames[: collect_fs_pairs.__code__.co_argcount]
        )

    def test_the_unit_reaches_the_mean_difference_line(self) -> None:
        trial = trial_of(evidence(CONTROL, points=(2.0,)), evidence(TREATMENT, points=(5.0,)))
        rendered = format_fs_trial_report(trial, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1")
        self.assertIn("**+3.0000** FrontierScience rubric points (0-10)", rendered)


class TheEnvironmentDigestExcludesAConfoundedPairTests(unittest.TestCase):
    def test_two_arms_told_different_things_are_not_a_pair(self) -> None:
        trial = trial_of(
            evidence(CONTROL),
            evidence(TREATMENT, environment=env(answer_guidance="coverage")),
        )
        self.assertEqual(trial.result.n, 0)
        self.assertIn("answer_guidance", dict(trial.result.excluded)["fs:000"])

    def test_the_same_environment_pairs(self) -> None:
        """The control: without it the assertion above passes for any two arms."""
        self.assertEqual(trial_of(evidence(CONTROL), evidence(TREATMENT)).result.n, 1)

    def test_every_digest_field_moves_the_key(self) -> None:
        base = env()
        for spec in base.__dataclass_fields__:
            with self.subTest(field=spec):
                current = getattr(base, spec)
                moved = 99 if isinstance(current, int) else ("moved",) if isinstance(current, tuple) else "moved"
                self.assertNotEqual(base.digest, replace(base, **{spec: moved}).digest)

    def test_the_diff_names_the_field_the_digest_only_excluded(self) -> None:
        reasons = compare_fs_arms(
            evidence(CONTROL), evidence(TREATMENT, environment=env(judge_model="gpt-5"))
        )
        self.assertTrue(any("judge_model" in reason for reason in reasons))
        self.assertEqual(compare_fs_arms(evidence(CONTROL), evidence(TREATMENT)), [])


class TheByteIdenticalRowsBecomeOnePairTests(unittest.TestCase):
    """Rows 6 and 11 of the split are the same question, so they are one observation."""

    def _both(self, task, duplicate_of, control_points, treatment_points):
        return [
            evidence(CONTROL, task=task, duplicate_of=duplicate_of, points=(control_points,)),
            evidence(TREATMENT, task=task, duplicate_of=duplicate_of, points=(treatment_points,)),
        ]

    def test_the_duplicate_rows_collapse_into_one_pair(self) -> None:
        items = self._both("fs:006", None, 2.0, 4.0) + self._both("fs:011", 6, 3.0, 4.0)
        trial = trial_of(*items, planned=2)
        self.assertEqual(trial.result.n, 1)
        self.assertEqual(trial.folded, (("fs:006", ("fs:006", "fs:011")),))
        # mean of the two differences: (4-2 + 4-3) / 2
        self.assertAlmostEqual(trial.result.mean_difference, 1.5)

    def test_the_fold_is_the_mean_of_the_two_differences(self) -> None:
        """Asserted as the identity rather than as a number, because the identity is the
        reason a per-arm mean is allowed to stand in for a mean of differences."""
        items = self._both("fs:006", None, 1.0, 8.0) + self._both("fs:011", 6, 5.0, 6.0)
        trial = trial_of(*items, planned=2)
        self.assertAlmostEqual(trial.result.mean_difference, ((8 - 1) + (6 - 5)) / 2)

    def test_a_member_admitted_for_only_one_arm_is_dropped_from_both(self) -> None:
        """Averaging a two-run arm against a one-run arm is a different estimator."""
        items = self._both("fs:006", None, 2.0, 4.0)
        items.append(evidence(CONTROL, task="fs:011", duplicate_of=6, points=(9.0,)))
        trial = trial_of(*items, planned=2)
        self.assertEqual(trial.result.n, 1)
        self.assertAlmostEqual(trial.result.mean_difference, 2.0)

    def test_the_fold_can_be_switched_off_and_then_both_rows_are_pairs(self) -> None:
        items = self._both("fs:006", None, 2.0, 4.0) + self._both("fs:011", 6, 3.0, 4.0)
        trial = trial_of(*items, planned=2, dedupe_pairs=False)
        self.assertEqual(trial.result.n, 2)

    def test_a_fold_over_two_environments_is_refused_rather_than_averaged(self) -> None:
        items = self._both("fs:006", None, 2.0, 4.0)
        items += [
            evidence(CONTROL, task="fs:011", duplicate_of=6, points=(3.0,),
                     environment=env(judge_model="gpt-5")),
            evidence(TREATMENT, task="fs:011", duplicate_of=6, points=(4.0,),
                     environment=env(judge_model="gpt-5")),
        ]
        folded, _folds, notes = fold_duplicate_rows(
            items, control_arm=CONTROL.label, treatment_arm=TREATMENT.label
        )
        self.assertEqual(folded, [])
        self.assertEqual(len(notes), 2)
        self.assertIn("different environments", notes[0])

    def test_a_task_with_no_duplicate_passes_through_untouched(self) -> None:
        """The control: a fold that changed a non-duplicate would be invisible above."""
        items = self._both("fs:000", None, 2.0, 4.0)
        folded, folds, notes = fold_duplicate_rows(
            items, control_arm=CONTROL.label, treatment_arm=TREATMENT.label
        )
        self.assertEqual(sorted(item.task_key for item in folded), ["fs:000", "fs:000"])
        self.assertEqual((folds, notes), ([], []))

    def test_the_report_says_the_population_is_not_the_paper_s(self) -> None:
        items = self._both("fs:006", None, 2.0, 4.0) + self._both("fs:011", 6, 3.0, 4.0)
        rendered = format_fs_trial_report(
            trial_of(*items, planned=2),
            plan=plan(tasks=["fs:006", "fs:011"]),
            judge_model="gpt-5.1",
        )
        self.assertIn("not over the paper's sixty-row population", rendered)


class TheReportRefusesToPublishABiasedDifferenceTests(unittest.TestCase):
    def _lopsided(self, refused: int, admitted: int):
        items = []
        refusals = []
        for index in range(admitted):
            task = f"fs:{index:03d}"
            items += [evidence(CONTROL, task=task), evidence(TREATMENT, task=task)]
        for index in range(admitted, admitted + refused):
            task = f"fs:{index:03d}"
            items += [
                evidence(CONTROL, task=task),
                evidence(TREATMENT, task=task, meta_status="failed"),
            ]
        return trial_of(*items, planned=admitted + refused), refusals

    def test_a_treatment_arm_over_the_ceiling_withholds_the_difference(self) -> None:
        trial, _ = self._lopsided(refused=3, admitted=5)
        self.assertGreater(trial.refusal_rate(TREATMENT.label), FS_MAX_REFUSAL_RATE)
        rendered = format_fs_trial_report(
            trial, plan=plan(tasks=[f"fs:{i:03d}" for i in range(8)]), judge_model="gpt-5.1"
        )
        self.assertIn("The difference is not published", rendered)
        self.assertNotIn("mean difference:", rendered)
        self.assertNotIn("pass@>=", rendered)

    def test_a_trial_inside_the_ceiling_publishes(self) -> None:
        """The control. Without it the assertion above holds for every report."""
        trial, _ = self._lopsided(refused=1, admitted=9)
        self.assertLessEqual(trial.refusal_rate(TREATMENT.label), FS_MAX_REFUSAL_RATE)
        rendered = format_fs_trial_report(
            trial, plan=plan(tasks=[f"fs:{i:03d}" for i in range(10)]), judge_model="gpt-5.1"
        )
        self.assertNotIn("The difference is not published", rendered)
        self.assertIn("mean difference:", rendered)

    def test_both_arms_rates_are_printed_side_by_side_even_at_zero(self) -> None:
        trial = trial_of(evidence(CONTROL), evidence(TREATMENT))
        rendered = format_fs_trial_report(trial, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1")
        self.assertIn(f"control `{CONTROL.label}`: **0 refused**", rendered)
        self.assertIn(f"treatment `{TREATMENT.label}`: **0 refused**", rendered)

    def test_an_arm_with_nothing_finished_reports_no_rate_rather_than_zero(self) -> None:
        trial = trial_of(planned=1)
        self.assertIsNone(trial.refusal_rate(CONTROL.label))
        rendered = format_fs_trial_report(trial, plan=plan(tasks=["fs:000"]), judge_model="")
        self.assertIn("unmeasured (no run of this arm has reached a verdict)", rendered)

    def test_every_clause_is_listed_even_when_it_never_fired(self) -> None:
        trial = trial_of(evidence(CONTROL), evidence(TREATMENT))
        rendered = format_fs_trial_report(trial, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1")
        for clause in FS_ADMISSION_CLAUSES:
            self.assertIn(f"| `{clause.name}` | 0 |", rendered)

    def test_a_driver_refusal_is_in_the_ledger_and_not_missing_from_it(self) -> None:
        trial = trial_of(
            evidence(CONTROL),
            planned=1,
            driver_refusals=[FsRefusal("fs:000", TREATMENT.label, ("driver:stalled",))],
        )
        rendered = format_fs_trial_report(trial, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1")
        self.assertIn("| `driver:stalled` | 1 |", rendered)
        self.assertIn(f"`fs:000` / `{TREATMENT.label}`: driver:stalled", rendered)


class TheReportSaysWhatItWillNotPrintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.trial = trial_of(
            evidence(CONTROL, points=(2.0,)), evidence(TREATMENT, points=(5.0,))
        )
        self.rendered = format_fs_trial_report(
            self.trial, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1"
        )

    def test_the_empty_decomposition_reaches_the_renderer_without_raising(self) -> None:
        """The claim `criterion_fitness = {}` is safe, asserted rather than argued."""
        self.assertNotIn("| Criterion |", self.rendered)
        self.assertNotIn("Concentration:", self.rendered)

    def test_it_says_why_the_criterion_table_is_absent(self) -> None:
        self.assertIn("No per-rubric-item table and no concentration figure", self.rendered)
        self.assertIn("second, unvalidated instrument", self.rendered)

    def test_the_non_comparability_banner_is_always_printed(self) -> None:
        self.assertIn("not comparable to the paper's table", self.rendered)
        self.assertIn("gpt-5.1", self.rendered)

    def test_a_single_draw_reports_an_unmeasured_spread_and_never_zero(self) -> None:
        self.assertIn("judge sampling noise: **unmeasured (1 draw)**", self.rendered)
        self.assertNotIn("spread 0.000", self.rendered)

    def test_one_attempt_reports_unmeasured_between_attempt_variance(self) -> None:
        self.assertIn("between-attempt variance: **unmeasured (1 attempt", self.rendered)

    def test_every_published_number_carries_its_judge(self) -> None:
        for line in self.rendered.splitlines():
            if "mean rubric points," in line or "pass@>=7, " in line:
                self.assertIn("(judge `gpt-5.1`)", line)

    def test_a_judge_that_is_not_the_declared_one_is_called_out(self) -> None:
        rendered = format_fs_trial_report(
            self.trial, plan=plan(tasks=["fs:000"]), judge_model="gemini-2.5-flash"
        )
        self.assertIn("the judge that ran is not the judge the plan declared", rendered)

    def test_a_dataset_nobody_declared_is_called_out(self) -> None:
        odd = trial_of(
            evidence(CONTROL, environment=env(dataset_sha256="deadbeef")),
            evidence(TREATMENT, environment=env(dataset_sha256="deadbeef")),
        )
        rendered = format_fs_trial_report(odd, plan=plan(tasks=["fs:000"]), judge_model="gpt-5.1")
        self.assertIn("did not all answer the dataset the plan names", rendered)

    def test_the_upper_bound_on_the_claim_is_stated(self) -> None:
        self.assertIn("It is not a measurement of AutoR's capability", self.rendered)


class TheStatisticsBesideTheMeanTests(unittest.TestCase):
    def test_wilson_is_not_degenerate_where_wald_is(self) -> None:
        low, high = wilson_interval(0, 20)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.1)
        self.assertEqual(wilson_interval(0, 0), (0.0, 1.0))

    def test_wilson_brackets_the_measured_three_of_twenty_one(self) -> None:
        low, high = wilson_interval(3, 21)
        self.assertLess(low, 3 / 21)
        self.assertGreater(high, 3 / 21)

    def test_a_single_pair_has_no_sd_and_therefore_no_detectable_effect(self) -> None:
        self.assertIsNone(paired_difference_sd([1.0]))
        self.assertIsNone(minimum_detectable_effect(None, 1))

    def test_the_sd_is_the_sample_one(self) -> None:
        self.assertAlmostEqual(paired_difference_sd([1.0, 3.0]), 2 ** 0.5)

    def test_the_detectable_effect_shrinks_with_the_sample(self) -> None:
        small = minimum_detectable_effect(1.0, 4)
        large = minimum_detectable_effect(1.0, 64)
        self.assertGreater(small, large)
        self.assertAlmostEqual(small / large, 4.0)

    def test_a_trial_that_could_not_have_seen_its_own_effect_says_so(self) -> None:
        items = []
        for index, (left, right) in enumerate([(1.0, 9.0), (9.0, 1.0), (1.0, 9.0)]):
            task = f"fs:{index:03d}"
            items += [
                evidence(CONTROL, task=task, points=(left,)),
                evidence(TREATMENT, task=task, points=(right,)),
            ]
        rendered = format_fs_trial_report(
            trial_of(*items, planned=3),
            plan=plan(tasks=["fs:000", "fs:001", "fs:002"]),
            judge_model="gpt-5.1",
        )
        self.assertIn("could not have detected the effect it was designed around", rendered)

    def test_the_subject_rollup_reports_a_mean_and_an_n_and_no_rate(self) -> None:
        items = []
        for index, subject in enumerate(("physics", "chemistry", "biology")):
            task = f"fs:{index:03d}"
            items += [
                evidence(CONTROL, task=task, subject=subject, points=(2.0,)),
                evidence(TREATMENT, task=task, subject=subject, points=(8.0,)),
            ]
        rollup = subject_rollup(trial_of(*items, planned=3))
        self.assertEqual(sorted(rollup), ["biology", "chemistry", "physics"])
        for values in rollup.values():
            self.assertEqual(sorted(values), ["mean", "n"])

    def test_the_report_says_why_there_is_no_per_subject_pass_rate(self) -> None:
        rendered = format_fs_trial_report(
            trial_of(evidence(CONTROL), evidence(TREATMENT)),
            plan=plan(tasks=["fs:000"]),
            judge_model="gpt-5.1",
        )
        self.assertIn("No per-subject pass rate", rendered)


class ThePlanIsFrozenAndRefusesWhatWouldSpendATrialTests(unittest.TestCase):
    def test_a_direct_label_has_to_name_its_model(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(control={**CONTROL.to_dict(), "label": "off"})
        self.assertIn("does not name the model", str(caught.exception))
        # The control: the shipped label does name it.
        self.assertEqual(plan().control.label, "direct-opus")

    def test_an_autor_label_and_its_sha_must_prefix_match_both_ways(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(treatment={**TREATMENT.to_dict(), "label": "on"})
        self.assertIn("Label the arm with its commit", str(caught.exception))
        longer = {**TREATMENT.to_dict(), "label": SHA[:4], "sha": SHA[:7]}
        self.assertEqual(plan(treatment=longer).treatment.label, SHA[:4])

    def test_a_direct_arm_may_not_carry_an_autor_field(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(control={**CONTROL.to_dict(), "review_model": "opus"})
        self.assertIn("`direct` and sets `review_model`", str(caught.exception))

    def test_an_autor_arm_without_a_review_model_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(treatment={**TREATMENT.to_dict(), "review_model": ""})
        self.assertIn("names no review model", str(caught.exception))

    def test_arms_on_different_models_are_refused_at_freeze_and_not_at_report(self) -> None:
        """The twelve-runs defect, generalised: a digest field the plan sets differently.

        Both arms would run, both would be admitted, and every pair would then be
        excluded with "the two arms measured no stage in common" -- a true sentence about
        a spent trial.
        """
        with self.assertRaises(ValueError) as caught:
            plan(treatment={**TREATMENT.to_dict(), "model": "sonnet"})
        self.assertIn("different answer models", str(caught.exception))

    def test_arms_given_different_guidance_are_refused_at_freeze(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(treatment={**TREATMENT.to_dict(), "answer_guidance": "coverage"})
        self.assertIn("different guidance", str(caught.exception))

    def test_the_same_guidance_on_both_arms_is_accepted(self) -> None:
        """The control for both refusals above."""
        both = plan(
            control={**CONTROL.to_dict(), "answer_guidance": "coverage"},
            treatment={**TREATMENT.to_dict(), "answer_guidance": "coverage"},
        )
        self.assertEqual(both.control.answer_guidance, "coverage")

    def test_an_instruction_the_tree_no_longer_renders_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(task_instruction_sha256="00" * 32)
        self.assertIn("The prompt is the instrument", str(caught.exception))

    def test_an_unknown_field_is_refused_rather_than_ignored(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(judge_modl="gpt-5.1")
        self.assertIn("unknown plan fields", str(caught.exception))

    def test_an_unknown_arm_field_is_refused_too(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(control={**CONTROL.to_dict(), "reviewmodel": "opus"})
        self.assertIn("unknown arm fields", str(caught.exception))

    def test_the_digest_is_the_only_tolerated_extra(self) -> None:
        payload = plan().to_dict()
        payload["digest"] = "whatever"
        self.assertEqual(FsTrialPlan.from_dict(payload).digest, plan().digest)

    def test_a_repeated_task_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(tasks=["fs:000", "fs:000"])
        self.assertIn("repeats a key", str(caught.exception))

    def test_a_task_that_is_not_a_key_is_refused_before_a_launch(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(tasks=["Energy_001"])
        self.assertIn("not task keys", str(caught.exception))

    def test_every_digest_field_of_the_plan_moves_the_digest(self) -> None:
        base = plan()
        for name, value in (
            ("capability", "other"),
            ("judge_replicates", 3),
            ("dedupe_pairs", False),
            ("tasks", ["fs:000"]),
            ("cost_note", "UNMEASURED, differently"),
        ):
            with self.subTest(field=name):
                self.assertNotEqual(base.digest, plan(**{name: value}).digest)


class ThePlanMayNotImplyAScheduleNobodyMeasuredTests(unittest.TestCase):
    """The defect this whole integration was designed around, at the file it would land in."""

    def test_a_plan_with_an_autor_arm_must_admit_what_is_unmeasured(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(cost_note="About four hours per task, twelve hours in total.")
        self.assertIn("UNMEASURED", str(caught.exception))

    def test_a_plan_with_no_cost_note_at_all_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(cost_note="   ")
        self.assertIn("no `cost_note`", str(caught.exception))

    def test_a_trial_of_two_direct_arms_is_not_asked_for_the_word(self) -> None:
        """The exemption is narrow and the control shows where it stops.

        A direct arm's latency *is* measured -- 134.5 s mean over 21 tasks -- so a plan
        with no pipeline arm has nothing UNMEASURED to declare, and demanding the word
        anyway would train whoever writes the next plan to paste it in.
        """
        two_direct = plan(
            treatment={
                "label": "direct-sonnet", "kind": "direct", "model": "sonnet",
                "answer_guidance": "minimal",
            },
            control={
                "label": "direct-sonnet-b", "kind": "direct", "model": "sonnet",
                "answer_guidance": "minimal",
            },
            cost_note="Two direct arms: 134.5 s mean answer latency, 2.6 h of judge.",
        )
        self.assertEqual(two_direct.treatment.kind, "direct")

    def test_the_shipped_plan_says_the_pipeline_arm_is_unmeasured(self) -> None:
        payload = json.loads((REPO / "configs" / "fs_trial_001.json").read_text(encoding="utf-8"))
        shipped = FsTrialPlan.from_dict(payload)
        self.assertIn("UNMEASURED", shipped.cost_note)
        self.assertEqual(shipped.planned_pairs, 60)
        self.assertEqual(shipped.deadline, 0.0, "a shipped deadline is a schedule")
        self.assertTrue(shipped.dedupe_pairs)
        self.assertEqual(shipped.arm_order_mode, "counterbalanced")
        self.assertEqual(shipped.max_refusal_rate_for_publication, 0.20)
        self.assertEqual(shipped.minimum_effect_of_interest, 0.5)


class TheLaunchOrderTests(unittest.TestCase):
    def test_counterbalanced_alternates_within_pair_order(self) -> None:
        order = fs_arm_order(plan(tasks=["fs:000", "fs:001"]))
        self.assertEqual(
            order,
            (
                ("fs:000", CONTROL.label),
                ("fs:000", TREATMENT.label),
                ("fs:001", TREATMENT.label),
                ("fs:001", CONTROL.label),
            ),
        )

    def test_control_first_does_not(self) -> None:
        """The control: without it the assertion above cannot tell the modes apart."""
        order = fs_arm_order(plan(tasks=["fs:000", "fs:001"], arm_order_mode="control_first"))
        self.assertEqual([arm for _task, arm in order][1::2], [TREATMENT.label] * 2)

    def test_both_arms_of_one_task_are_adjacent(self) -> None:
        order = fs_arm_order(plan(tasks=[f"fs:{i:03d}" for i in range(4)]))
        for index in range(0, len(order), 2):
            self.assertEqual(order[index][0], order[index + 1][0])


class TheStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.plan = plan(tasks=["fs:000", "fs:001", "fs:002"], concurrency=2)

    def launched(self, task, arm, pid, attempt=1):
        return {
            "task_key": task, "arm": arm, "attempt": attempt,
            "phase": "launched", "child_pid": pid,
        }

    def finished(self, task, arm, classification="ok", attempt=1):
        return {
            "task_key": task, "arm": arm, "attempt": attempt,
            "phase": "finished", "classification": classification,
        }

    def test_an_empty_state_directory_launches_up_to_the_budget(self) -> None:
        actions = next_actions(self.plan, [], now=0.0)
        self.assertEqual([action.kind for action in actions], ["launch", "launch"])

    def test_a_live_run_consumes_the_budget_rather_than_aborting(self) -> None:
        states = [self.launched("fs:000", CONTROL.label, 4242)]
        actions = next_actions(
            self.plan, states, now=0.0, live_pids=frozenset({4242})
        )
        self.assertNotIn("abort", [action.kind for action in actions])
        self.assertEqual([action.kind for action in actions], ["launch"])

    def test_the_budget_reaching_zero_returns_no_launch(self) -> None:
        """The control for the budget: with it full, the call above returns launches."""
        states = [
            self.launched("fs:000", CONTROL.label, 4242),
            self.launched("fs:000", TREATMENT.label, 4243),
        ]
        actions = next_actions(
            self.plan, states, now=0.0, live_pids=frozenset({4242, 4243})
        )
        self.assertEqual([action for action in actions if action.kind == "launch"], [])
        self.assertEqual([action.kind for action in actions], ["wait"])

    def test_a_launched_run_whose_pid_is_gone_is_abandoned_and_never_resumed(self) -> None:
        actions = next_actions(
            self.plan, [self.launched("fs:000", CONTROL.label, 4242)], now=0.0,
            live_pids=frozenset(),
        )
        self.assertEqual(actions[0].kind, "abandon")
        self.assertNotIn("resume", [action.kind for action in actions])

    def test_an_abandoned_attempt_is_relaunched_as_a_new_attempt(self) -> None:
        states = [{**self.launched("fs:000", CONTROL.label, 4242), "phase": "abandoned"}]
        actions = next_actions(self.plan, states, now=0.0)
        launch = next(a for a in actions if a.task_key == "fs:000" and a.arm == CONTROL.label)
        self.assertEqual((launch.kind, launch.attempt), ("launch", 2))

    def test_the_attempt_budget_is_a_ceiling_and_is_the_same_for_both_arms(self) -> None:
        for arm in (CONTROL.label, TREATMENT.label):
            with self.subTest(arm=arm):
                states = [
                    {**self.launched("fs:000", arm, 1, attempt=n), "phase": "abandoned"}
                    for n in (1, 2)
                ]
                actions = next_actions(self.plan, states, now=0.0)
                refusal = next(a for a in actions if a.task_key == "fs:000" and a.arm == arm)
                self.assertEqual(refusal.kind, "refuse")

    def test_a_fallback_or_incomplete_run_is_refused_and_not_retried(self) -> None:
        for classification in ("fallback", "incomplete"):
            with self.subTest(classification=classification):
                actions = next_actions(
                    self.plan,
                    [self.finished("fs:000", CONTROL.label, classification)],
                    now=0.0,
                )
                first = next(a for a in actions if a.task_key == "fs:000")
                self.assertEqual((first.kind, first.reason), ("refuse", classification))

    def test_a_stalled_or_crashed_run_is_retried_once(self) -> None:
        """The control for the refusal above: not every failure is terminal."""
        for classification in ("stalled", "crashed"):
            with self.subTest(classification=classification):
                actions = next_actions(
                    self.plan,
                    [self.finished("fs:000", CONTROL.label, classification)],
                    now=0.0,
                )
                first = next(a for a in actions if a.task_key == "fs:000")
                self.assertEqual((first.kind, first.attempt), ("launch", 2))

    def test_a_refused_cell_is_terminal(self) -> None:
        states = [{"task_key": "fs:000", "arm": CONTROL.label, "attempt": 0, "phase": "refused"}]
        actions = next_actions(self.plan, states, now=0.0)
        self.assertEqual([a for a in actions if a.arm == CONTROL.label and a.task_key == "fs:000"], [])

    def test_a_deadline_stops_new_runs_and_leaves_running_ones_alone(self) -> None:
        states = [self.launched("fs:000", CONTROL.label, 4242)]
        actions = next_actions(
            self.plan, states, now=100.0, live_pids=frozenset({4242}),
        )
        self.assertEqual([a.kind for a in actions], ["launch"])
        past = replace(self.plan, deadline=50.0)
        actions = next_actions(past, states, now=100.0, live_pids=frozenset({4242}))
        self.assertEqual([a.kind for a in actions], ["wait"])

    def test_the_final_pass_runs_once_and_then_the_trial_is_done(self) -> None:
        states = [
            self.finished(task, arm)
            for task in self.plan.tasks
            for arm in (CONTROL.label, TREATMENT.label)
        ]
        self.assertEqual(
            next_actions(self.plan, states, now=0.0), (FsAction("final_pass"),)
        )
        self.assertEqual(
            next_actions(self.plan, states, now=0.0, final_pass_done=True),
            (FsAction("done"),),
        )

    def test_the_same_state_directory_twice_gives_the_same_actions(self) -> None:
        states = [
            self.launched("fs:000", CONTROL.label, 4242),
            self.finished("fs:001", TREATMENT.label, "fallback"),
        ]
        first = next_actions(self.plan, states, now=0.0, live_pids=frozenset({4242}))
        second = next_actions(self.plan, list(states), now=0.0, live_pids=frozenset({4242}))
        self.assertEqual(first, second)
        self.assertTrue(first)

    def test_the_classifier_separates_a_crash_from_a_bad_answer(self) -> None:
        self.assertEqual(classify_fs_run({}), "crashed")
        self.assertEqual(classify_fs_run({"meta_present": True, "meta_status": "failed"}), "incomplete")
        self.assertEqual(
            classify_fs_run(
                {"meta_present": True, "meta_answer_source": FS_SOURCE_FALLBACK}
            ),
            "fallback",
        )
        self.assertEqual(
            classify_fs_run({"meta_present": True, "answer_first_line_is_fallback": True}),
            "fallback",
        )
        self.assertEqual(classify_fs_run({"stalled": True, "meta_present": True}), "stalled")
        self.assertEqual(
            classify_fs_run({"meta_present": True, "meta_status": "completed"}), "ok"
        )


class NoTrialModuleCanReachTheArchiveTests(unittest.TestCase):
    """The containment for `rubric_version = RUBRIC_VERSION` on a benchmark row.

    A FrontierScience total is 0-10 rubric points. Pooled into
    ``Archive.variant_fitness`` it would sit beside AutoR's [0, 1] rubric means *and*
    ResearchClawBench's 0-100 totals -- three units in one bucket -- and steer topology
    promotion off a unit error. Prose in a docstring is not a guard: the guard is that no
    archive is constructible from any of these files.
    """

    POPULATION = (
        "src/fs_trial.py",
        "tools/fs_trial.py",
        "src/fs_scoring.py",
        "tools/score_fs_run.py",
        "src/trial_driver.py",
    )

    def test_no_scoring_or_trial_module_can_reach_the_archive(self) -> None:
        for name in self.POPULATION:
            body = (REPO / name).read_text(encoding="utf-8")
            for forbidden in ("Archive(", "record_run", "runs.jsonl"):
                self.assertNotIn(forbidden, body, f"{name} can reach the archive via {forbidden}")

    def test_the_scan_would_notice_the_thing_it_forbids(self) -> None:
        """The control. A scan over files that could never contain the string asserts
        nothing, so the same three needles are checked against a body that has them."""
        body = "Archive(path)\narchive.record_run(row)\nopen('runs.jsonl')\n"
        for forbidden in ("Archive(", "record_run", "runs.jsonl"):
            self.assertIn(forbidden, body)

    def test_every_file_in_the_population_exists(self) -> None:
        """The other control: a renamed file would silently leave the fence empty."""
        for name in self.POPULATION:
            self.assertTrue((REPO / name).is_file(), name)


class TheDryRunKnobsAreDryRunOnlyTests(unittest.TestCase):
    def test_a_fault_may_not_be_injected_into_a_real_arm(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(fake_faults=["browse"], operator="claude")
        self.assertIn("dry-run knob", str(caught.exception))

    def test_a_fault_nobody_injects_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            plan(fake_faults=["explode"], operator="fake")
        self.assertIn("unknown fake_faults", str(caught.exception))

    def test_every_declared_fault_names_a_clause_that_exists(self) -> None:
        names = {clause.name for clause in FS_ADMISSION_CLAUSES}
        for fault, clause in FS_FAKE_FAULTS.items():
            with self.subTest(fault=fault):
                self.assertIn(clause, names)


class TheFallbackMarkerIsTheAdapterSTests(unittest.TestCase):
    def test_the_driver_and_the_adapter_agree_on_the_marker(self) -> None:
        """One string, one definition. Two copies of a marker is how a witness stops
        witnessing: the exporter writes one spelling and the gate looks for another."""
        driver = (REPO / "tools" / "fs_trial.py").read_text(encoding="utf-8")
        self.assertIn("FS_FALLBACK_MARKER", driver)
        self.assertNotIn(f'"{FS_FALLBACK_MARKER}"', driver)


if __name__ == "__main__":
    unittest.main()
