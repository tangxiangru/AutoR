"""The adversarial findings are AutoR's record, not the answering stage's.

`validate_validity_response` refuses a stage that leaves a validity finding unanswered.
It read the findings out of `workspace/reviews/validity_review_<slug>.json` — a directory
the answering stage writes, in the tree every stage prompt names, with the operator
running at `cwd=run_root` under `bypassPermissions`. Measured on a run from
`build_run_paths` with one critical finding on record:

    with the review present : 1 problem
    after `rm`              : 0
    after emptying findings : 0

The objection and the obligation to answer it disappeared together, and what was left on
disk said no reviewer had raised anything. #202 named this surface — "`workspace/reviews/`
is writable by the stage the next gate constrains" — and moved the *completion* into the
harness, leaving the findings behind.

So the pass is stamped to `runs/<id>/validity_review_stamp.json`, where
`report_plan_stamp.json` and `preregistration_stamp.json` already live for the same
reason. `load_findings` reads the stamp, so every reader — the gate, the prompt that
lists the objections, fake mode's answerer — counts AutoR's population; the gate refuses
a workspace copy that disagrees; and the manager writes the record back before the next
attempt, logging what disagreed first, because the repair is what destroys the evidence
it was needed for.

The boundary is unchanged and is the one #206 wrote down: everything under `run_root` is
writable by the party the gate constrains. Deleting the stamp too still gets through to
the pre-stamp behaviour, which is why `stamped_review` returning None is documented as
the pre-stamp state rather than as a pass.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.utils import STAGES, RunPaths, build_run_paths, ensure_run_layout
from src.validity_review import (
    COMPLETED,
    CRASHED,
    RESTORE_WITNESS_HEADING,
    ValidityFinding,
    ValidityReviewer,
    load_findings,
    restore_validity_review,
    stamped_review,
    validate_validity_response,
    validity_review_path,
    validity_review_stamp_path,
    validity_review_tamper,
)

STAGE_05 = STAGES[4]
STAGE_06 = STAGES[5]

FINDINGS = [
    ValidityFinding(
        identifier="V1",
        category="confound",
        severity="critical",
        finding="Both conditions were tuned on the split that reports the headline number.",
        why_it_matters="The gap may be selection rather than the intervention.",
        what_would_settle_it="Re-tune on a development split and re-report.",
    ),
    ValidityFinding(
        identifier="V2",
        category="effect_within_noise",
        severity="major",
        finding="The reported gap is smaller than the seed-to-seed spread.",
        why_it_matters="The comparison cannot separate the effect from variance.",
        what_would_settle_it="Report the spread across at least five seeds.",
    ),
]


def _answers(*identifiers: str) -> str:
    return json.dumps(
        {
            "responses": [
                {
                    "id": identifier,
                    "status": "accepted_limitation",
                    "explanation": (
                        "The objection stands and this run cannot settle it; it is carried "
                        "into the manuscript as a limitation."
                    ),
                    "evidence": "",
                }
                for identifier in identifiers
            ]
        }
    )


class ValidityReviewStampTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths: RunPaths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        self.review = validity_review_path(self.paths, STAGE_05.slug)
        self.response = self.paths.reviews_dir / f"validity_response_{STAGE_05.slug}.json"

    def _record(self, findings=FINDINGS, *, completion: str = COMPLETED) -> None:
        reviewer = ValidityReviewer.__new__(ValidityReviewer)
        ValidityReviewer._write_review(  # noqa: SLF001 - the writer under test
            reviewer, self.paths, STAGE_05, list(findings), note="fixture", completion=completion
        )

    # -- where the record lives ------------------------------------------------

    def test_the_stamp_is_outside_the_tree_the_prompts_name(self) -> None:
        self._record()
        stamp = validity_review_stamp_path(self.paths)
        self.assertTrue(stamp.is_file())
        self.assertFalse(stamp.is_relative_to(self.paths.workspace_root))
        self.assertTrue(stamp.is_relative_to(self.paths.run_root))

    def test_the_workspace_artifact_is_still_written_unchanged(self) -> None:
        """docs/run-artifacts.md documents this file's schema; the stamp is in addition to it."""
        self._record()
        payload = json.loads(self.review.read_text(encoding="utf-8"))
        self.assertEqual(payload["reviewed_stage"], STAGE_05.slug)
        self.assertIs(payload["reviewer_failed"], False)
        self.assertEqual([item["id"] for item in payload["findings"]], ["V1", "V2"])

    def test_a_crashed_pass_is_stamped_as_crashed(self) -> None:
        self._record([], completion=CRASHED)
        self.assertEqual(stamped_review(self.paths, STAGE_05.slug)["completion"], CRASHED)
        self.assertIs(
            json.loads(self.review.read_text(encoding="utf-8"))["reviewer_failed"], True
        )

    def test_a_second_stage_does_not_overwrite_the_first(self) -> None:
        """One stamp file, one entry per reviewed stage: Stage 07 answers Stage 06's review."""
        self._record()
        reviewer = ValidityReviewer.__new__(ValidityReviewer)
        ValidityReviewer._write_review(  # noqa: SLF001
            reviewer, self.paths, STAGES[5], [FINDINGS[0]], note="", completion=COMPLETED
        )
        self.assertEqual(
            [item["id"] for item in stamped_review(self.paths, STAGE_05.slug)["findings"]],
            ["V1", "V2"],
        )
        self.assertEqual(
            [item["id"] for item in stamped_review(self.paths, STAGES[5].slug)["findings"]],
            ["V1"],
        )

    # -- the escape that used to work -----------------------------------------

    def test_deleting_the_workspace_copy_does_not_clear_the_obligation(self) -> None:
        self._record()
        self.review.unlink()
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(problems)
        self.assertEqual(len(load_findings(self.paths, STAGE_05.slug)), 2)

    def test_emptying_the_findings_list_does_not_clear_the_obligation(self) -> None:
        self._record()
        self.review.write_text(
            json.dumps({"reviewed_stage": STAGE_05.slug, "findings": []}), encoding="utf-8"
        )
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertTrue(any("dropping V1, V2" in problem for problem in problems))

    def test_swapping_in_a_softer_finding_does_not_clear_the_critical_one(self) -> None:
        """The cheapest edit is not deletion: keep one row and make it trivial."""
        self._record()
        self.review.write_text(
            json.dumps(
                {
                    "reviewed_stage": STAGE_05.slug,
                    "findings": [
                        {
                            "id": "V1",
                            "category": "overclaim",
                            "severity": "minor",
                            "finding": "A caption is missing a unit.",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        self.assertTrue(validity_review_tamper(self.paths, STAGE_05.slug))
        self.assertEqual(
            [item.finding for item in load_findings(self.paths, STAGE_05.slug)],
            [item.finding for item in FINDINGS],
        )

    def test_answering_the_stamped_findings_is_what_clears_the_gate(self) -> None:
        """The refusal has to be clearable, or it is a run that cannot finish."""
        self._record()
        self.response.write_text(_answers("V1", "V2"), encoding="utf-8")
        self.assertEqual(validate_validity_response(self.paths, STAGE_06), [])

    def test_a_deletion_is_refused_even_when_every_finding_was_answered(self) -> None:
        """Otherwise the record stays wrong and nothing in the run ever says so."""
        self._record()
        self.response.write_text(_answers("V1", "V2"), encoding="utf-8")
        self.review.unlink()
        problems = validate_validity_response(self.paths, STAGE_06)
        self.assertEqual(len(problems), 1)
        self.assertIn("is gone or unreadable", problems[0])

    def test_the_refusal_does_not_tell_the_stage_to_rewrite_the_record(self) -> None:
        """Asking the stage that erased the objections to reprint them is not a repair."""
        self._record()
        self.review.unlink()
        problem = validate_validity_response(self.paths, STAGE_06)[0]
        self.assertIn("Leave the workspace copy alone", problem)
        self.assertNotIn("rewrite", problem.lower())

    # -- the repair, and the record of it -------------------------------------

    def test_the_repair_puts_autors_record_back_and_reports_what_disagreed(self) -> None:
        self._record()
        self.review.unlink()
        disagreement = restore_validity_review(self.paths, STAGE_05.slug)
        self.assertIn("stamped copy records 2 finding(s)", disagreement)
        self.assertEqual(
            [item["id"] for item in json.loads(self.review.read_text(encoding="utf-8"))["findings"]],
            ["V1", "V2"],
        )

    def test_the_repair_converges_rather_than_firing_every_attempt(self) -> None:
        """#206 found the shape this avoids: a repair that never agrees with itself.

        The comparison is over the finding records, not the bytes — the restored file
        carries a fresh `generated_at` — so a second pass reports nothing to repair.
        """
        self._record()
        self.review.unlink()
        self.assertTrue(restore_validity_review(self.paths, STAGE_05.slug))
        self.assertEqual(restore_validity_review(self.paths, STAGE_05.slug), "")
        self.assertEqual(validity_review_tamper(self.paths, STAGE_05.slug), "")

    def test_an_untouched_run_is_never_reported_as_tampered(self) -> None:
        self._record()
        self.assertEqual(validity_review_tamper(self.paths, STAGE_05.slug), "")
        self.assertEqual(restore_validity_review(self.paths, STAGE_05.slug), "")

    def test_a_run_with_no_stamp_falls_back_to_the_workspace_copy(self) -> None:
        """The pre-stamp state, and the only one in which the workspace copy is authoritative.

        Reported as nothing to compare against rather than as a clean comparison: a run
        resumed from an AutoR that predates the stamp has no record to check against, and
        calling that a pass would be the leniency #206 removed from the preregistration.
        """
        self._record()
        validity_review_stamp_path(self.paths).unlink()
        self.review.write_text(
            json.dumps({"reviewed_stage": STAGE_05.slug, "findings": []}), encoding="utf-8"
        )
        self.assertIsNone(stamped_review(self.paths, STAGE_05.slug))
        self.assertEqual(validity_review_tamper(self.paths, STAGE_05.slug), "")
        self.assertEqual(load_findings(self.paths, STAGE_05.slug), [])

    # -- the readers other than the gate --------------------------------------

    def test_the_prompt_lists_the_stamped_findings_after_a_deletion(self) -> None:
        """The refusal is only clearable if the next prompt still shows what to answer."""
        from src.validity_review import format_findings_for_prompt

        self._record()
        self.review.unlink()
        rendered = format_findings_for_prompt(self.paths, STAGE_06)
        self.assertIn("V1", rendered)
        self.assertIn("V2", rendered)

    def test_the_stage_prompt_restores_the_record_and_the_run_log_says_so(self) -> None:
        """The manager hook, at the same point as the freeze and the report-plan stamp."""
        from src.manager import ResearchManager

        self._record()
        self.review.unlink()
        manager = ResearchManager.__new__(ResearchManager)

        class _Silent:
            def show_status(self, *args, **kwargs) -> None:
                return None

        manager.ui = _Silent()
        manager._restore_validity_review(self.paths, STAGE_06)  # noqa: SLF001
        self.assertTrue(self.review.is_file())
        log = self.paths.logs.read_text(encoding="utf-8")
        self.assertIn(RESTORE_WITNESS_HEADING, log)
        self.assertIn("stamped copy records 2 finding(s)", log)

    def test_building_the_stage_06_prompt_is_what_reaches_the_repair(self) -> None:
        """The hook, driven through `_build_stage_prompt` rather than called directly.

        #202's own review found this shape one layer up: every test asserted the state and
        none asserted it was delivered, so deleting the call left the suite green. Removing
        the line from `_build_stage_prompt` has to kill something.
        """
        from src.manager import ResearchManager
        from src.operator import ClaudeOperator
        from src.terminal_ui import TerminalUI
        from src.utils import initialize_memory, initialize_run_config, write_text

        initialize_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "Writable-surface fixture.")
        write_text(self.paths.user_input, "Writable-surface fixture.")

        self._record()
        self.review.unlink()

        ui = TerminalUI()
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=self.paths.run_root.parent,
            operator=ClaudeOperator(model="sonnet", fake_mode=True, ui=ui),
            ui=ui,
        )
        manager._build_stage_prompt(self.paths, STAGE_06, None, False)  # noqa: SLF001

        self.assertTrue(self.review.is_file())
        self.assertEqual(validity_review_tamper(self.paths, STAGE_05.slug), "")
        self.assertIn(RESTORE_WITNESS_HEADING, self.paths.logs.read_text(encoding="utf-8"))

    def test_the_run_log_says_nothing_when_the_record_is_intact(self) -> None:
        """A witness line that always fires carries no information."""
        from src.manager import ResearchManager

        self._record()
        manager = ResearchManager.__new__(ResearchManager)

        class _Silent:
            def show_status(self, *args, **kwargs) -> None:
                return None

        manager.ui = _Silent()
        manager._restore_validity_review(self.paths, STAGE_06)  # noqa: SLF001
        self.assertNotIn(
            RESTORE_WITNESS_HEADING, self.paths.logs.read_text(encoding="utf-8")
        )


if __name__ == "__main__":
    unittest.main()
