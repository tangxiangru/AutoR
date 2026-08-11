"""The figure plan: a commitment made before the results, or nothing at all.

Two properties carry most of these tests, and both are about what the gate
*cannot* be turned into. The refusal set has exactly two count rules — "no
figures" and "more than the ceiling" — so a plan with one, two or three slots
passes untouched; ``MAX_REPORT_FIGURES`` is a ceiling, and a gate that nudged
toward it would have made it a quota. And every slot has to carry a claim no
other slot carries, which is the only rule here that pushes the count down.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.report_plan import (
    MAX_HEADLINE_NUMBERS,
    MIN_BRANCH_CHARS,
    MIN_DROP_REASON_CHARS,
    MIN_SHOWS_CHARS,
    format_report_plan_for_prompt,
    load_report_plan,
    report_plan_digest,
    stamp_report_plan,
    validate_report_plan,
    validate_report_plan_coverage,
    validate_report_plan_sources,
)
from src.utils import (
    MAX_REPORT_FIGURES,
    STAGES,
    build_run_paths,
    ensure_run_layout,
    validate_stage_artifacts,
    write_text,
)
from tests.prereg_support import write_hypothesis_manifest, write_report_plan


STAGE_02 = next(stage for stage in STAGES if stage.number == 2)
STAGE_03 = next(stage for stage in STAGES if stage.number == 3)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
STAGE_07 = next(stage for stage in STAGES if stage.number == 7)


def figure(slot: int, **overrides) -> dict:
    entry = {
        "slot": slot,
        "filename": f"figure_{slot}.png",
        "supports": [f"exploratory:question-{slot}"],
        "shows": (
            "Accuracy (%) against context length (tokens) for the method and the "
            "long-context baseline, five seeds, band = stderr."
        ),
        "if_supported": "the method's curve stays above the baseline's beyond 8k tokens",
        "if_refuted": "the two curves overlap within their bands at every length",
        "source_artifact": "results/accuracy_by_length.json",
        "dropped_because": "",
    }
    entry.update(overrides)
    return entry


class ReportPlanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def write_plan(self, figures=None, headline_numbers=None, **extra) -> None:
        payload = {
            "figures": figures if figures is not None else [figure(1)],
            "headline_numbers": headline_numbers
            if headline_numbers is not None
            else [
                {
                    "quantity": "held-out accuracy, method vs baseline",
                    "unit": "percentage points",
                    "source_artifact": "results/accuracy_by_length.json",
                }
            ],
            # Every plan answers the task description. Tests about figure counts
            # override `figures`, not this, so the default has to cover slot 1 —
            # which every default figure set includes.
            "task_outputs": [
                {
                    "stated": "the accuracy comparison the task asks for",
                    "covered_by": "figure:1",
                    "why_not": "",
                }
            ],
        }
        payload.update(extra)
        write_text(self.paths.report_plan, json.dumps(payload))

    def problems(self, **kwargs) -> list[str]:
        return validate_report_plan(self.paths, kwargs.pop("output_format", "markdown"))


class ValidPlanTest(ReportPlanTestCase):
    def test_a_complete_plan_passes(self) -> None:
        self.write_plan()
        self.assertEqual(self.problems(), [])

    def test_a_missing_plan_names_the_path_and_what_it_must_contain(self) -> None:
        problems = self.problems()
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("workspace/notes/report_plan.json", problems[0])
        for expected in ("filename", "claim", "headline_numbers"):
            self.assertIn(expected, problems[0])

    def test_the_plan_lives_beside_the_protocol_and_not_under_data(self) -> None:
        """`.json` under data/ would satisfy the Stage 03 data gate all by itself."""
        self.assertEqual(self.paths.report_plan.parent, self.paths.notes_dir)
        self.assertEqual(self.paths.report_plan.name, "report_plan.json")

    def test_a_plan_that_is_not_an_object_loads_as_absent(self) -> None:
        write_text(self.paths.report_plan, "[]")
        self.assertIsNone(load_report_plan(self.paths))

    def test_malformed_json_does_not_crash_the_gate(self) -> None:
        write_text(self.paths.report_plan, "{not json")
        problems = self.problems()
        self.assertTrue(any("report_plan.json" in problem for problem in problems), problems)


class FigureCountTest(ReportPlanTestCase):
    def test_zero_figures_is_refused(self) -> None:
        self.write_plan(figures=[])
        self.assertTrue(any("declares no figures" in p for p in self.problems()))

    def test_one_two_and_three_figure_plans_are_accepted_with_no_complaint(self) -> None:
        """The explicit no-floor test. The ceiling must never read as a target."""
        for count in (1, 2, 3):
            with self.subTest(figures=count):
                self.write_plan(figures=[figure(index) for index in range(1, count + 1)])
                self.assertEqual(self.problems(), [])

    def test_the_ceiling_fires_one_figure_above_the_cap(self) -> None:
        self.write_plan(figures=[figure(i) for i in range(1, MAX_REPORT_FIGURES + 2)])
        problems = self.problems()
        self.assertTrue(any("ceiling, not a" in p for p in problems), problems)

    def test_the_ceiling_does_not_fire_at_the_cap(self) -> None:
        self.write_plan(figures=[figure(i) for i in range(1, MAX_REPORT_FIGURES + 1)])
        self.assertEqual(self.problems(), [])

    def test_no_refusal_ever_asks_for_more_figures(self) -> None:
        """A message that says 'add another figure' is a quota wearing a gate's clothes."""
        cases = [
            [],
            [figure(1)],
            [figure(1), figure(2)],
            [figure(i) for i in range(1, MAX_REPORT_FIGURES + 2)],
        ]
        for figures in cases:
            with self.subTest(count=len(figures)):
                self.write_plan(figures=figures)
                for problem in self.problems():
                    lowered = problem.lower()
                    self.assertNotIn("at least two", lowered)
                    self.assertNotIn("at least three", lowered)
                    self.assertNotIn("more figures", lowered)

    def test_the_latex_branch_has_no_figure_ceiling(self) -> None:
        """Five would damage a venue paper that legitimately carries ten."""
        self.write_plan(
            figures=[figure(index) for index in range(1, MAX_REPORT_FIGURES + 4)]
        )
        self.assertEqual(self.problems(output_format="latex"), [])


