"""The benchmark seam, and the ten ways a run fails to be a measurement.

The whole apparatus is one producer feeding :mod:`src.trials`, so almost every rule
worth holding is a rule about what gets into ``stage_fitness`` and
``criterion_fitness`` — and about what is refused before it gets there. Each test below
is written to die when its rule is mutated, because a gate over internal artifacts does
not fail loudly when one of them drifts: it stops refusing.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.rcb_trial import (
    ADMISSION_CLAUSES,
    RCB_TOTAL,
    SETTLED_REASONING_HEADING,
    ArmEvidence,
    ArmSpec,
    Refusal,
    RunEnvironment,
    ScoredItem,
    TrialPlan,
    admit_arm,
    arm_order,
    classify_run,
    collect_rcb_pairs,
    compare_arms,
    count_quota_hits,
    format_rcb_trial_report,
    items_from_score_payloads,
    judge_draws_in,
    next_action,
    pair_resolution,
    resolution_is_measured,
    run_status_of,
    stratum_rollup,
    to_run_record,
    truncated,
)

# Private on purpose — it is one rule shared by the classifier and the admission clause,
# and the test below is here to keep it one rule.
from src.rcb_trial import _QUOTA_MARKERS

REPO_ROOT = Path(__file__).resolve().parent.parent

GOOD_FACTS = {
    "meta_status": "completed",
    "meta_pipeline_completed": True,
    "meta_report_source": "agent",
    "autor_run_count": 1,
    "images_under_outputs": 0,
    "report_md_count": 1,
    "report_md_present": True,
    "last_event": "run.completed",
    "resource_exhausted_hits": 0,
    "revision_at_launch": "621566bdeadbeef",
    "revision_at_finish": "621566bdeadbeef",
    "worktree_dirty": False,
}


def env(**overrides) -> RunEnvironment:
    base = dict(
        checklist_digest="cl",
        judge_model="gpt-5.1",
        agent_model="opus",
        review_model="opus",
        web_search_level="info",
        instructions_digest="ins",
        bench_revision="bench",
        judge_replicates=1,
    )
    base.update(overrides)
    return RunEnvironment(**base)


def items(*scores: float, weights=(0.5, 0.3, 0.2), kinds=("image", "text", "text")) -> tuple:
    return tuple(
        ScoredItem(
            index=index,
            kind=kinds[index],
            weight=weights[index],
            content_key=f"item-{index}",
            scores=(int(score),) if not isinstance(score, tuple) else score,
        )
        for index, score in enumerate(scores)
    )


def arm(
    task: str = "Energy_001",
    label: str = "621566b",
    *,
    scores=(40, 30, 20),
    facts: dict | None = None,
    environment: RunEnvironment | None = None,
    replicates: int = 1,
    requested: int = 0,
    images: tuple[int, int] = (1, 1),
    dose: bool = False,
    stages: tuple[str, ...] = ("01_s", "02_s"),
    judge_failures: tuple[str, ...] = (),
    weights=(0.5, 0.3, 0.2),
) -> ArmEvidence:
    scored = items(*scores, weights=weights)
    total = sum(item.weight * item.score for item in scored)
    merged = dict(GOOD_FACTS)
    merged["revision_at_launch"] = merged["revision_at_finish"] = label + "0" * 33
    merged.update(facts or {})
    return ArmEvidence(
        task_id=task,
        arm=label,
        run_id=f"{task}_{label}",
        workspace=f"/ws/{task}_{label}",
        # The replicate count lives in the environment, because two arms averaged over
        # different numbers of judge draws are a composition difference.
        env=environment or env(judge_replicates=replicates),
        items=scored,
        published_total=round(total, 2),
        replicates_requested=requested or replicates,
        images_shown=images[0],
        images_available=images[1],
        judge_failures=judge_failures,
        checklist_items_expected=len(scored),
        facts=merged,
        autor_stages_scored=stages,
        settled_reasoning_dose=dose,
    )


def trial(*evidences, planned: int = 1, driver_refusals=()):
    return collect_rcb_pairs(
        evidences,
        capability="pr175",
        control_arm="621566b",
        treatment_arm="47f3fbf",
        planned_pairs=planned,
        driver_refusals=driver_refusals,
    )


class SeamTests(unittest.TestCase):
    def test_the_pair_difference_is_the_benchmark_total_difference_exactly(self) -> None:
        """A mean over one element is that element.

        ``Pair._mean_over`` is unweighted and ResearchClawBench's total is weighted, so
        anything other than a single stage key publishes a number that is not the
        benchmark's total. With one key the two arithmetics cannot disagree.
        """
        control = arm(scores=(40, 30, 20))
        treatment = arm(label="47f3fbf", scores=(60, 30, 20))
        result = trial(control, treatment).result

        self.assertEqual(result.n, 1)
        expected = treatment.total_weighted - control.total_weighted
        self.assertAlmostEqual(result.pairs[0].difference, expected, places=9)
        self.assertAlmostEqual(expected, 0.5 * 20, places=9)

    def test_one_stage_key_per_record(self) -> None:
        record = to_run_record(arm(), capability="pr175")
        self.assertEqual(len(record.stage_fitness), 1)
        self.assertTrue(next(iter(record.stage_fitness)).startswith("Energy_001|"))

    def test_the_decomposition_sums_to_the_scalar(self) -> None:
        """The property AutoR's own decomposition does not have.

        Every shipped checklist's weights sum to 1.0, so per-item contributions sum to
        the total and ``concentration`` becomes literally the share of the movement in
        one checklist item.
        """
        record = to_run_record(arm(), capability="pr175")
        total = next(iter(record.stage_fitness.values()))
        self.assertAlmostEqual(sum(record.criterion_fitness.values()), total, places=9)

    def test_weights_that_do_not_sum_to_one_are_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            to_run_record(arm(weights=(0.5, 0.3, 0.1)), capability="pr175")
        self.assertIn("1.0", str(caught.exception))

    def test_a_single_replicate_must_reconcile_with_the_scorers_own_total(self) -> None:
        """One number, two encodings, and this is the only place they meet.

        ``score.py`` truncates every item score with ``int()`` and rounds the total to
        two places. Recomputing from the items is right, and it is right only as long as
        it still lands on the number the scorer published.
        """
        good = arm()
        to_run_record(good, capability="pr175")  # does not raise

        drifted = ArmEvidence(**{**good.__dict__, "published_total": good.published_total + 1.0})
        with self.assertRaises(ValueError) as caught:
            to_run_record(drifted, capability="pr175")
        self.assertIn("reconcile", str(caught.exception))

    def test_the_reconciliation_tolerates_only_the_scorers_rounding(self) -> None:
        good = arm()
        rounded = ArmEvidence(**{**good.__dict__, "published_total": good.published_total + 0.004})
        to_run_record(rounded, capability="pr175")

    def test_replicated_scoring_is_not_reconciled_against_one_pass(self) -> None:
        """Three replicate means are not the number a single pass published."""
        good = arm(replicates=3)
        drifted = ArmEvidence(**{**good.__dict__, "published_total": 0.0})
        to_run_record(drifted, capability="pr175")

    def test_duplicate_item_keys_are_refused(self) -> None:
        collided = ArmEvidence(
            **{
                **arm().__dict__,
                "items": tuple(
                    ScoredItem(0, "text", 0.5, f"c{n}", (40,)) for n in range(2)
                ),
                "checklist_items_expected": 2,
                "published_total": 40.0,
            }
        )
        with self.assertRaises(ValueError) as caught:
            to_run_record(collided, capability="pr175")
        self.assertIn("duplicate", str(caught.exception))

    def test_no_record_is_ever_written_to_an_archive(self) -> None:
        """The containment for `rubric_version = RUBRIC_VERSION` on a benchmark row.

        A benchmark row is not an AutoR rubric row, and the version it must carry to be
        ``usable`` is a claim it cannot support. Prose in a docstring is not a guard: the
        guard is that no archive is constructible from either file. Pooled into
        ``Archive.variant_fitness`` these 0-100 totals would sit beside [0, 1] rubric
        means and steer topology promotion off a unit error.
        """
        for name in ("src/rcb_trial.py", "tools/rcb_trial.py"):
            body = (REPO_ROOT / name).read_text(encoding="utf-8")
            for forbidden in ("Archive(", "record_run", "runs.jsonl"):
                self.assertNotIn(forbidden, body, f"{name} can reach the archive via {forbidden}")


class TheMeasureIsDeclaredHereTests(unittest.TestCase):
    """This module is the only thing that knows what filled `stage_fitness`.

    `collect_pairs` reads two dicts of floats and cannot tell a rubric mean from a
    judge's total, so the measure has to be declared by the producer — and the
    circularity refusal, which is a statement about a mechanism *and* a measure, then
    reads the capability against the one that was actually used.
    """

    def test_the_trial_declares_the_benchmark_as_its_measure(self) -> None:
        control = arm(scores=(40, 30, 20))
        treatment = arm(label="47f3fbf", scores=(60, 30, 20))
        self.assertEqual(trial(control, treatment).result.outcome, RCB_TOTAL)

    def test_the_champion_ratchet_is_reportable_against_the_judge(self) -> None:
        """The whole point of the seam, and what the keyed-on-the-string refusal broke.

        `EvolutionController.consider` is `argmax` on AutoR's own `score.total`. The
        judge here runs after the workspace is finished, against a checklist no stage
        was shown, so the ratchet cannot have optimised against it and the arm with
        rounds can lose. Refused, this trial printed "score the arms on a held-out
        judge, or a benchmark" over a report produced by exactly that.
        """
        finished = collect_rcb_pairs(
            [arm(scores=(40, 30, 20)), arm(label="47f3fbf", scores=(60, 30, 20))],
            capability="polish_rounds",
            control_arm="621566b",
            treatment_arm="47f3fbf",
            planned_pairs=1,
        )
        self.assertFalse(finished.result.circular)

        rendered = format_rcb_trial_report(finished)
        self.assertIn("- mean difference: **+10.0000**", rendered)
        self.assertNotIn("selects on the outcome measure", rendered)

    def test_the_measure_is_fixed_here_rather_than_asked_for(self) -> None:
        """An exemption a caller can request is an exemption a caller can grant itself.

        Two ways it could have been made requestable, both refused: a parameter on this
        function, and a field on `TrialPlan` — which would also have changed
        `TrialPlan.digest` and invalidated the plan frozen before the first launch.
        """
        import dataclasses
        import inspect

        self.assertNotIn("outcome", inspect.signature(collect_rcb_pairs).parameters)
        self.assertNotIn("selects_on", {f.name for f in dataclasses.fields(TrialPlan)})

    def test_the_report_takes_its_scale_from_the_measure(self) -> None:
        """The benchmark's scale used to be written out here as well as on the outcome.
        One string, two encodings, and the copy printed beside the number is the one a
        reader takes it from."""
        control = arm(scores=(40, 30, 20))
        treatment = arm(label="47f3fbf", scores=(60, 30, 20))
        rendered = format_rcb_trial_report(trial(control, treatment))
        self.assertIn(f"- mean difference: **+10.0000** {RCB_TOTAL.unit}", rendered)
        self.assertIn(f"- outcome: `rcb_total` — {RCB_TOTAL.measured_by}", rendered)


class EnvironmentTests(unittest.TestCase):
    def test_every_field_in_the_digest_shows_up_in_the_cross_arm_diff(self) -> None:
        """The digest is the gate; the diff is the only explanation of it.

        A field silently dropped from the diff leaves a pair excluded with "the two arms
        measured no stage in common", which is true and useless. A field dropped from
        the digest instead lets a confounded pair through. This holds the two in step
        field by field, so adding a field to :class:`RunEnvironment` without teaching the
        diff about it fails here.
        """
        import dataclasses

        base = env()
        for spec in dataclasses.fields(RunEnvironment):
            with self.subTest(field=spec.name):
                other = dataclasses.replace(base, **{spec.name: "CHANGED"})
                self.assertNotEqual(base.digest, other.digest, "field is not in the digest")
                reasons = base.describe_difference(other)
                self.assertTrue(
                    any(f"`{spec.name}`" in reason for reason in reasons),
                    f"{spec.name} changes the digest but is never named in the diff",
                )

    def test_an_environment_difference_excludes_the_pair_and_names_the_field(self) -> None:
        control = arm()
        treatment = arm(label="47f3fbf", environment=env(web_search_level="warn"))
        result = trial(control, treatment).result

        self.assertEqual(result.n, 0)
        self.assertEqual(len(result.excluded), 1)
        self.assertIn("web_search_level", result.excluded[0][1])

    def test_a_deliberate_off_and_a_working_search_are_not_the_same_environment(self) -> None:
        """The resolved level stopped separating the two things it was added to separate.

        ``--web-search off`` announces itself at ``level: info`` -- the right level for a
        deliberate choice -- and so does an ``auto`` that found a working backend. Since
        `rcb_agent.py` began accepting ``off``, an arm told not to browse and an arm that
        browsed freely could carry the identical ``web_search_level`` and hash the same,
        which is the confound the field exists to catch arriving from the other side. The
        requested mode is recorded next to it.
        """
        browsing = env(web_search_mode="auto", web_search_level="info")
        not_browsing = env(web_search_mode="off", web_search_level="info")

        self.assertNotEqual(browsing.digest, not_browsing.digest)
        self.assertTrue(
            any("web_search_mode" in reason
                for reason in browsing.describe_difference(not_browsing)),
            browsing.describe_difference(not_browsing),
        )
        self.assertEqual(trial(arm(), arm(label="47f3fbf", environment=not_browsing)).result.n, 0)

    def test_two_arms_that_asked_for_the_same_search_still_pair(self) -> None:
        """Control: the digest above differs because the mode differs, not because two
        environments built the same way now differ."""
        both = dict(web_search_mode="auto", web_search_level="info")
        self.assertEqual(env(**both).digest, env(**both).digest)
        self.assertEqual(
            trial(
                arm(environment=env(**both)),
                arm(label="47f3fbf", environment=env(**both)),
            ).result.n,
            1,
        )

    def test_a_different_judge_in_the_two_arms_is_not_a_comparison(self) -> None:
        """Judge choice is worth about sixteen points on identical artifacts."""
        control = arm()
        treatment = arm(label="47f3fbf", environment=env(judge_model="claude-opus-4-5"))
        self.assertEqual(trial(control, treatment).result.n, 0)

    def test_the_digest_and_the_diff_cannot_go_out_of_step_silently(self) -> None:
        """If a named reason exists and the pair survived, the gate has a hole.

        The assertion is what makes the split between gate and diagnostics safe. Drop a
        field from the digest and its diff line still fires — and then the pair reaches
        ``pairs`` with a written reason for excluding it, which raises here rather than
        being published.
        """
        control = arm()
        # Same environment digest, different checklist content keys: `compare_arms`
        # names it, and nothing in the stage key can see it.
        treatment = ArmEvidence(
            **{
                **arm(label="47f3fbf").__dict__,
                "items": tuple(
                    ScoredItem(index=item.index, kind=item.kind, weight=item.weight,
                               content_key=f"other-{item.index}", scores=item.scores)
                    for item in arm().items
                ),
            }
        )
        self.assertTrue(compare_arms(control, treatment))
        with self.assertRaises(AssertionError) as caught:
            trial(control, treatment)
        self.assertIn("out of step", str(caught.exception))


class AdmissionTests(unittest.TestCase):
    """One fixture per clause. A clause that has stopped firing is a silent hole."""

    BREAKERS = {
        "status_completed": {"meta_status": "running"},
        "pipeline_completed": {"meta_pipeline_completed": False},
        "report_from_agent": {"meta_report_source": "fallback"},
        "single_run_root": {"autor_run_count": 2},
        "no_images_under_outputs": {"images_under_outputs": 1},
        "single_report_md": {"report_md_count": 2},
        "backend_reached": {"last_event": "run.backend_unavailable"},
        "no_quota_in_logs": {"resource_exhausted_hits": 1},
        "revision_matches_arm": {"revision_at_finish": "deadbeef" * 5},
    }

    def test_a_clean_run_is_admitted(self) -> None:
        ok, failed = admit_arm(arm())
        self.assertTrue(ok, failed)

    def test_every_clause_refuses_on_its_own(self) -> None:
        for clause in ADMISSION_CLAUSES:
            if clause.name == "every_item_judged":
                continue
            with self.subTest(clause=clause.name):
                ok, failed = admit_arm(arm(facts=self.BREAKERS[clause.name]))
                self.assertFalse(ok)
                self.assertEqual(failed, [clause.name])

    def test_a_dirty_worktree_refuses_even_when_the_shas_agree(self) -> None:
        ok, failed = admit_arm(arm(facts={"worktree_dirty": True}))
        self.assertEqual(failed, ["revision_matches_arm"])

    def test_a_head_that_could_not_be_read_refuses_rather_than_matching_everything(self) -> None:
        """``git_head`` returns ``""`` whenever ``rev-parse`` exits non-zero.

        A worktree moved or deleted during a four-day trial, a directory that is not a
        repository, git not on the path: launch and finish are then both ``""``, they
        agree, and the prefix test degenerates because ``label.startswith("")`` is true of
        every label. The arm label is the only carrier of the revision, so a run admitted
        that way is a run nobody checked was the commit under test.
        """
        blank = arm(facts={"revision_at_launch": "", "revision_at_finish": ""})
        self.assertEqual(admit_arm(blank), (False, ["revision_matches_arm"]))

    def test_an_arm_label_that_is_not_the_sha_that_ran_refuses(self) -> None:
        """The arm label is the only carrier of the revision and nothing else checks it."""
        mislabelled = ArmEvidence(**{**arm().__dict__, "arm": "notasha"})
        self.assertIn("revision_matches_arm", admit_arm(mislabelled)[1])

    def test_a_judge_failure_refuses_and_kills_the_whole_pair(self) -> None:
        """Refusing one arm turns the pair into "no treatment arm" and hides the cause."""
        control = arm()
        treatment = arm(label="47f3fbf", judge_failures=("timeout",))
        outcome = trial(control, treatment)

        self.assertEqual(outcome.result.n, 0)
        self.assertEqual(len(outcome.refusals), 1)
        reason = dict(outcome.result.excluded)["Energy_001"]
        self.assertIn("every_item_judged", reason)
        self.assertNotIn("no `47f3fbf` arm", reason)

    def test_a_short_item_vector_refuses(self) -> None:
        short = ArmEvidence(**{**arm().__dict__, "checklist_items_expected": 5})
        self.assertIn("every_item_judged", admit_arm(short)[1])

    def test_an_empty_item_vector_refuses(self) -> None:
        empty = ArmEvidence(
            **{**arm().__dict__, "items": (), "checklist_items_expected": 0, "published_total": 0.0}
        )
        self.assertIn("every_item_judged", admit_arm(empty)[1])

    def test_a_refused_arm_never_becomes_a_record(self) -> None:
        with self.assertRaises(ValueError):
            to_run_record(arm(facts={"meta_report_source": "synthesized"}), capability="pr175")

    def test_every_clause_says_what_observation_motivated_it(self) -> None:
        for clause in ADMISSION_CLAUSES:
            self.assertGreater(len(clause.why), 60, f"{clause.name} does not argue for itself")


class ResolutionTests(unittest.TestCase):
    def test_the_resolution_is_the_weighted_worst_replicate_spread(self) -> None:
        """In total points, not raw item points.

        The rule it replaces — "a text item moving under thirty points is noise" — is in
        the wrong units: at ``w = 0.2`` thirty raw points is six total points, and the
        two readings differ by a factor of five.
        """
        control = arm(scores=((40, 40, 40), (30, 40, 50), (20, 20, 20)))
        treatment = arm(label="47f3fbf", scores=((40, 46, 40), (30, 30, 30), (20, 20, 20)))
        # image w=0.5 spread 6; text w=0.3 spread 20; text w=0.2 spread 0
        self.assertAlmostEqual(pair_resolution(control, treatment), 0.5 * 6 + 0.3 * 20, places=9)

    def test_the_stratum_identity_closes(self) -> None:
        control = arm(scores=(40, 30, 20))
        treatment = arm(label="47f3fbf", scores=(50, 45, 25))
        rollup = stratum_rollup(control, treatment)
        self.assertAlmostEqual(rollup["residual"], 0.0, places=9)
        self.assertAlmostEqual(rollup["strata"]["image"]["share"], 0.5, places=9)
        self.assertAlmostEqual(rollup["strata"]["text"]["share"], 0.5, places=9)


class ReplicateParityTests(unittest.TestCase):
    """What happens when the judge's draws go missing, which is the ordinary failure.

    ``final_pass`` gives each replicate two tries and then moves on writing nothing, so
    an arm scored once against an arm scored three times needs no exotic sequence of
    events. Every consequence of that used to point the same way: the delta moved, the
    stated uncertainty *shrank*, and the report printed the count of whichever arm it
    happened to read.
    """

    def test_two_arms_scored_a_different_number_of_times_are_not_a_comparison(self) -> None:
        """One un-averaged draw against a three-draw mean is not the pair's difference.

        It is also the direction that inflates: the single draw carries the judge's whole
        sampling range into the delta while the other arm has averaged its own away.
        """
        outcome = trial(
            arm(replicates=3, requested=3),
            arm(label="47f3fbf", replicates=1, requested=3),
        )
        self.assertEqual(outcome.result.n, 0)
        self.assertIn("judge_replicates", dict(outcome.result.excluded)["Energy_001"])

    def test_a_pair_scored_the_same_number_of_times_is_compared(self) -> None:
        self.assertEqual(trial(arm(replicates=3), arm(label="47f3fbf", replicates=3)).result.n, 1)

    def test_one_draw_cannot_state_a_resolution_of_zero(self) -> None:
        """Fewer draws produced a *smaller* stated uncertainty, which is backwards.

        With one draw every ``spread`` is 0, so the pair printed "judge resolution:
        ±0.00 total points" — the strongest claim on the page — about the one arm where
        nothing at all was observed of the judge's noise.
        """
        control = arm(replicates=1, requested=3)
        treatment = arm(label="47f3fbf", replicates=1, requested=3)
        self.assertFalse(resolution_is_measured(control, treatment))
        text = format_rcb_trial_report(trial(control, treatment))
        self.assertIn("**unmeasured**", text)
        self.assertNotIn("±0.00", text)

    def test_both_arms_draw_counts_are_printed_and_neither_stands_for_the_other(self) -> None:
        control = arm(replicates=3, requested=3, scores=((40, 40, 40), (30, 30, 30), (20, 20, 20)))
        treatment = arm(
            label="47f3fbf", replicates=3, requested=3,
            scores=((60, 60, 60), (30, 30, 30), (20, 20, 20)),
        )
        text = format_rcb_trial_report(trial(control, treatment))
        self.assertIn("judge draws: control **3**, treatment **3**, of 3 planned", text)
        self.assertNotIn("per arm)", text)

    def test_a_pair_scored_fewer_times_than_planned_says_so(self) -> None:
        text = format_rcb_trial_report(
            trial(arm(replicates=2, requested=3), arm(label="47f3fbf", replicates=2, requested=3))
        )
        self.assertIn("Under-replicated", text)
        self.assertIn("1 control and 1 treatment replicate scorings were planned", text)

    def test_a_fully_replicated_pair_is_not_disclaimed(self) -> None:
        text = format_rcb_trial_report(
            trial(arm(replicates=3, requested=3), arm(label="47f3fbf", replicates=3, requested=3))
        )
        self.assertNotIn("Under-replicated", text)

    def test_an_unrecorded_draw_count_still_meets_the_scorers_own_total(self) -> None:
        """``<= 1``, not ``== 1``. An evidence whose replicate count nobody recorded is a
        single pass until something says otherwise, and skipping the one place the two
        encodings of the total meet is not the safe way to guess."""
        good = arm(replicates=1)
        drifted = ArmEvidence(
            **{
                **good.__dict__,
                "env": env(judge_replicates=0),
                "published_total": good.published_total + 1.0,
            }
        )
        with self.assertRaises(ValueError) as caught:
            to_run_record(drifted, capability="pr175")
        self.assertIn("reconcile", str(caught.exception))


class ImagesShownTests(unittest.TestCase):
    """60.6% of the weight, chosen by an unsorted sweep, and previously never printed."""

    def test_the_images_the_judge_saw_are_printed_for_both_arms(self) -> None:
        text = format_rcb_trial_report(
            trial(arm(images=(4, 4)), arm(label="47f3fbf", images=(4, 4)))
        )
        self.assertIn("images shown to the judge: control **4** of 4, treatment **4** of 4", text)

    def test_an_arm_over_the_five_image_cap_says_the_evidence_differed(self) -> None:
        """A real workspace here already has six images under ``report/``.

        Four figures all shown against twelve figures of which an arbitrary five were
        shown is a difference in the evidence, not in the research, and it moves the
        stratum that carries most of the benchmark's weight.
        """
        text = format_rcb_trial_report(
            trial(arm(images=(4, 4)), arm(label="47f3fbf", images=(5, 12)))
        )
        self.assertIn("not shown the same evidence", text)
        self.assertIn("treatment arm's figures were over the scorer's cap", text)

    def test_two_arms_shown_the_same_figures_are_not_disclaimed(self) -> None:
        text = format_rcb_trial_report(
            trial(arm(images=(3, 3)), arm(label="47f3fbf", images=(3, 3)))
        )
        self.assertNotIn("not shown the same evidence", text)


class DriverRefusalLedgerTests(unittest.TestCase):
    """The deaths that never reach the gate, which are most of the deaths.

    A run killed by quota, by the watchdog, by a backend outage or by the scorer produces
    no evidence at all, so the gate cannot refuse it. Left out, the ledger printed "none"
    and the loss appeared only as "no `<arm>` arm" — the same sentence as an arm that was
    never launched — under a paragraph telling the reader to judge the whole trial on the
    per-arm death counts.
    """

    def quota_death(self, task: str = "Energy_001", arm_label: str = "47f3fbf") -> Refusal:
        return Refusal(task, arm_label, ("driver:quota",))

    def test_a_death_the_driver_refused_is_in_the_ledger(self) -> None:
        outcome = trial(arm(), driver_refusals=[self.quota_death()])
        self.assertEqual(len(outcome.refusals), 1)
        self.assertEqual(outcome.refusals_by_clause()["driver:quota"], 1)
        text = format_rcb_trial_report(outcome)
        self.assertIn("driver:quota", text)
        self.assertNotIn("- no run was refused.", text)

    def test_the_per_arm_count_sees_it(self) -> None:
        outcome = trial(arm(), driver_refusals=[self.quota_death()])
        self.assertEqual(outcome.refusals_by_arm(), {"621566b": 0, "47f3fbf": 1})
        self.assertIn(
            "control `621566b` 0, treatment `47f3fbf` 1", format_rcb_trial_report(outcome)
        )

    def test_the_pair_is_excluded_by_name_and_not_as_never_launched(self) -> None:
        outcome = trial(arm(), driver_refusals=[self.quota_death()])
        reason = dict(outcome.result.excluded)["Energy_001"]
        self.assertIn("was refused (driver:quota)", reason)
        self.assertNotIn("no `47f3fbf` arm", reason)

    def test_three_treatment_deaths_against_zero_control_deaths_are_visible(self) -> None:
        """The asymmetry is a result even though it has no number attached."""
        outcome = collect_rcb_pairs(
            [arm(task=task) for task in ("Energy_001", "Energy_002", "Astronomy_000")],
            capability="pr175",
            control_arm="621566b",
            treatment_arm="47f3fbf",
            planned_pairs=3,
            driver_refusals=[
                self.quota_death(task) for task in ("Energy_001", "Energy_002", "Astronomy_000")
            ],
        )
        self.assertEqual(outcome.refusals_by_arm(), {"621566b": 0, "47f3fbf": 3})
        text = format_rcb_trial_report(outcome)
        self.assertIn("control `621566b` 0, treatment `47f3fbf` 3", text)
        self.assertIn("manufactures a null", text)

    def test_the_per_arm_line_is_printed_even_when_nothing_died(self) -> None:
        """The paragraph tells the reader to judge the difference on this line, so a line
        that only appears once something has gone wrong is missing where it is needed."""
        text = format_rcb_trial_report(trial(arm(), arm(label="47f3fbf")))
        self.assertIn("control `621566b` 0, treatment `47f3fbf` 0", text)

    def test_an_arm_a_later_attempt_rescued_did_not_cost_a_pair(self) -> None:
        outcome = trial(
            arm(), arm(label="47f3fbf"), driver_refusals=[self.quota_death()]
        )
        self.assertEqual(outcome.refusals, ())
        self.assertEqual(outcome.result.n, 1)

    def test_one_arm_is_counted_once_however_many_ways_it_died(self) -> None:
        """The gate and the driver both have a claim on a fallback report; the reader is
        told to read the per-arm counts, and double counting them is a lie in the
        direction that looks like a finding."""
        outcome = trial(
            arm(),
            arm(label="47f3fbf", facts={"meta_report_source": "fallback"}),
            driver_refusals=[Refusal("Energy_001", "47f3fbf", ("driver:fallback",))],
        )
        self.assertEqual(outcome.refusals_by_arm()["47f3fbf"], 1)
        self.assertEqual(outcome.refusals[0].clauses, ("report_from_agent",))

    def test_the_zero_count_caveat_offers_the_reading_where_a_clause_cannot_fire(self) -> None:
        """Four clauses are pre-empted by the driver's own classification, so their zero
        does not mean "never violated"; it means the death arrived under a driver row."""
        text = format_rcb_trial_report(trial(arm(), arm(label="47f3fbf")))
        self.assertIn("cannot fire at all on this path", text)


class ReportTests(unittest.TestCase):
    def report(self, *evidences, planned=1, **kwargs) -> str:
        return format_rcb_trial_report(trial(*evidences, planned=planned), **kwargs)

    def test_the_refusal_ledger_is_above_the_total_and_counts_per_arm(self) -> None:
        """Three treatment deaths against zero control deaths is a result.

        It has no number attached, which is exactly why it cannot be a footnote under
        one.
        """
        text = self.report(
            arm(), arm(label="47f3fbf", facts={"meta_report_source": "fallback"}), planned=1
        )
        self.assertLess(text.index("Runs refused"), text.index("## The difference"))
        self.assertIn("`47f3fbf` 1", text)
        self.assertIn("`621566b` 0", text)

    def test_every_clause_gets_a_printed_count_even_at_zero(self) -> None:
        """A clause that stopped firing looks exactly like a clause never violated."""
        text = self.report(arm(), arm(label="47f3fbf"))
        for clause in ADMISSION_CLAUSES:
            self.assertIn(f"| `{clause.name}` |", text)

    def test_an_incomplete_trial_is_labelled_interim(self) -> None:
        text = self.report(arm(), arm(label="47f3fbf"), planned=3)
        self.assertIn("INTERIM — 1 of 3 planned pairs", text)
        self.assertIn("not this trial's result", text)

    def test_a_complete_trial_is_not_labelled_interim(self) -> None:
        self.assertNotIn("INTERIM", self.report(arm(), arm(label="47f3fbf"), planned=1))

    def test_the_refusal_bias_paragraph_appears_wherever_pairs_were_lost(self) -> None:
        text = self.report(arm(), arm(label="47f3fbf"), planned=3)
        self.assertIn("manufactures a null", text)

    def test_a_zero_dose_pair_is_refused_as_a_test_of_the_channel(self) -> None:
        """``build_block`` returns nothing when the run argued nothing.

        A treatment run that emitted an empty channel is indistinguishable from one that
        used it and gained nothing — unless the prompt is checked, which is the one
        thing that turns an uninformative null into a diagnosis.
        """
        text = self.report(arm(), arm(label="47f3fbf", dose=False))
        self.assertIn("Zero settled-reasoning dose", text)
        self.assertIn("not a test of it", text)

    def test_the_dose_marker_is_the_channel_that_carries_the_dose(self) -> None:
        """Not ``build_block``'s crux sub-heading, which is half the channel.

        ``build_block`` emits ``## Methodological questions this run settled`` inside
        ``if cruxes:``. A block built from rejected idea-pool candidates alone — one of
        the two things PR #175's channel routes — carries only ``## Hypotheses generated
        and not pursued``, and looking for the crux sub-heading published "this pair did
        not administer the channel" over a dose that was delivered.
        """
        from src.information_flow import CHANNELS

        channel = next(item for item in CHANNELS if item.key == "settled_reasoning")
        self.assertEqual(SETTLED_REASONING_HEADING, channel.heading)
        self.assertNotIn("Methodological questions", SETTLED_REASONING_HEADING)

    def test_a_dosed_pair_is_not_disclaimed(self) -> None:
        self.assertNotIn(
            "Zero settled-reasoning dose", self.report(arm(), arm(label="47f3fbf", dose=True))
        )

    def test_the_unit_is_benchmark_points_and_not_rubric_points(self) -> None:
        text = self.report(arm(), arm(label="47f3fbf"))
        self.assertIn("RCB points", text)
        self.assertNotIn("rubric points", text)

    def test_the_judge_is_printed_with_the_number(self) -> None:
        self.assertIn("gpt-5.1", self.report(arm(), arm(label="47f3fbf"), judge_model="gpt-5.1"))

    def test_a_judge_that_is_not_the_planned_one_is_said_so_beside_the_number(self) -> None:
        """The header stated the plan's field whatever had actually scored the runs.

        ``score_rcb_run.py`` builds its judge with ``args.model or`` its own fallback, so
        a dropped ``--model`` scores a whole trial with a model nobody chose — and judge
        choice is worth about sixteen points on identical artifacts, which is larger than
        anything this trial is looking for.
        """
        text = self.report(
            arm(), arm(label="47f3fbf"),
            judge_model="claude-opus-4-5", planned_judge_model="gpt-5.1",
        )
        self.assertIn("not the judge the plan declared", text)
        self.assertNotIn(
            "not the judge the plan declared",
            self.report(
                arm(), arm(label="47f3fbf"),
                judge_model="gpt-5.1", planned_judge_model="gpt-5.1",
            ),
        )

    def test_the_one_observation_caveat_sits_under_the_total(self) -> None:
        text = self.report(arm(), arm(label="47f3fbf"))
        self.assertIn("ran **once**", text)
        self.assertIn("zero observations", text)

    def test_a_stage_composition_difference_is_set_aside_from_the_score(self) -> None:
        """``shape_changes`` used to be structurally zero here. It is not any more.

        Both arms are scored against the same checklist whatever their internal
        composition, so ``stage_fitness`` carries one key each and the strongest refusal
        in :mod:`src.trials` was true and empty on this outcome measure — over exactly
        the pair it was written for. The first live pair is four stages against seven,
        one arm cancelled and one completed, and its totals were averaged as if they
        were two configurations of the same depth of run.
        """
        control = arm(stages=("01_s", "02_s", "03_s", "04_s"), scores=(40, 30, 20))
        treatment = arm(
            label="47f3fbf",
            stages=tuple(f"0{n}_s" for n in range(1, 8)),
            scores=(20, 30, 20),
        )
        outcome = trial(control, treatment)
        text = self.report(control, treatment)

        self.assertIn("did not score the same stages", text)
        self.assertEqual((outcome.result.n, outcome.result.shape_changes), (0, 1))
        self.assertIn("set aside: 1 shape-differing pair(s)", text)
        self.assertIn("there is no same-shape pair yet", text)
        # The delta is real and is reported as a set-aside, not as the result.
        self.assertAlmostEqual(outcome.result.shape_changed_mean, -10.0, places=6)
        self.assertAlmostEqual(outcome.result.mean_difference, 0.0, places=9)

    def test_two_arms_that_got_equally_far_are_still_one_pair(self) -> None:
        """The control on the change above: only the composition may move the verdict.

        A declaration that set every pair aside would look identical from the report's
        one shape-differing line, and would silently empty the trial.
        """
        outcome = trial(arm(stages=("01_s", "02_s")), arm(label="47f3fbf", stages=("01_s", "02_s")))
        self.assertEqual((outcome.result.n, outcome.result.shape_changes), (1, 0))
        self.assertNotIn(
            "set aside", format_rcb_trial_report(outcome)
        )

    def test_the_contrast_is_printed_verbatim(self) -> None:
        text = self.report(arm(), arm(label="47f3fbf"), contrast_log="47f3fbf one commit (#175)")
        self.assertIn("47f3fbf one commit (#175)", text)

    def test_the_per_pair_concentration_is_printed_beside_its_floor(self) -> None:
        text = self.report(arm(scores=(40, 30, 20)), arm(label="47f3fbf", scores=(60, 30, 20)))
        self.assertIn("Concentration on this pair: **100%**", text)
        self.assertIn("floor at 3 items: 33%", text)
        self.assertIn("different tasks into one denominator", text)


class PlanTests(unittest.TestCase):
    def plan(self, **kwargs) -> TrialPlan:
        base = dict(
            capability="pr175",
            bench="/bench",
            tasks=("Energy_001", "Astronomy_000", "Energy_002"),
            control=ArmSpec("621566b", "/wt/c", "621566b"),
            treatment=ArmSpec("47f3fbf", "/wt/t", "47f3fbf"),
        )
        base.update(kwargs)
        return TrialPlan(**base)

    def test_the_shipped_plan_names_pr_175_and_its_parent(self) -> None:
        """`be76a34` is #174, not #175. It changes `manager.py`, `archive.py` and
        `inference.py` and un-silences three stages, so running it as the treatment
        measures two PRs and reports one."""
        import json

        payload = json.loads(
            (REPO_ROOT / "configs" / "rcb_trial_175.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["control"]["sha"], "621566b")
        self.assertEqual(payload["treatment"]["sha"], "47f3fbf")
        self.assertNotIn("be76a34", json.dumps(payload))

    def test_the_shipped_plan_loads(self) -> None:
        import json

        payload = json.loads(
            (REPO_ROOT / "configs" / "rcb_trial_175.json").read_text(encoding="utf-8")
        )
        plan = TrialPlan.from_dict(payload)
        self.assertEqual(plan.planned_pairs, 3)
        self.assertFalse(plan.state_dir.startswith("/home/"), "state belongs off the shared NFS")

    def test_a_misspelled_plan_field_is_refused_rather_than_ignored(self) -> None:
        with self.assertRaises(ValueError) as caught:
            TrialPlan.from_dict(
                {
                    "capability": "c", "bench": "/b", "tasks": ["T"],
                    "control": {"label": "a", "worktree": "/x", "sha": "a"},
                    "treatment": {"label": "b", "worktree": "/y", "sha": "b"},
                    "reviewmodel": "opus",
                }
            )
        self.assertIn("reviewmodel", str(caught.exception))

    def test_two_arms_with_one_label_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            TrialPlan.from_dict(
                {
                    "capability": "c", "bench": "/b", "tasks": ["T"],
                    "control": {"label": "a", "worktree": "/x", "sha": "a"},
                    "treatment": {"label": "a", "worktree": "/y", "sha": "a"},
                }
            )

    def test_editing_the_plan_changes_its_digest(self) -> None:
        self.assertNotEqual(self.plan().digest, self.plan(judge_model="other").digest)

    def test_the_order_is_pair_major_and_control_first_by_default(self) -> None:
        """Both arms of a pair adjacent, so they straddle as little drift as possible."""
        self.assertEqual(
            arm_order(self.plan()),
            (
                ("Energy_001", "621566b"), ("Energy_001", "47f3fbf"),
                ("Astronomy_000", "621566b"), ("Astronomy_000", "47f3fbf"),
                ("Energy_002", "621566b"), ("Energy_002", "47f3fbf"),
            ),
        )

    def test_counterbalancing_is_available_and_alternates(self) -> None:
        order = arm_order(self.plan(arm_order_mode="counterbalanced"))
        self.assertEqual(order[0][1], "621566b")
        self.assertEqual(order[2][1], "47f3fbf")

    def test_the_first_task_is_the_one_that_carries_both_channels(self) -> None:
        """Twenty-four hours buys one pair. Which pair is a decision, not a shuffle."""
        import json

        payload = json.loads(
            (REPO_ROOT / "configs" / "rcb_trial_175.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["tasks"][0], "Energy_001")


class ClassifyTests(unittest.TestCase):
    def test_quota_is_found_in_the_runs_own_log_even_when_it_reported_completion(self) -> None:
        """``classify_backend`` only runs when neither attempt wrote a stage file.

        A 429 landing mid-stage is baked into the summary as prose, and the manifest
        says the run completed. Reading only the manifest retries nothing.
        """
        self.assertEqual(
            classify_run(
                {
                    "last_event": "run.completed",
                    "meta_status": "completed",
                    "meta_report_source": "agent",
                    "run_log_text": "google.api_core RESOURCE_EXHAUSTED: 429",
                }
            ),
            "quota",
        )

    def test_a_clean_run_classifies_ok(self) -> None:
        self.assertEqual(
            classify_run(
                {
                    "last_event": "run.completed", "meta_status": "completed",
                    "meta_report_source": "agent", "run_log_text": "fine",
                }
            ),
            "ok",
        )

    def test_a_fallback_report_is_not_a_completed_run(self) -> None:
        """A quota death exports a fallback report and records status completed."""
        self.assertEqual(
            classify_run(
                {
                    "last_event": "run.completed", "meta_status": "completed",
                    "meta_report_source": "fallback", "run_log_text": "",
                }
            ),
            "fallback",
        )

    def test_a_stalled_run_is_not_an_incomplete_one(self) -> None:
        self.assertEqual(classify_run({"stalled": True}), "stalled")

    def test_a_429_in_ordinary_research_output_is_not_a_quota_death(self) -> None:
        """All four real ``logs.txt`` on this box contain ``429``; none contains a marker.

        A chi2 value, a grep hit reading ``sources.json:429``, a table cell, and arXiv
        answering ``HTTP Error 429`` to a literature fetch that then succeeded. Reading a
        bare ``429`` classified every healthy run as a quota death, and that is not the
        safe direction to be wrong in: :func:`next_action` answers ``quota`` with two
        backoffs — 1800 s then 3600 s — and two relaunches per arm before refusing the
        pair, so a healthy three-task trial spends eighteen runs and nine hours of
        sleeping to publish zero pairs.
        """
        log = (
            "chi2 = 3.429 for the joint fit\n"
            'literature/sources.json:429:        "output": "..."\n'
            "2018 ERR HTTP Error 429: Unknown Error\n"
        )
        self.assertEqual(
            classify_run(
                {
                    "last_event": "run.completed", "meta_status": "completed",
                    "meta_report_source": "agent", "run_log_text": log,
                }
            ),
            "ok",
        )
        self.assertEqual(count_quota_hits(log), 0)

    def test_the_classifier_and_the_admission_clause_read_the_same_markers(self) -> None:
        """One rule about what a quota death is, not two tuples that drifted.

        ``count_quota_hits`` deliberately read a *prefix* of the classifier's markers, so
        a run the classifier sent to a backoff was a run the clause called clean.
        """
        for marker in _QUOTA_MARKERS:
            with self.subTest(marker=marker):
                log = f"API Error: {marker} for claude-sonnet-4-5\n"
                self.assertEqual(
                    classify_run(
                        {
                            "last_event": "run.completed", "meta_status": "completed",
                            "meta_report_source": "agent", "run_log_text": log,
                        }
                    ),
                    "quota",
                )
                self.assertEqual(count_quota_hits(log), 1)


class PlannerTests(unittest.TestCase):
    def plan(self, **kwargs) -> TrialPlan:
        base = dict(
            capability="pr175",
            bench="/bench",
            tasks=("T1",),
            control=ArmSpec("c", "/wt/c", "c"),
            treatment=ArmSpec("t", "/wt/t", "t"),
        )
        base.update(kwargs)
        return TrialPlan(**base)

    def test_an_empty_state_launches_the_control_arm_first(self) -> None:
        action = next_action(self.plan(), [], now=0.0)
        self.assertEqual((action.kind, action.task_id, action.arm, action.attempt),
                         ("launch", "T1", "c", 1))

    def test_a_surviving_child_aborts_rather_than_racing_it(self) -> None:
        """A ``setsid`` child outlives its driver, and two drivers is the concurrency
        that exhausts the quota that kills both."""
        states = [{"task_id": "T1", "arm": "c", "attempt": 1, "phase": "launched", "child_pid": 4242}]
        action = next_action(self.plan(), states, now=0.0, live_pids=frozenset({4242}))
        self.assertEqual(action.kind, "abort")
        self.assertIn("4242", action.reason)

    def test_a_dead_child_is_abandoned_and_never_resumed(self) -> None:
        """``rcb_agent.py`` has only ``--export-only``; ``main.py --resume-run`` on a
        benchmark workspace hits three false refusals because it passes neither
        ``artifact_roots`` nor ``min_report_figures``."""
        states = [{"task_id": "T1", "arm": "c", "attempt": 1, "phase": "launched", "child_pid": 4242}]
        action = next_action(self.plan(), states, now=0.0, live_pids=frozenset())
        self.assertEqual(action.kind, "abandon")
        self.assertIn("no resume", action.reason)

    def test_an_abandoned_attempt_is_re_planned_as_a_new_attempt(self) -> None:
        states = [{"task_id": "T1", "arm": "c", "attempt": 1, "phase": "abandoned"}]
        action = next_action(self.plan(), states, now=0.0)
        self.assertEqual((action.kind, action.attempt), ("launch", 2))

    def test_the_attempt_budget_is_finite(self) -> None:
        states = [
            {"task_id": "T1", "arm": "c", "attempt": n, "phase": "abandoned"} for n in (1, 2)
        ]
        self.assertEqual(next_action(self.plan(), states, now=0.0).kind, "refuse")

    def test_quota_backs_off_rather_than_refusing_the_pair(self) -> None:
        """Refusing on the first 429 most likely ends a four-day trial with zero pairs."""
        states = [
            {"task_id": "T1", "arm": "c", "attempt": 1, "phase": "finished",
             "classification": "quota"}
        ]
        action = next_action(self.plan(), states, now=0.0)
        self.assertEqual(action.kind, "backoff")
        self.assertGreaterEqual(action.seconds, 1800)

    def test_the_backoff_budget_is_finite(self) -> None:
        states = [
            {"task_id": "T1", "arm": "c", "attempt": n, "phase": "finished",
             "classification": "quota"}
            for n in (1, 2, 3)
        ]
        self.assertEqual(next_action(self.plan(), states, now=0.0).kind, "refuse")

    def test_a_fallback_run_is_refused_rather_than_retried(self) -> None:
        states = [
            {"task_id": "T1", "arm": "c", "attempt": 1, "phase": "finished",
             "classification": "fallback"}
        ]
        self.assertEqual(next_action(self.plan(), states, now=0.0).kind, "refuse")

    def test_a_refusal_is_terminal_and_does_not_loop(self) -> None:
        states = [{"task_id": "T1", "arm": "c", "attempt": 0, "phase": "refused"}]
        self.assertEqual(next_action(self.plan(), states, now=0.0).arm, "t")

    def test_a_finished_run_is_scored_before_the_next_one_launches(self) -> None:
        """A gate that refuses everything must be visible after run one, not day five."""
        states = [
            {"task_id": "T1", "arm": "c", "attempt": 1, "phase": "finished",
             "classification": "ok"}
        ]
        self.assertEqual(next_action(self.plan(), states, now=0.0).kind, "score")

    def test_the_deadline_stops_new_launches_and_nothing_else(self) -> None:
        """No per-run wall clock: a measured 15.8-hour run finished properly."""
        plan = self.plan(deadline=100.0)
        self.assertEqual(next_action(plan, [], now=200.0).kind, "final_pass")
        self.assertEqual(next_action(plan, [], now=50.0).kind, "launch")

    def test_the_final_pass_runs_once_and_then_the_trial_is_done(self) -> None:
        states = [
            {"task_id": "T1", "arm": a, "attempt": 1, "phase": "finished",
             "classification": "ok", "scored": True}
            for a in ("c", "t")
        ]
        self.assertEqual(next_action(self.plan(), states, now=0.0).kind, "final_pass")
        self.assertEqual(
            next_action(self.plan(), states, now=0.0, final_pass_done=True).kind, "done"
        )


class ReplicateTests(unittest.TestCase):
    def test_replicates_zip_by_position_and_identity_is_checked(self) -> None:
        payloads = [
            {"items": [{"index": 0, "type": "text", "weight": 1.0, "content": "a", "score": 40}]},
            {"items": [{"index": 0, "type": "text", "weight": 1.0, "content": "a", "score": 50}]},
        ]
        scored = items_from_score_payloads(payloads)
        self.assertEqual(scored[0].scores, (40, 50))
        self.assertEqual(scored[0].score, 45.0)
        self.assertEqual(scored[0].spread, 10)

    def test_a_checklist_that_changed_between_replicates_is_refused(self) -> None:
        payloads = [
            {"items": [{"index": 0, "type": "text", "weight": 1.0, "content": "a", "score": 40}]},
            {"items": [{"index": 0, "type": "text", "weight": 1.0, "content": "b", "score": 50}]},
        ]
        with self.assertRaises(ValueError) as caught:
            items_from_score_payloads(payloads)
        self.assertIn("item identity", str(caught.exception))


class DrawsInsideOneFileTests(unittest.TestCase):
    """A file is a checkpoint. A draw is a judge pass. They were the same number once.

    ``final_pass`` writes one draw per file, so ``len(payloads)`` was the draw count and
    reading ``item["score"]`` was reading the draw. Both stop being true the moment the
    scorer is asked for ``--draws N``, which is what the in-loop score now does — and
    they stop being true silently and in the direction that publishes: an arm the report
    calls single-draw is an arm whose measured spread the report then declines to state.
    """

    def folded(self, *draws: tuple[int, ...]) -> dict:
        """One score file as ``score_rcb_run.aggregate_draws`` actually writes it."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "score_rcb_run", REPO_ROOT / "tools" / "score_rcb_run.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module.aggregate_draws(
            [
                {
                    "items": [
                        {"index": i, "type": "text", "weight": 0.5, "content": f"c{i}", "score": s}
                        for i, s in enumerate(scores)
                    ],
                    "total_score": sum(0.5 * s for s in scores),
                    "judge_calls": len(scores),
                    "judge_failures": [],
                }
                for scores in draws
            ]
        )

    def test_one_file_of_three_draws_counts_as_three(self) -> None:
        payload = self.folded((40, 20), (60, 20), (50, 20))
        self.assertEqual(payload["draws"], 3)
        self.assertEqual(judge_draws_in([payload]), 3)

    def test_three_files_of_one_draw_still_count_as_three(self) -> None:
        """The two ways the driver spends the same budget have to agree."""
        payloads = [self.folded((40, 20)), self.folded((60, 20)), self.folded((50, 20))]
        self.assertEqual([p["draws"] for p in payloads], [1, 1, 1])
        self.assertEqual(judge_draws_in(payloads), 3)

    def test_a_file_written_before_the_field_existed_reads_as_one_draw(self) -> None:
        self.assertEqual(judge_draws_in([{"items": []}]), 1)
        self.assertEqual(judge_draws_in([{"draws": None}]), 1)

    def test_the_spread_inside_one_file_survives_into_the_item_vector(self) -> None:
        """The half that made the count wrong in the direction that publishes.

        ``aggregate_draws`` leaves the per-draw list on each item and the mean in
        ``score``. Reading ``score`` alone gave a one-element ``ScoredItem.scores``, so
        ``spread`` was 0 over a first item the judge had actually moved 20 points on —
        and ``pair_resolution`` then reported ±0.00, which reads as a judge that
        resolved every item exactly, off the one file where the judge's noise *was*
        observed.
        """
        payload = self.folded((40, 20), (60, 20), (50, 20))
        scored = items_from_score_payloads([payload])
        self.assertEqual(scored[0].scores, (40, 60, 50))
        self.assertEqual(scored[0].spread, 20)
        self.assertEqual(scored[1].spread, 0)

    def test_a_replicated_arm_in_one_file_can_state_its_resolution(self) -> None:
        """End to end: one file of three draws is a pair with a measured band."""
        payload = self.folded((40, 20), (60, 20), (50, 20))
        scored = items_from_score_payloads([payload])
        both = ArmEvidence(
            task_id="Energy_001",
            arm="621566b",
            run_id="r",
            workspace="/ws",
            env=env(judge_replicates=judge_draws_in([payload])),
            items=scored,
            published_total=float(payload["total_score"]),
            replicates_requested=3,
            checklist_items_expected=len(scored),
            facts=dict(GOOD_FACTS),
        )
        self.assertEqual(both.replicates, 3)
        self.assertTrue(resolution_is_measured(both, both))
        self.assertAlmostEqual(pair_resolution(both, both), 0.5 * 20, places=9)


