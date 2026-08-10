"""Who dates the figure plan, and what a second round is allowed to do to it.

The agent chooses the figures. AutoR dates them: ``declared_at``, ``digest``
and ``amendments`` are written by the manager, never by the run, because asking
a language model for a sha256 is a wish rather than a gate.

What these tests hold is the drift discipline, not the wording of the log:

- a plan that did not move produces **no** amendment, so the ledger counts real
  changes rather than how many times a stage was approved;
- a plan that did move produces **exactly one**, carrying the reason the round
  already had to argue for in ``what_changes_next``;
- a run that arrives at the stage which draws the figures without ever passing
  through a Stage 03 approval — a resume, a ``--redo-stage``, a bootstrap — is
  still stamped, the same way the preregistration freezes again at Stage 05.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.evolution import EvolutionConfig
from src.manager import ResearchManager
from src.operator import ClaudeOperator
from src.report_plan import load_report_plan, report_plan_digest
from src.terminal_ui import TerminalUI
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_config,
    ensure_run_layout,
    initialize_memory,
    read_text,
    write_text,
)
from tests.prereg_support import close_round


REPO_ROOT = Path(__file__).resolve().parent.parent
#: ``STAGES`` is 1-indexed by stage number, so 06_analysis is element 5.
#: Named rather than indexed inline: the stage that draws the figures is
#: the one these tests are about, and an off-by-one here would silently
#: move them onto Stage 07.
STAGE_06 = next(stage for stage in STAGES if stage.slug == "06_analysis")


def plan_payload() -> dict[str, object]:
    """A plan as the Stage 03 agent writes it: figures and numbers, no stamp."""
    return {
        "figures": [
            {
                "slot": 1,
                "filename": "main_result.png",
                "supports": ["H1"],
                "shows": (
                    "Accuracy (%) against context length (tokens) for the method and the "
                    "long-context baseline, five seeds, band = stderr."
                ),
                "if_supported": "the method's curve stays above the baseline beyond 8k tokens",
                "if_refuted": "the two curves overlap within their bands at every length",
                "source_artifact": "results/accuracy_by_length.json",
                "dropped_because": "",
            },
            {
                "slot": 2,
                "filename": "data_overview.png",
                "supports": ["exploratory:input-distribution"],
                "shows": (
                    "Distribution of document length (tokens) and label balance across the "
                    "two evaluation splits."
                ),
                "if_supported": "the splits are comparable, so a difference is about the method",
                "if_refuted": "the splits differ in length and every comparison is conditioned",
                "source_artifact": "data/splits_summary.json",
                "dropped_because": "",
            },
        ],
        "headline_numbers": [
            {
                "quantity": "held-out accuracy, method vs baseline",
                "unit": "percentage points",
                "source_artifact": "results/accuracy_by_length.json",
            }
        ],
    }


class ReportPlanStampingTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_dir = Path(self._tmp.name) / "runs"
        self.runs_dir.mkdir()
        self.paths = build_run_paths(self.runs_dir / "run_0001")
        ensure_run_layout(self.paths)
        ensure_run_config(self.paths, model="sonnet", venue="neurips_2025")
        initialize_memory(self.paths, "plan stamping")
        write_text(self.paths.user_input, "plan stamping")
        ui = TerminalUI()
        self.manager = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=self.runs_dir,
            operator=ClaudeOperator(model="sonnet", fake_mode=True, ui=ui),
            ui=ui,
            output_stream=io.StringIO(),
            evolution=EvolutionConfig(rounds=0),
        )

    def _write_plan(self, payload: dict[str, object]) -> None:
        self.paths.report_plan.parent.mkdir(parents=True, exist_ok=True)
        write_text(self.paths.report_plan, json.dumps(payload, indent=2))

    def _stored(self) -> dict[str, object]:
        return json.loads(read_text(self.paths.report_plan))

    def _edit_plan(self, dropped: str) -> None:
        """Abandon slot 1, the way a later stage edits the file: in place.

        The stamp fields stay where AutoR put them — the agent is told not to
        write them, and rewriting the whole file from scratch is a different
        failure with a different owner.
        """
        stored = self._stored()
        stored["figures"][0]["dropped_because"] = dropped
        write_text(self.paths.report_plan, json.dumps(stored, indent=2))

    def test_the_first_stamp_dates_a_plan_the_agent_left_undated(self) -> None:
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)

        stored = self._stored()
        self.assertTrue(stored.get("declared_at"), "the plan was never dated")
        self.assertTrue(stored.get("digest"), "the plan has no content digest")
        self.assertEqual(stored.get("amendments"), [], "a first declaration is not an amendment")

    def test_a_plan_that_did_not_move_is_not_an_amendment(self) -> None:
        """Otherwise the ledger counts approvals instead of changes."""
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)
        first = self._stored()

        for _ in range(3):
            self.manager._stamp_report_plan(self.paths, reason="a round that changed nothing")
        again = self._stored()

        self.assertEqual(again["amendments"], [])
        self.assertEqual(again["digest"], first["digest"])
        self.assertEqual(again["declared_at"], first["declared_at"])
        self.assertEqual(read_text(self.paths.logs).count("report_plan declared"), 1)

    def test_a_plan_that_moved_records_exactly_one_amendment(self) -> None:
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)
        before = self._stored()

        self._edit_plan("the run never produced the length sweep")
        self.manager._stamp_report_plan(self.paths, reason="round 2 abandoned the length sweep")

        after = self._stored()
        self.assertEqual(len(after["amendments"]), 1)
        amendment = after["amendments"][0]
        self.assertEqual(amendment["previous_digest"], before["digest"])
        self.assertEqual(amendment["new_digest"], after["digest"])
        self.assertNotEqual(after["digest"], before["digest"])
        self.assertIn("report_plan amended", read_text(self.paths.logs))

    def test_the_amendment_reason_is_the_one_the_round_already_argued_for(self) -> None:
        """``what_changes_next`` is required to be 40+ chars before a round may
        re-enter Stage 03, so the reason the plan moved is already written down
        and already checked. Asking for it again would be the same sentence
        twice, and the second copy is the one nobody reads."""
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)
        close_round(
            self.paths,
            decision="refine_design",
            what_changes_next=(
                "Replace the length sweep with a per-domain breakdown, because the sweep "
                "cannot separate the effect from tokenizer differences."
            ),
        )

        self._edit_plan("superseded by the per-domain breakdown figure")
        self.manager._stamp_report_plan(self.paths)

        reason = self._stored()["amendments"][0]["reason"]
        self.assertIn("per-domain breakdown", reason)

    def test_the_first_declaration_has_no_round_to_cite(self) -> None:
        self.assertEqual(
            self.manager._report_plan_amendment_reason(self.paths), "initial declaration"
        )

    def test_a_rewrite_no_round_asked_for_is_not_recorded_as_a_declaration(self) -> None:
        """A --redo-stage or a hand edit is a revision nothing on record asked
        for. Reusing the first-write wording would put a false sentence in the
        ledger: the entry would say "initial declaration" about the second."""
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)

        self._edit_plan("nothing on record asked for this")
        self.manager._stamp_report_plan(self.paths)

        reason = self._stored()["amendments"][0]["reason"]
        self.assertNotEqual(reason, "initial declaration")
        self.assertIn("no round on record", reason)

    def test_a_wholesale_rewrite_cannot_re_date_the_plan(self) -> None:
        """The accident the ledger has to survive, not the attack.

        Stage 06 is told to edit ``report_plan.json``, and Stage 03 is told not
        to write ``declared_at``, ``digest`` or ``amendments``. A stage that
        regenerates the file from its own template obeys both instructions and
        produces a plan with no stamp on it. If the previous digest is read out
        of that file, the second write is indistinguishable from the first:
        ``declared_at`` becomes a post-results timestamp, the ledger stays
        empty, and the artifact's one claim — that the figures were chosen
        before the results existed — is now false with nothing recording it.
        """
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)
        first = self._stored()

        rewritten = plan_payload()
        rewritten["figures"][0]["filename"] = "the_one_that_came_out_well.png"
        self._write_plan(rewritten)  # no declared_at, no digest, no amendments
        self.manager._stamp_report_plan(self.paths, reason="rewritten at Stage 06")

        after = self._stored()
        self.assertEqual(after["declared_at"], first["declared_at"], "the plan was re-dated")
        self.assertEqual(len(after["amendments"]), 1, "the rewrite left no trace")
        self.assertEqual(after["amendments"][0]["previous_digest"], first["digest"])
        self.assertEqual(read_text(self.paths.logs).count("report_plan declared"), 1)
        self.assertIn("report_plan amended", read_text(self.paths.logs))

    def test_a_digest_the_run_wrote_itself_does_not_certify_the_plan(self) -> None:
        """A sha256 is a wish when it is asked for and a no-op when it is
        believed. Recomputing the digest over changed figures is a move any
        stage with a Python interpreter can make, and believing it would let a
        plan rewritten against the results claim it never moved."""
        self._write_plan(plan_payload())
        self.manager._stamp_report_plan(self.paths)
        first = self._stored()

        forged = self._stored()
        forged["figures"][0]["filename"] = "swapped_for_the_result_that_worked.png"
        write_text(self.paths.report_plan, json.dumps(forged, indent=2))
        # The run recomputes the sha256 over its own new content — the same
        # function AutoR uses — and writes it back as if nothing had moved.
        forged["digest"] = report_plan_digest(load_report_plan(self.paths))
        write_text(self.paths.report_plan, json.dumps(forged, indent=2))
        self.manager._stamp_report_plan(self.paths, reason="forged")

        after = self._stored()
        self.assertEqual(len(after["amendments"]), 1, "the forged digest hid the change")
        self.assertEqual(after["amendments"][0]["previous_digest"], first["digest"])
        self.assertEqual(after["declared_at"], first["declared_at"])

    def test_a_missing_plan_is_the_gate_s_finding_and_not_this_hook_s(self) -> None:
        """The Stage 03 artifact gate refuses a run with no plan and says so in
        the log. A hook that fires on every stage from 06 onward must not turn
        that one refusal into a line per stage."""
        self.manager._stamp_report_plan(self.paths)

        self.assertFalse(self.paths.report_plan.exists())
        self.assertNotIn("report_plan", read_text(self.paths.logs))

    def test_a_run_that_never_passed_through_stage_03_is_stamped_anyway(self) -> None:
        """Resume, --redo-stage and --project-root all skip the approval hook.
        The stage that draws the figures is the last honest place to date them."""
        self._write_plan(plan_payload())

        self.manager._build_stage_prompt(self.paths, STAGE_06, None, False)

        self.assertTrue(self._stored().get("declared_at"))

    def test_the_stage_that_draws_the_figures_is_shown_the_plan(self) -> None:
        self._write_plan(plan_payload())

        prompt = self.manager._build_stage_prompt(self.paths, STAGE_06, None, False)

        self.assertIn("Report Plan", prompt)
        self.assertIn("main_result.png", prompt)


if __name__ == "__main__":
    unittest.main()