class SlotTest(ReportPlanTestCase):
    def test_a_duplicate_slot_is_refused(self) -> None:
        self.write_plan(figures=[figure(1), figure(1, filename="second.png",
                                                 supports=["exploratory:second-question"])])
        self.assertTrue(any("contiguous from 1" in p for p in self.problems()))

    def test_a_gap_in_the_slots_is_refused(self) -> None:
        self.write_plan(figures=[figure(1), figure(3)])
        self.assertTrue(any("contiguous from 1" in p for p in self.problems()))

    def test_a_non_integer_slot_is_refused_rather_than_crashing(self) -> None:
        self.write_plan(figures=[figure("first")])
        self.assertTrue(any("contiguous from 1" in p for p in self.problems()))


class FilenameTest(ReportPlanTestCase):
    def test_a_duplicate_filename_is_refused(self) -> None:
        self.write_plan(
            figures=[
                figure(1, filename="one.png"),
                figure(2, filename="one.png", supports=["exploratory:second-question"]),
            ]
        )
        self.assertTrue(any("another slot also" in p for p in self.problems()))

    def test_a_missing_filename_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, filename="")])
        self.assertTrue(any("declares no filename" in p for p in self.problems()))

    def test_a_subdirectory_figure_cannot_be_planned(self) -> None:
        """`report/images/panels/a.png` passes every current export gate and is never seen."""
        self.write_plan(figures=[figure(1, filename="panels/a.png")])
        self.assertTrue(any("not a bare filename" in p for p in self.problems()))

    def test_a_parent_traversal_filename_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, filename="../a.png")])
        self.assertTrue(any("not a bare filename" in p for p in self.problems()))

    def test_a_jpg_cannot_be_planned_for_a_markdown_report(self) -> None:
        """The other live export defect: a .jpg reaches the reader as nothing."""
        self.write_plan(figures=[figure(1, filename="main.jpg")])
        problems = self.problems()
        self.assertTrue(any(".png" in p for p in problems), problems)

    def test_a_pdf_figure_is_allowed_for_a_latex_run(self) -> None:
        self.write_plan(figures=[figure(1, filename="main.pdf")])
        self.assertEqual(self.problems(output_format="latex"), [])


class SupportsTest(ReportPlanTestCase):
    def test_a_figure_with_no_claim_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, supports=[])])
        self.assertTrue(any("names no claim" in p for p in self.problems()))

    def test_two_figures_with_identical_supports_are_refused(self) -> None:
        """Five views of one result is one figure and four wasted slots."""
        self.write_plan(
            figures=[
                figure(1, supports=["exploratory:one-question"]),
                figure(2, filename="two.png", supports=["exploratory:one-question"]),
            ]
        )
        problems = self.problems()
        self.assertTrue(any("slot spent twice" in p for p in problems), problems)

    def test_a_slot_that_repeats_its_own_claim_is_not_a_second_slot(self) -> None:
        """The distinctness rule counts slots per claim, not mentions of a claim.

        ``["H1", "H1"]`` in one slot is one question written twice. Counting
        mentions made the only slot carrying H1 look like the second of two and
        refused it, with a message blaming a slot that does not exist — a
        refusal the run cannot act on because the thing it names is not there.
        """
        self.write_plan(figures=[figure(1, supports=["exploratory:one-question"] * 2)])
        self.assertEqual(self.problems(), [])

    def test_the_repeat_does_not_hide_a_genuine_duplicate(self) -> None:
        """The control: deduplicating within a slot must not disarm the rule."""
        self.write_plan(
            figures=[
                figure(1, supports=["exploratory:one-question"] * 2),
                figure(2, filename="two.png", supports=["exploratory:one-question"]),
            ]
        )
        self.assertTrue(any("slot spent twice" in p for p in self.problems()))

    def test_a_composite_that_adds_one_new_claim_is_not_the_slot_refused(self) -> None:
        """The composite carries something of its own; the slot it subsumes does not."""
        self.write_plan(
            figures=[
                figure(1, supports=["exploratory:one-question"]),
                figure(
                    2,
                    filename="two.png",
                    supports=["exploratory:one-question", "exploratory:second-question"],
                ),
            ]
        )
        problems = [p for p in self.problems() if "slot spent twice" in p]
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("slot 1", problems[0])

    def test_overlap_is_allowed_while_every_slot_carries_something_of_its_own(self) -> None:
        self.write_plan(
            figures=[
                figure(1, supports=["exploratory:one-question", "exploratory:shared-question"]),
                figure(
                    2,
                    filename="two.png",
                    supports=["exploratory:shared-question", "exploratory:second-question"],
                ),
            ]
        )
        self.assertEqual(self.problems(), [])

    def test_an_exploratory_slug_must_name_something(self) -> None:
        self.write_plan(figures=[figure(1, supports=["exploratory:x"])])
        self.assertTrue(any("slug" in p for p in self.problems()))

    def test_an_id_the_hypothesis_manifest_does_not_declare_is_refused(self) -> None:
        write_hypothesis_manifest(self.paths)
        self.write_plan(figures=[figure(1, supports=["H7"])])
        problems = self.problems()
        self.assertTrue(any("hypothesis_manifest.json" in p for p in problems), problems)

    def test_a_declared_hypothesis_id_is_accepted(self) -> None:
        write_hypothesis_manifest(self.paths)
        self.write_plan(figures=[figure(1, supports=["H1"])])
        self.assertEqual(self.problems(), [])

    def test_without_a_manifest_the_membership_check_degrades_to_non_empty(self) -> None:
        """A `--project-root` run has no Stage 02 manifest and cannot be asked for one here."""
        self.write_plan(figures=[figure(1, supports=["H7"])])
        self.assertEqual(self.problems(), [])