class RunStatusIsVisibleTests(unittest.TestCase):
    """A truncated deliverable is a different object from a finished one.

    ``run_status: cancelled`` is what the manifest records when a stage burned its
    attempts, the auto-skip budget ran out, and the next failure landed at the stage
    that writes the deliverable. Two of the three finished runs of the live stage-graph
    trial ended that way and the report said so nowhere: a reader had to open
    ``runs/<task>.<arm>.a1.json``.
    """

    def report(self, *evidences, **kwargs) -> str:
        return format_rcb_trial_report(trial(*evidences, **kwargs))

    def cut(self, **kwargs):
        return arm(facts={"run_status": "cancelled"}, **kwargs)

    def test_a_cancelled_run_is_named_in_the_sample_table(self) -> None:
        text = self.report(self.cut(), arm(label="47f3fbf", facts={"run_status": "completed"}))
        self.assertIn("Runs scored, and how they ended", text)
        self.assertIn("1 of 2 scored runs did not end `completed`", text)
        self.assertIn("| `Energy_001` | `621566b` | **cancelled** | yes | 2 |", text)
        self.assertIn("| `Energy_001` | `47f3fbf` | completed | yes | 2 |", text)
        self.assertIn("of those 2, **2 reached the difference below** and **0 were refused**", text)

    def test_the_sample_table_sits_above_the_difference(self) -> None:
        """Same argument as the refusal ledger: the composition of a sample is not a
        footnote to the number the sample produced."""
        text = self.report(self.cut(), arm(label="47f3fbf", facts={"run_status": "completed"}))
        self.assertLess(text.index("Runs scored, and how they ended"), text.index("## The difference"))

    def test_the_truncation_is_named_beside_the_pair_delta(self) -> None:
        text = self.report(self.cut(), arm(label="47f3fbf", facts={"run_status": "completed"}))
        self.assertIn("- run status: control **cancelled**, treatment **completed**", text)
        self.assertIn("The control arm's deliverable was truncated", text)

    def test_both_arms_truncated_are_both_named(self) -> None:
        text = self.report(self.cut(), self.cut(label="47f3fbf"))
        self.assertIn("2 of 2 scored runs did not end `completed`", text)
        self.assertIn("The control and treatment arm's deliverable was truncated", text)

    def test_a_finished_pair_is_not_disclaimed(self) -> None:
        text = self.report(
            arm(facts={"run_status": "completed"}),
            arm(label="47f3fbf", facts={"run_status": "completed"}),
        )
        self.assertIn("all 2 scored runs ended `completed`", text)
        self.assertNotIn("was truncated", text)

    def test_an_unrecorded_status_is_printed_as_unrecorded_and_not_as_truncated(self) -> None:
        """Silence is not evidence of truncation, and it is not evidence of completion.

        A state file written before the driver carried the field says nothing, and
        inventing either reading from it would put a claim on runs nobody measured.
        Folding it into the clean branch is the tempting half: "all 2 scored runs ended
        `completed`" over two runs whose ending nothing observed is a fabrication with
        the report's own voice behind it.
        """
        control, treatment = arm(), arm(label="47f3fbf")
        self.assertEqual((run_status_of(control), truncated(control)), ("", False))
        text = self.report(control, treatment)
        self.assertIn("2 of 2 scored runs recorded no run status at all", text)
        self.assertNotIn("all 2 scored runs ended `completed`", text)
        self.assertNotIn("was truncated", text)
        self.assertIn("| <unrecorded> |", text)
        self.assertIn("- run status: control **<unrecorded>**", text)

    def test_one_silent_run_beside_one_clean_one_is_not_reported_as_two_clean(self) -> None:
        """The mixed case, which the two-branch version got wrong in the same direction."""
        text = self.report(arm(), arm(label="47f3fbf", facts={"run_status": "completed"}))
        self.assertIn("1 of 2 scored runs recorded no run status at all", text)
        self.assertNotIn("all 2 scored runs ended `completed`", text)

    def test_the_table_is_over_the_scored_runs_and_says_which_reached_the_mean(self) -> None:
        """Two populations, one table, and the difference between them printed.

        With nothing refused the two are the same set, and a test written only on this
        fixture cannot tell ``trial.scored`` from ``trial.evidence`` — which is exactly
        how the first version of this section shipped reading the wrong one.
        ``RunStatusSeesRefusedRunsTests`` below is the fixture where they differ.
        """
        result = trial(self.cut(), arm(label="47f3fbf", facts={"run_status": "completed"}))
        self.assertEqual(len(result.scored), 2)
        self.assertEqual(set(result.scored), set(result.evidence))
        self.assertEqual(result.refused_clauses_by_arm(), {})

    def test_no_admission_clause_reads_the_run_status(self) -> None:
        """It comes off the run's own manifest inside the run root, which the operator
        writes with `bypassPermissions`. A gate on it would be a gate the party it
        constrains can clear with one word."""
        for status in ("cancelled", "completed", "failed", "halted", ""):
            with self.subTest(status=status):
                self.assertEqual(
                    admit_arm(arm(facts={"run_status": status})),
                    admit_arm(arm()),
                )


