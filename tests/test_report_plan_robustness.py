"""Three ways the figure plan was satisfiable without committing to anything.

Each of these is a gate that was already there, held to the question "what is
the *cheapest* thing that gets past it".

1. A malformed plan crashed the gate instead of refusing the stage. ``"figures":
   null`` is a thing a model writes, and it left a ``TypeError`` to escape
   ``validate_stage_artifacts`` and end the run — a refusal the stage could
   never see, let alone fix.
2. A slot could be born dropped. ``dropped_because`` is skipped by the Stage 06
   source gate and by the Stage 07 coverage gate, so a plan declaring five slots
   with four already abandoned reads as a five-slot plan and owes one figure.
3. ``touch`` satisfied the source gate. The cheapest way past "the file your
   figure comes from does not exist" was to create it empty, which is the
   figure-fitted-to-nothing the gate exists to refuse.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.report_plan import (
    load_report_plan,
    stamp_report_plan,
    validate_report_plan,
    validate_report_plan_sources,
)
from src.utils import build_run_paths, ensure_run_layout, write_text


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


HEADLINE = [
    {
        "quantity": "held-out accuracy, method vs baseline",
        "unit": "percentage points",
        "source_artifact": "results/accuracy_by_length.json",
    }
]

DROP_REASON = "the length sweep never finished, so the claim it carried is reported as untested"


class ReportPlanRobustnessTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")

    def write_plan(self, figures, headline_numbers=None) -> None:
        write_text(
            self.paths.report_plan,
            json.dumps(
                {
                    "figures": figures,
                    "headline_numbers": HEADLINE if headline_numbers is None else headline_numbers,
                }
            ),
        )


class MalformedPlanTest(ReportPlanRobustnessTestCase):
    """A gate is not a place to crash: every shape comes back as a refusal."""

    def _refuses(self, raw: str) -> None:
        write_text(self.paths.report_plan, raw)
        problems = validate_report_plan(self.paths, "markdown")
        self.assertTrue(problems, f"{raw} produced no refusal")

    def test_a_null_figure_list_is_refused_rather_than_raising(self) -> None:
        self._refuses('{"figures": null, "headline_numbers": null}')

    def test_a_scalar_figure_list_is_refused_rather_than_raising(self) -> None:
        self._refuses('{"figures": 5}')

    def test_a_scalar_headline_list_is_refused_rather_than_raising(self) -> None:
        self._refuses('{"figures": [], "headline_numbers": 3}')

    def test_a_scalar_amendment_ledger_loads_as_no_amendments(self) -> None:
        write_text(
            self.paths.report_plan,
            json.dumps({"figures": [figure(1)], "headline_numbers": HEADLINE, "amendments": 7}),
        )
        plan = load_report_plan(self.paths)
        assert plan is not None
        self.assertEqual(plan.amendments, [])

    def test_the_refusal_reaches_the_stage_that_can_fix_it(self) -> None:
        """Not a traceback: text the stage prompt can carry back on the retry."""
        write_text(self.paths.report_plan, '{"figures": null}')
        problems = validate_report_plan(self.paths, "markdown")
        self.assertTrue(all(isinstance(problem, str) and problem for problem in problems))
        self.assertTrue(any("report_plan.json" in problem for problem in problems))


class DeclarationTimeDropTest(ReportPlanRobustnessTestCase):
    """``dropped_because`` is a move that only exists after the plan was declared."""

    def test_a_slot_dropped_in_the_plan_that_declares_it_is_refused(self) -> None:
        self.write_plan([figure(1), figure(2, dropped_because=DROP_REASON)])
        problems = validate_report_plan(self.paths, "markdown")
        self.assertTrue(any("dropped in the same plan that declares it" in p for p in problems))

    def test_padding_a_plan_with_born_dropped_slots_is_refused_slot_by_slot(self) -> None:
        """Five slots, four of them owing nothing, was the cheap way to look thorough."""
        self.write_plan(
            [figure(1)] + [figure(n, dropped_because=DROP_REASON) for n in (2, 3, 4, 5)]
        )
        problems = validate_report_plan(self.paths, "markdown")
        self.assertEqual(
            sum("dropped in the same plan that declares it" in p for p in problems), 4
        )

    def test_a_plan_with_no_drops_is_untouched(self) -> None:
        self.write_plan([figure(1), figure(2)])
        self.assertEqual(validate_report_plan(self.paths, "markdown"), [])

    def test_dropping_a_slot_after_autor_stamped_the_plan_is_allowed(self) -> None:
        """The legitimate case: the results came in and the figure became impossible."""
        self.write_plan([figure(1), figure(2)])
        stamp_report_plan(self.paths)
        self.write_plan([figure(1), figure(2, dropped_because=DROP_REASON)])
        self.assertEqual(validate_report_plan(self.paths, "markdown"), [])

    def test_the_agent_cannot_grant_itself_the_drop_by_writing_declared_at(self) -> None:
        """The stamp AutoR keeps outside ``workspace/`` is what the rule reads."""
        write_text(
            self.paths.report_plan,
            json.dumps(
                {
                    "figures": [figure(1), figure(2, dropped_because=DROP_REASON)],
                    "headline_numbers": HEADLINE,
                    "declared_at": "2020-01-01T00:00:00",
                    "digest": "0" * 64,
                }
            ),
        )
        problems = validate_report_plan(self.paths, "markdown")
        self.assertTrue(any("dropped in the same plan that declares it" in p for p in problems))


class EmptySourceArtifactTest(ReportPlanRobustnessTestCase):
    """``touch`` was the cheapest way past "produce the file your figure comes from"."""

    def setUp(self) -> None:
        super().setUp()
        self.source = self.paths.results_dir / "accuracy_by_length.json"
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.write_plan([figure(1)])

    def test_a_zero_byte_source_is_refused(self) -> None:
        self.source.write_text("")
        problems = validate_report_plan_sources(self.paths)
        self.assertTrue(any("which is empty" in problem for problem in problems))

    def test_a_whitespace_only_source_is_refused(self) -> None:
        self.source.write_text("\n  \n")
        self.assertTrue(any("which is empty" in p for p in validate_report_plan_sources(self.paths)))

    def test_the_empty_refusal_is_distinct_from_the_missing_one(self) -> None:
        """Two different repairs; a run told the wrong one repairs the wrong thing."""
        missing = validate_report_plan_sources(self.paths)
        self.source.write_text("")
        empty = validate_report_plan_sources(self.paths)
        self.assertTrue(any("does not exist" in problem for problem in missing))
        self.assertFalse(any("does not exist" in problem for problem in empty))

    def test_a_headline_number_is_held_to_the_same_floor(self) -> None:
        self.source.write_text("")
        problems = validate_report_plan_sources(self.paths)
        self.assertTrue(
            any("headline number 1" in p and "which is empty" in p for p in problems)
        )

    def test_one_byte_of_content_passes(self) -> None:
        """A floor under *a file was written*, not a judgement about the data."""
        self.source.write_text("{}")
        self.assertEqual(validate_report_plan_sources(self.paths), [])

    def test_an_empty_copy_in_one_root_does_not_mask_the_real_one(self) -> None:
        """The benchmark writes results outside the run tree; either copy may be the real one."""
        self.source.write_text("")
        outputs = Path(self._tmp.name) / "workspace" / "outputs"
        outputs.mkdir(parents=True, exist_ok=True)
        (outputs / "accuracy_by_length.json").write_text('{"accuracy": 0.91}')
        self.assertEqual(validate_report_plan_sources(self.paths, [outputs]), [])


if __name__ == "__main__":
    unittest.main()