class SentenceTest(ReportPlanTestCase):
    def test_a_short_shows_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, shows="a plot")])
        self.assertTrue(any(str(MIN_SHOWS_CHARS) in p for p in self.problems()))

    def test_the_shows_floor_is_not_a_units_regex(self) -> None:
        """A guard that reduced the value to a shape would only measure shape."""
        self.write_plan(
            figures=[
                figure(
                    1,
                    shows=(
                        "The relationship between the two conditions across the whole "
                        "evaluation, drawn as a paired comparison."
                    ),
                )
            ]
        )
        self.assertEqual(self.problems(), [])

    def test_a_missing_branch_sentence_is_refused(self) -> None:
        for branch in ("if_supported", "if_refuted"):
            with self.subTest(branch=branch):
                self.write_plan(figures=[figure(1, **{branch: ""})])
                problems = self.problems()
                self.assertTrue(any(branch in p for p in problems), problems)

    def test_a_short_branch_sentence_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, if_refuted="no")])
        self.assertTrue(any(str(MIN_BRANCH_CHARS) in p for p in self.problems()))

    def test_identical_branches_are_refused(self) -> None:
        sentence = "the two curves are drawn against each other"
        self.write_plan(figures=[figure(1, if_supported=sentence, if_refuted=sentence)])
        self.assertTrue(any("decoration" in p for p in self.problems()))

    def test_branches_that_differ_only_in_whitespace_and_case_are_refused(self) -> None:
        self.write_plan(
            figures=[
                figure(
                    1,
                    if_supported="The two curves separate beyond 8k tokens",
                    if_refuted="the  two curves   SEPARATE beyond 8k tokens ",
                )
            ]
        )
        self.assertTrue(any("decoration" in p for p in self.problems()))

    def test_inserting_not_defeats_the_branch_guard_and_that_is_the_documented_bargain(self) -> None:
        """Recorded as a property so nobody later mistakes this guard for proof."""
        self.write_plan(
            figures=[
                figure(
                    1,
                    if_supported="the two curves separate beyond 8k tokens",
                    if_refuted="the two curves do not separate beyond 8k tokens",
                )
            ]
        )
        self.assertEqual(self.problems(), [])
        module = (Path(__file__).resolve().parent.parent / "src" / "report_plan.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("trivially defeated", module)


class SourceArtifactTest(ReportPlanTestCase):
    def test_a_missing_source_artifact_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, source_artifact="")])
        self.assertTrue(any("names no source_artifact" in p for p in self.problems()))

    def test_a_figure_drawn_from_a_note_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, source_artifact="notes/design.json")])
        self.assertTrue(any("never from a note" in p for p in self.problems()))

    def test_an_absolute_source_artifact_is_refused(self) -> None:
        self.write_plan(figures=[figure(1, source_artifact="/tmp/results/x.json")])
        self.assertTrue(any("workspace-relative" in p for p in self.problems()))

    def test_a_bare_directory_is_not_a_source_artifact(self) -> None:
        self.write_plan(figures=[figure(1, source_artifact="results")])
        self.assertTrue(any("workspace-relative" in p for p in self.problems()))

    def test_the_benchmark_outputs_root_is_accepted(self) -> None:
        self.write_plan(figures=[figure(1, source_artifact="outputs/metrics.json")])
        self.assertEqual(self.problems(), [])