class RunStatusSeesRefusedRunsTests(unittest.TestCase):
    """The live stage-graph trial's own three scored runs, as a fixture.

    Read off ``/rmeng_data/robtang/rcb-trial-graph`` — ``runs/*.json`` for the statuses
    and stage lists, each workspace's ``_meta.json`` for ``pipeline_completed``:

    ==============  ========  ===========  ====================  ======
    task            arm       run_status   pipeline_completed    stages
    ==============  ========  ===========  ====================  ======
    Astronomy_000   a13cd7d   completed    true                  7
    Astronomy_000   a3bcae6   cancelled    false                 4
    Chemistry_000   a13cd7d   cancelled    false                 6
    ==============  ========  ===========  ====================  ======

    Both truncated runs are refused by ``pipeline_completed``, so ``trial.evidence``
    holds one of the three. That is not an accident of this sample and it is why the
    section cannot be computed over the admitted runs: a run that spends its auto-skip
    budget is routed to the writing stage rather than reaching it, and that is the same
    event that leaves ``pipeline_completed`` false. Reading ``evidence`` here printed
    "all 1 scored runs ended ``completed``" — a positive clean-sample claim, in the
    report's own voice, over a sample two thirds of which was cut off.
    """

    CONTROL = "a3bcae6"
    TREATMENT = "a13cd7d"
    HEADING = "## Runs scored, and how they ended"

    def section(self, result) -> str:
        """Just the sample-composition section, so "absent from it" is assertable."""
        text = format_rcb_trial_report(result)
        self.assertIn(self.HEADING, text)
        return text.split(self.HEADING, 1)[1].split("\n## ", 1)[0]

    def live(self):
        """The three runs above, with everything not under test held at the good value."""
        return collect_rcb_pairs(
            [
                arm(
                    task="Astronomy_000",
                    label=self.TREATMENT,
                    facts={"run_status": "completed"},
                    stages=tuple(f"{n:02d}_s" for n in range(1, 8)),
                ),
                arm(
                    task="Astronomy_000",
                    label=self.CONTROL,
                    facts={"run_status": "cancelled", "meta_pipeline_completed": False},
                    stages=tuple(f"{n:02d}_s" for n in range(1, 5)),
                ),
                arm(
                    task="Chemistry_000",
                    label=self.TREATMENT,
                    facts={"run_status": "cancelled", "meta_pipeline_completed": False},
                    stages=tuple(f"{n:02d}_s" for n in range(1, 7)),
                ),
            ],
            capability="stage_graph",
            control_arm=self.CONTROL,
            treatment_arm=self.TREATMENT,
            planned_pairs=6,
        )

    def test_the_two_populations_really_do_differ_on_this_fixture(self) -> None:
        """Without this the rest of the class would pass on either collection."""
        result = self.live()
        self.assertEqual(len(result.scored), 3)
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(
            sorted(result.refused_clauses_by_arm()),
            [("Astronomy_000", self.CONTROL), ("Chemistry_000", self.TREATMENT)],
        )
        for clauses in result.refused_clauses_by_arm().values():
            self.assertEqual(clauses, ("pipeline_completed",))

    def test_the_headline_counts_every_scored_run_not_only_the_admitted_one(self) -> None:
        text = format_rcb_trial_report(self.live())
        self.assertIn("**2 of 3 scored runs did not end `completed`.**", text)
        self.assertNotIn("all 1 scored runs ended `completed`", text)
        self.assertNotIn("scored runs ended `completed`", text)

    def test_both_truncated_runs_are_in_the_table_with_their_status(self) -> None:
        text = format_rcb_trial_report(self.live())
        self.assertIn(
            "| `Astronomy_000` | `a3bcae6` | **cancelled** | no — refused "
            "(`pipeline_completed`) | 4 |",
            text,
        )
        self.assertIn(
            "| `Chemistry_000` | `a13cd7d` | **cancelled** | no — refused "
            "(`pipeline_completed`) | 6 |",
            text,
        )
        self.assertIn("| `Astronomy_000` | `a13cd7d` | completed | yes | 7 |", text)

    def test_the_split_between_the_sample_and_the_mean_is_stated(self) -> None:
        text = format_rcb_trial_report(self.live())
        self.assertIn(
            "of those 3, **1 reached the difference below** and **2 were refused**", text
        )

    def test_the_word_a_reader_would_search_for_is_in_the_report(self) -> None:
        """The reviewer's own test: replaying these artifacts produced a report with no
        occurrence of `cancelled` or `truncated` anywhere in it."""
        text = format_rcb_trial_report(self.live())
        self.assertGreaterEqual(text.count("cancelled"), 2)
        self.assertIn("truncated", text)

    def test_a_sample_that_is_entirely_refused_still_discloses(self) -> None:
        """Zero admitted is the reading the old code could not make at all: with
        ``evidence`` empty it printed "no run was scored" over runs that were scored."""
        text = format_rcb_trial_report(
            collect_rcb_pairs(
                [
                    arm(
                        task="Astronomy_000",
                        label=self.CONTROL,
                        facts={"run_status": "cancelled", "meta_pipeline_completed": False},
                    )
                ],
                capability="stage_graph",
                control_arm=self.CONTROL,
                treatment_arm=self.TREATMENT,
                planned_pairs=6,
            )
        )
        self.assertNotIn("no run was scored", text)
        self.assertIn("**1 of 1 scored runs did not end `completed`.**", text)
        self.assertIn("**0 reached the difference below** and **1 were refused**", text)

    def test_a_driver_refusal_is_not_counted_as_a_scored_run(self) -> None:
        """It never became evidence and has no score, so it belongs to the ledger above.

        Chemistry_000's control arm was still `launched` when this trial was read, and a
        run in flight or dead before the judge must not inflate the denominator of a
        sentence about what the judge saw.
        """
        result = collect_rcb_pairs(
            [arm(task="Astronomy_000", label=self.TREATMENT, facts={"run_status": "completed"})],
            capability="stage_graph",
            control_arm=self.CONTROL,
            treatment_arm=self.TREATMENT,
            planned_pairs=6,
            driver_refusals=(Refusal("Chemistry_000", self.CONTROL, ("driver:quota",)),),
        )
        self.assertEqual(len(result.scored), 1)
        section = self.section(result)
        self.assertIn("all 1 scored runs ended `completed`.", section)
        self.assertIn(
            "of those 1, **1 reached the difference below** and **0 were refused**", section
        )
        self.assertNotIn("| `Chemistry_000` |", section)
        # It is in the ledger above instead, which is the half of the record it belongs to.
        self.assertIn(
            "`Chemistry_000` / `a3bcae6`: driver:quota", format_rcb_trial_report(result)
        )