class HeadlineNumberTest(ReportPlanTestCase):
    def test_zero_headline_numbers_is_refused(self) -> None:
        self.write_plan(headline_numbers=[])
        self.assertTrue(any("no headline_numbers" in p for p in self.problems()))

    def test_more_than_the_cap_is_refused(self) -> None:
        self.write_plan(
            headline_numbers=[
                {
                    "quantity": f"quantity {index}",
                    "unit": "count",
                    "source_artifact": "results/metrics.json",
                }
                for index in range(MAX_HEADLINE_NUMBERS + 1)
            ]
        )
        self.assertTrue(any("at most" in p for p in self.problems()))

    def test_each_field_is_required(self) -> None:
        base = {
            "quantity": "held-out accuracy",
            "unit": "percentage points",
            "source_artifact": "results/metrics.json",
        }
        for missing in base:
            with self.subTest(field=missing):
                self.write_plan(headline_numbers=[{**base, missing: ""}])
                self.assertTrue(self.problems(), f"{missing} was not required")

    def test_dimensionless_is_a_unit(self) -> None:
        self.write_plan(
            headline_numbers=[
                {
                    "quantity": "effect size",
                    "unit": "dimensionless",
                    "source_artifact": "results/metrics.json",
                }
            ]
        )
        self.assertEqual(self.problems(), [])


class SourceExistenceTest(ReportPlanTestCase):
    def test_a_source_that_does_not_exist_is_refused_from_stage_06(self) -> None:
        self.write_plan()
        problems = validate_report_plan_sources(self.paths)
        self.assertTrue(any("does not exist" in p for p in problems), problems)
        self.assertTrue(any("dropped_because" in p for p in problems), problems)

    def test_a_source_that_exists_passes(self) -> None:
        self.write_plan()
        write_text(self.paths.results_dir / "accuracy_by_length.json", "{}")
        self.assertEqual(validate_report_plan_sources(self.paths), [])

    def test_a_dropped_slot_is_not_asked_for_its_source(self) -> None:
        # The headline number's own source is written, so the only thing this
        # assertion can be failing on is the dropped slot.
        write_text(self.paths.results_dir / "accuracy_by_length.json", "{}")
        self.write_plan(
            figures=[
                figure(
                    1,
                    dropped_because=(
                        "the length sweep never finished, so the claim it carried is "
                        "reported as untested"
                    ),
                )
            ]
        )
        self.assertEqual(validate_report_plan_sources(self.paths), [])

    def test_a_headline_number_is_held_to_the_same_rule_as_a_figure(self) -> None:
        """The one gate that ever resolves ``headline_numbers[].source_artifact``.

        Shape is checked at Stage 03 and nowhere else, so without this the field
        is the cheapest thing in the plan: a number the report leads with could
        name a file nothing ever wrote and no stage would notice. There is no
        ``dropped_because`` escape here — a headline number has no slot to
        abandon, so the move is to amend the plan.
        """
        write_text(self.paths.results_dir / "accuracy_by_length.json", "{}")
        self.write_plan(
            headline_numbers=[
                {
                    "quantity": "held-out accuracy, method vs baseline",
                    "unit": "percentage points",
                    "source_artifact": "results/never_written.json",
                }
            ]
        )
        problems = validate_report_plan_sources(self.paths)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("headline number 1", problems[0])
        self.assertIn("results/never_written.json", problems[0])
        self.assertNotIn("dropped_because", problems[0])

    def test_a_configured_artifact_root_satisfies_the_check(self) -> None:
        """A benchmark run writes results outside the run tree; the gate follows it."""
        benchmark = Path(self._tmp.name) / "benchmark"
        (benchmark / "outputs").mkdir(parents=True)
        (benchmark / "outputs" / "accuracy_by_length.json").write_text("{}", encoding="utf-8")
        self.write_plan(figures=[figure(1, source_artifact="outputs/accuracy_by_length.json")])
        self.assertEqual(
            validate_report_plan_sources(self.paths, [benchmark / "outputs"]), []
        )

    def test_a_shape_violation_is_not_reported_twice(self) -> None:
        """The Stage 03 gate owns shape; a second copy would make one defect look like two."""
        write_text(self.paths.results_dir / "accuracy_by_length.json", "{}")
        self.write_plan(figures=[figure(1, source_artifact="notes/design.json")])
        self.assertEqual(validate_report_plan_sources(self.paths), [])


class CoverageTest(ReportPlanTestCase):
    def publish(self, filename: str, *, reference: bool = True) -> None:
        self.paths.report_images_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.report_images_dir / filename).write_bytes(b"png")
        body = "# Report\n\n"
        if reference:
            body += f"![A figure.](images/{filename})\n"
        write_text(self.paths.report_file, body)

    def test_a_published_and_referenced_figure_is_covered(self) -> None:
        self.write_plan()
        self.publish("figure_1.png")
        self.assertEqual(validate_report_plan_coverage(self.paths), [])

    def test_a_silently_missing_figure_is_refused(self) -> None:
        self.write_plan()
        write_text(self.paths.report_file, "# Report\n")
        problems = validate_report_plan_coverage(self.paths)
        self.assertTrue(any("neither published nor dropped" in p for p in problems), problems)
        self.assertTrue(any("figure_1.png" in p for p in problems), problems)
        self.assertTrue(any("exploratory:question-1" in p for p in problems), problems)

    def test_a_figure_on_disk_that_the_report_never_references_is_refused(self) -> None:
        """The judge is shown the file; the reader is shown the report. Both, or neither."""
        self.write_plan()
        self.publish("figure_1.png", reference=False)
        problems = validate_report_plan_coverage(self.paths)
        self.assertTrue(any("neither published nor dropped" in p for p in problems), problems)

    def test_a_dropped_slot_passes_coverage(self) -> None:
        self.write_plan(
            figures=[
                figure(1),
                figure(
                    2,
                    filename="figure_2.png",
                    supports=["exploratory:second-question"],
                    dropped_because=(
                        "the second sweep did not converge in the time left; the claim it "
                        "carried is reported as untested"
                    ),
                ),
            ]
        )
        self.publish("figure_1.png")
        self.assertEqual(validate_report_plan_coverage(self.paths), [])

    def test_a_one_word_drop_reason_does_not_account_for_a_slot(self) -> None:
        self.write_plan(figures=[figure(1, dropped_because="skipped")])
        write_text(self.paths.report_file, "# Report\n")
        problems = validate_report_plan_coverage(self.paths)
        self.assertTrue(any("neither published nor dropped" in p for p in problems), problems)
        self.assertTrue(
            any(str(MIN_DROP_REASON_CHARS) in p for p in problems),
            "the refusal has to say how long a drop reason has to be",
        )

    def test_dropping_every_slot_is_refused(self) -> None:
        self.write_plan(
            figures=[
                figure(
                    1,
                    dropped_because=(
                        "nothing finished in time and the report carries no figure at all"
                    ),
                )
            ]
        )
        problems = validate_report_plan_coverage(self.paths)
        self.assertTrue(any("drops every planned figure" in p for p in problems), problems)

    def test_a_configured_figures_root_counts_as_published(self) -> None:
        benchmark_images = Path(self._tmp.name) / "benchmark" / "report" / "images"
        benchmark_images.mkdir(parents=True)
        (benchmark_images / "figure_1.png").write_bytes(b"png")
        self.write_plan()
        write_text(self.paths.report_file, "# Report\n\n![A figure.](images/figure_1.png)\n")
        self.assertEqual(validate_report_plan_coverage(self.paths, [benchmark_images]), [])

    def test_no_plan_means_no_coverage_refusal(self) -> None:
        self.assertEqual(validate_report_plan_coverage(self.paths), [])


class DigestAndAmendmentTest(ReportPlanTestCase):
    def test_the_digest_ignores_the_stamp_fields(self) -> None:
        self.write_plan()
        first = load_report_plan(self.paths)
        assert first is not None
        self.write_plan(declared_at="2026-01-01T00:00:00", amendments=[{"reason": "x"}])
        second = load_report_plan(self.paths)
        assert second is not None
        self.assertEqual(report_plan_digest(first), report_plan_digest(second))

    def test_the_digest_moves_when_a_committed_field_moves(self) -> None:
        self.write_plan()
        first = load_report_plan(self.paths)
        assert first is not None
        self.write_plan(figures=[figure(1, filename="renamed.png")])
        second = load_report_plan(self.paths)
        assert second is not None
        self.assertNotEqual(report_plan_digest(first), report_plan_digest(second))

    def test_stamping_dates_the_plan_without_recording_an_amendment(self) -> None:
        self.write_plan()
        stamped = stamp_report_plan(self.paths)
        assert stamped is not None
        self.assertTrue(stamped.declared_at)
        self.assertEqual(stamped.amendments, [])
        self.assertEqual(stamped.digest, report_plan_digest(stamped))

    def test_stamping_is_idempotent_on_unchanged_content(self) -> None:
        """A round that legitimately left the plan alone must not fake an amendment."""
        self.write_plan()
        first = stamp_report_plan(self.paths)
        assert first is not None
        before = self.paths.report_plan.read_text(encoding="utf-8")
        again = stamp_report_plan(self.paths, "second round")
        assert again is not None
        self.assertEqual(again.amendments, [])
        self.assertEqual(self.paths.report_plan.read_text(encoding="utf-8"), before)

    def test_a_changed_plan_appends_exactly_one_amendment(self) -> None:
        self.write_plan()
        stamp_report_plan(self.paths)
        payload = json.loads(self.paths.report_plan.read_text(encoding="utf-8"))
        first_digest = payload["digest"]
        payload["figures"][0]["filename"] = "renamed.png"
        write_text(self.paths.report_plan, json.dumps(payload))

        amended = stamp_report_plan(self.paths, "round 2: the length sweep replaced the ablation")
        assert amended is not None
        self.assertEqual(len(amended.amendments), 1)
        self.assertEqual(amended.amendments[0]["previous_digest"], first_digest)
        self.assertEqual(amended.amendments[0]["new_digest"], amended.digest)
        self.assertIn("round 2", amended.amendments[0]["reason"])

    def test_dropping_a_slot_in_a_later_round_is_recorded_as_an_amendment(self) -> None:
        self.write_plan()
        stamp_report_plan(self.paths)
        payload = json.loads(self.paths.report_plan.read_text(encoding="utf-8"))
        payload["figures"][0]["dropped_because"] = (
            "the sweep never ran, and the claim it carried is reported as untested"
        )
        write_text(self.paths.report_plan, json.dumps(payload))
        amended = stamp_report_plan(self.paths, "round 2: dropped the length sweep")
        assert amended is not None
        self.assertEqual(len(amended.amendments), 1)

    def test_the_first_declaration_survives_an_amendment(self) -> None:
        self.write_plan()
        first = stamp_report_plan(self.paths)
        assert first is not None
        payload = json.loads(self.paths.report_plan.read_text(encoding="utf-8"))
        payload["figures"][0]["filename"] = "renamed.png"
        write_text(self.paths.report_plan, json.dumps(payload))
        amended = stamp_report_plan(self.paths, "moved")
        assert amended is not None
        self.assertEqual(amended.declared_at, first.declared_at)

    def test_stamping_a_plan_that_does_not_exist_does_nothing(self) -> None:
        self.assertIsNone(stamp_report_plan(self.paths))
        self.assertFalse(self.paths.report_plan.exists())

    def test_a_stamped_plan_still_passes_the_gate(self) -> None:
        self.write_plan()
        stamp_report_plan(self.paths)
        self.assertEqual(self.problems(), [])