if __name__ == "__main__":
    unittest.main()


class LeftoverDraftTest(unittest.TestCase):
    """Counting is not naming.

    ``score.py`` falls back to the first ``*.md`` an unsorted glob yields when
    ``report/report.md`` is absent. A workspace holding only ``draft.md`` therefore
    satisfies "exactly one markdown file" *and* gets its draft scored as the
    deliverable, with nothing on the record saying which file was read. The clause has
    to test both halves or it admits exactly the run it was written to catch.
    """

    def test_a_lone_leftover_draft_is_refused(self) -> None:
        ok, failed = admit_arm(arm(facts={"report_md_count": 1, "report_md_present": False}))
        self.assertFalse(ok)
        self.assertEqual(failed, ["single_report_md"])

    def test_report_md_beside_a_second_markdown_file_is_still_refused(self) -> None:
        ok, failed = admit_arm(arm(facts={"report_md_count": 2, "report_md_present": True}))
        self.assertFalse(ok)
        self.assertEqual(failed, ["single_report_md"])

    def test_a_missing_presence_fact_refuses_rather_than_passing(self) -> None:
        # An older state file predates the field. Absent must not read as present: the
        # cheapest way to satisfy a check over declared keys is to not declare the key.
        ok, failed = admit_arm(arm(facts={"report_md_present": None}))
        self.assertFalse(ok)
        self.assertEqual(failed, ["single_report_md"])

    def test_the_healthy_case_still_passes(self) -> None:
        ok, failed = admit_arm(arm())
        self.assertTrue(ok, failed)