class PromptRenderingTest(ReportPlanTestCase):
    def test_the_rendered_plan_carries_every_committed_field(self) -> None:
        self.write_plan()
        plan = load_report_plan(self.paths)
        assert plan is not None
        rendered = format_report_plan_for_prompt(plan)
        self.assertIn("figure_1.png", rendered)
        self.assertIn("exploratory:question-1", rendered)
        self.assertIn("results/accuracy_by_length.json", rendered)
        self.assertIn("held-out accuracy", rendered)

    def test_a_dropped_slot_says_so_in_the_prompt(self) -> None:
        self.write_plan(
            figures=[
                figure(
                    1,
                    dropped_because="the sweep did not finish and the claim is reported untested",
                )
            ]
        )
        plan = load_report_plan(self.paths)
        assert plan is not None
        self.assertIn("DROPPED", format_report_plan_for_prompt(plan))

    def test_an_amendment_is_visible_to_the_next_round(self) -> None:
        self.write_plan()
        stamp_report_plan(self.paths)
        payload = json.loads(self.paths.report_plan.read_text(encoding="utf-8"))
        payload["figures"][0]["filename"] = "renamed.png"
        write_text(self.paths.report_plan, json.dumps(payload))
        stamp_report_plan(self.paths, "round 2: swapped the ablation for the length sweep")
        plan = load_report_plan(self.paths)
        assert plan is not None
        self.assertIn("round 2", format_report_plan_for_prompt(plan))


class StageGateWiringTest(ReportPlanTestCase):
    def test_stage_03_refuses_a_missing_plan(self) -> None:
        """Held at the stage that writes it, not four stages later."""
        problems = validate_stage_artifacts(STAGE_03, self.paths)
        self.assertTrue(any("report_plan.json" in p for p in problems), problems)

    def test_stage_02_is_not_held_to_the_plan(self) -> None:
        problems = validate_stage_artifacts(STAGE_02, self.paths)
        self.assertFalse(any("report_plan" in p for p in problems), problems)

    def test_stage_03_accepts_a_complete_plan(self) -> None:
        write_report_plan(self.paths)
        problems = validate_stage_artifacts(STAGE_03, self.paths)
        self.assertFalse(any("report_plan" in p for p in problems), problems)

    def test_stage_06_reports_a_source_artifact_that_was_never_produced(self) -> None:
        write_report_plan(self.paths, figures=[figure(1)])
        problems = validate_stage_artifacts(STAGE_06, self.paths)
        self.assertTrue(any("does not exist" in p for p in problems), problems)

    def test_stage_07_reports_an_unpublished_planned_figure(self) -> None:
        write_report_plan(self.paths, figures=[figure(1)])
        write_text(self.paths.report_file, "# Report\n")
        problems = validate_stage_artifacts(STAGE_07, self.paths)
        self.assertTrue(any("neither published nor dropped" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()


class NoFigureFloorTest(unittest.TestCase):
    """The plan must not push a run toward more figures than its argument needs.

    Measured over the forty ResearchClawBench tasks: image criteria per task run
    {0: 3 tasks, 1: 10, 2: 9, 3: 12, 4: 3, 5: 3} — a median of two, and three
    tasks with none at all. Not one task needs more than five. So the ceiling was
    never the binding constraint; coverage is. A floor of three, or of one, makes
    those runs draw a figure that carries nothing, and a surplus figure displaces
    one that carried a claim rather than adding to it.
    """

    def test_no_prompt_asks_for_a_minimum_number_of_figures(self) -> None:
        from pathlib import Path

        prompts = Path(__file__).resolve().parent.parent / "src" / "prompts"
        offenders = []
        for path in sorted(prompts.glob("*.md")):
            text = path.read_text(encoding="utf-8").lower()
            for phrase in ("at least three figures", "at least two figures", "at least one figure"):
                if phrase in text:
                    offenders.append(f"{path.name}: {phrase}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_deliverable_contract_states_there_is_no_floor(self) -> None:
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / "src" / "information_flow.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("no floor", text)

    def test_a_plan_with_no_figures_is_allowed_when_it_says_why(self) -> None:
        plan = {
            "figures": [],
            "headline_numbers": [
                {"quantity": "upper limit on g", "unit": "GeV^-1", "source_artifact": "results/limit.json"}
            ],
            "no_figures_because": (
                "The reproduction establishes one scalar upper limit; the prose states it "
                "with its confidence interval and a figure would plot a single point."
            ),
        }
        self._write(plan)
        self.assertEqual(
            [p for p in validate_report_plan(self.paths) if "no figures" in p], []
        )

    def test_a_plan_with_no_figures_and_no_reason_is_refused(self) -> None:
        """Allowed is not the same as unremarked."""
        self._write({"figures": [], "headline_numbers": [
            {"quantity": "x", "unit": "count", "source_artifact": "results/m.json"}]})
        problems = validate_report_plan(self.paths)
        self.assertTrue(any("does not say why" in p for p in problems), problems)

    def _write(self, payload: dict) -> None:
        import json

        from src.utils import write_text

        write_text(self.paths.report_plan, json.dumps(payload))

    def setUp(self) -> None:
        import tempfile
        from pathlib import Path

        from src.utils import build_run_paths, ensure_run_layout, write_text

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")


class JudgeVisibleWindowTest(unittest.TestCase):
    """A figure's argument has to be where a figure grader reads.

    ResearchClawBench's scorer passes ``report_text[:10000]`` when grading an
    image criterion and the whole report when grading a text one
    (evaluation/score.py:138). Image criteria carry 60.6% of the weight, so
    prose arguing for a figure is worth nothing past that point — the grader
    sees the picture and none of the case for it.

    Only the highest-ranked undropped slot is held to this. Requiring every
    figure's argument inside 10k characters would refuse a long paper whose
    fifth figure is legitimately discussed late.
    """

    def setUp(self) -> None:
        import json
        import tempfile
        from pathlib import Path

        from src.utils import build_run_paths, ensure_run_layout, write_text

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(
            self.paths.report_plan,
            json.dumps(
                {
                    "figures": [
                        {
                            "slot": 1,
                            "filename": "main.png",
                            "supports": ["H1"],
                            "shows": "Accuracy against context length for the method and the baseline.",
                            "if_supported": "the method's curve stays above the baseline",
                            "if_refuted": "the two curves overlap within their bands",
                            "source_artifact": "results/acc.json",
                            "dropped_because": "",
                        }
                    ],
                    "headline_numbers": [
                        {"quantity": "accuracy", "unit": "percent", "source_artifact": "results/acc.json"}
                    ],
                }
            ),
        )
        self.paths.report_images_dir.mkdir(parents=True, exist_ok=True)
        (self.paths.report_images_dir / "main.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    def _report(self, *, reference_late: bool, long: bool = True) -> None:
        from src.report_plan import JUDGE_VISIBLE_PREFIX_CHARS
        from src.utils import write_text

        filler = "Methodology prose that occupies space without saying much. " * (
            260 if long else 2
        )
        ref = "![Main](images/main.png)"
        body = (
            f"# R\n\n## Abstract\n\nshort\n\n{filler}\n\n{ref}\n"
            if reference_late
            else f"# R\n\n## Abstract\n\n{ref}\n\n{filler}"
        )
        write_text(self.paths.report_file, body)
        if long:
            self.assertGreater(len(body), JUDGE_VISIBLE_PREFIX_CHARS)

    def _window_problems(self) -> list[str]:
        from src.report_plan import validate_report_plan_coverage

        # "characters" also appears in the not-published message ("20 characters
        # or more"), so match the window message specifically.
        return [
            p for p in validate_report_plan_coverage(self.paths) if "first references slot" in p
        ]

    def test_the_lead_figure_discussed_early_passes(self) -> None:
        self._report(reference_late=False)
        self.assertEqual(self._window_problems(), [])

    def test_the_lead_figure_discussed_only_late_is_refused(self) -> None:
        self._report(reference_late=True)
        self.assertTrue(self._window_problems())

    def test_a_short_report_is_never_held_to_the_window(self) -> None:
        """Nothing falls outside a window the report never reaches."""
        self._report(reference_late=True, long=False)
        self.assertEqual(self._window_problems(), [])

    def test_an_unpublished_figure_is_reported_as_missing_not_as_late(self) -> None:
        """The two failures are different and must not be conflated."""
        from src.report_plan import validate_report_plan_coverage
        from src.utils import write_text

        (self.paths.report_images_dir / "main.png").unlink()
        write_text(self.paths.report_file, "# R\n\nno figure here\n")
        problems = validate_report_plan_coverage(self.paths)
        self.assertTrue(any("neither published nor dropped" in p for p in problems))
        self.assertEqual(self._window_problems(), [])

    def test_the_window_matches_the_scorer(self) -> None:
        from src.report_plan import JUDGE_VISIBLE_PREFIX_CHARS

        self.assertEqual(JUDGE_VISIBLE_PREFIX_CHARS, 10_000)


class TaskOutputCoverageTest(ReportPlanTestCase):
    """The task description is the only statement of intent the run may read.

    22 of the 40 ResearchClawBench tasks carry a literal ``Outputs:`` sentence
    naming the constraints, comparisons and distributions the study should
    produce. The grading criteria themselves live with the target study, which
    the run has no access to and must never be shown — but that sentence is the
    closest legitimate proxy, and nothing was answering it item by item.
    """

    def test_a_plan_that_answers_every_stated_output_passes(self) -> None:
        self.write_plan(
            task_outputs=[
                {"stated": "parameter constraints from model fitting", "covered_by": "figure:1"},
                {"stated": "goodness-of-fit comparison", "covered_by": "number:0"},
            ]
        )
        self.assertEqual([p for p in self.problems() if "task output" in p], [])

    def test_a_plan_with_no_task_outputs_is_refused(self) -> None:
        self.write_plan(task_outputs=[])
        self.assertTrue(any("no `task_outputs`" in p for p in self.problems()))

    def test_pointing_at_a_slot_that_does_not_exist_is_refused(self) -> None:
        self.write_plan(task_outputs=[{"stated": "constraints", "covered_by": "figure:9"}])
        self.assertTrue(any("which this plan does not declare" in p for p in self.problems()))

    def test_pointing_at_a_headline_number_that_does_not_exist_is_refused(self) -> None:
        self.write_plan(task_outputs=[{"stated": "constraints", "covered_by": "number:7"}])
        self.assertTrue(any("which this plan does not declare" in p for p in self.problems()))

    def test_prose_is_a_valid_answer(self) -> None:
        """Not everything the task asks for needs a figure or a headline number."""
        self.write_plan(task_outputs=[{"stated": "a discussion of limitations", "covered_by": "prose"}])
        self.assertEqual([p for p in self.problems() if "task output" in p], [])

    def test_not_attempting_something_is_allowed_when_said(self) -> None:
        self.write_plan(
            task_outputs=[
                {
                    "stated": "posterior distributions of the EDE parameters",
                    "covered_by": "not_attempted",
                    "why_not": "the supplied data carries only best-fit values, not chains",
                }
            ]
        )
        self.assertEqual([p for p in self.problems() if "task output" in p], [])

    def test_not_attempting_something_silently_is_refused(self) -> None:
        self.write_plan(
            task_outputs=[{"stated": "posterior distributions", "covered_by": "not_attempted"}]
        )
        self.assertTrue(any("without saying why" in p for p in self.problems()))

    def test_an_unknown_coverage_kind_is_refused(self) -> None:
        self.write_plan(task_outputs=[{"stated": "constraints", "covered_by": "somehow"}])
        self.assertTrue(any("expected one of" in p for p in self.problems()))

    def test_the_gate_does_not_judge_whether_the_reading_was_right(self) -> None:
        """Structural only.

        A gate cannot know what the task description said without parsing prose,
        and one that guessed would refuse correct plans. Whether the agent read
        the description well is a review question.
        """
        self.write_plan(
            task_outputs=[{"stated": "something the task never asked for", "covered_by": "figure:1"}]
        )
        self.assertEqual([p for p in self.problems() if "task output" in p], [])


class StampCarriesEveryAuthoredFieldTest(ReportPlanTestCase):
    """The manager rewrites the file on approval; anything it forgets is lost.

    `task_outputs` and `no_figures_because` were both dropped by the stamp
    because the three `ReportPlan(...)` reconstructions inside it listed fields
    by hand. The agent wrote them, the manager silently erased them, and the
    gate then refused the stage for not having what it had just deleted.
    """

    def test_stamping_preserves_task_outputs(self) -> None:
        from src.report_plan import load_report_plan, stamp_report_plan

        self.write_plan(
            task_outputs=[{"stated": "the comparison", "covered_by": "figure:1"}]
        )
        stamp_report_plan(self.paths)
        self.assertEqual(len(load_report_plan(self.paths).task_outputs), 1)

    def test_stamping_preserves_the_no_figures_reason(self) -> None:
        from src.report_plan import load_report_plan, stamp_report_plan

        reason = "The result is one scalar limit; the prose states it with its interval."
        self.write_plan(figures=[], no_figures_because=reason,
                        task_outputs=[{"stated": "the limit", "covered_by": "number:0"}])
        stamp_report_plan(self.paths)
        self.assertEqual(load_report_plan(self.paths).no_figures_because, reason)

    def test_every_dataclass_field_survives_a_stamp(self) -> None:
        """The general form, so the next field added is covered without a new test."""
        import dataclasses

        from src.report_plan import ReportPlan, load_report_plan, stamp_report_plan

        self.write_plan(task_outputs=[{"stated": "x", "covered_by": "figure:1"}])
        before = load_report_plan(self.paths)
        stamp_report_plan(self.paths)
        after = load_report_plan(self.paths)
        # declared_at, digest and amendments are what the stamp is *for*.
        stamped = {"declared_at", "digest", "amendments"}
        for f in dataclasses.fields(ReportPlan):
            if f.name in stamped:
                continue
            with self.subTest(field=f.name):
                self.assertEqual(getattr(after, f.name), getattr(before, f.name))
