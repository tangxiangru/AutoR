"""What a panel seat inherits from the run, and what a panel run leaves behind.

Two mechanisms accumulate across a run and both used to reach exactly one reader. The
standing rules earlier refusals produced (`review_policy.json`) and the obligations earlier
approvals attached (`obligations.json`) were rendered into `AutomatedReviewer`'s prompt and
nowhere else, and neither the seat prompt nor the chair prompt asked for `carry_forward`, so
a panel run could not create an obligation either.

The sharp form of that: `--rigor max` had *fewer* live mechanisms than `--rigor standard`,
because the higher setting swaps the solo reviewer for the panel and the panel could not see
what the solo reviewer sees. `ParityWithTheSoloReviewerTests` is the test for the dial itself
— it asserts the two prompts argue from the same rendered blocks, so the panel cannot silently
fall behind the reviewer it replaces again.

The discharge half is deliberately not symmetric with the carry-forward half, and
`OnlyTheChairClosesADebtTests` is where that asymmetry is pinned: any seat may record a debt
(five seats then make the run stricter), only the chair's last word closes one (five seats
must not become five chances to write one off).
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src import approval_agent, obligations as obligations_module, review_panel
from src import review_policy as review_policy_module
from src.approval_agent import AutomatedReviewer, ReviewDecision
from src.manager import ResearchManager
from src.obligations import (
    DISCHARGED,
    OPEN,
    format_for_review_prompt,
    load_ledger,
    record_obligations,
)
from src.review_panel import (
    DEFAULT_PANEL,
    PanelDeliberation,
    PanelVerdict,
    ReviewPanel,
    resolve_roles,
)
from src.review_policy import format_policy_for_prompt, load_policy, record_correction
from src.terminal_ui import TerminalUI
from src.utils import STAGES, build_run_paths, ensure_run_config, ensure_run_layout, read_text, write_text
from tests.test_review_panel import STAGE_01, SUGGESTIONS, _ScriptedPanel


STAGE_03 = next(stage for stage in STAGES if stage.slug == "03_study_design")
RULE = "Every number in a summary must name the file it was read from."
#: A rule Stage 03's own attempt 1 produced. It binds Stage 04 onward and must reach
#: neither gate while Stage 03 is the stage under review — see
#: `format_policy_for_prompt`'s `stage` argument. Without a row the filter has to
#: reject, every parity assertion in this file would hold with that argument deleted.
OWN_STAGE_RULE = "State the randomisation seed next to every split this stage defines."
DEBT = "State a power analysis and justify the sample size before any experiment is run."
OTHER_DEBT = "Report a confidence interval for every metric, computed from the raw measurements."


def _seat_json(
    decision: str,
    *,
    blocking: bool = False,
    reason: str = "",
    feedback: str = "",
    carry_forward: list | None = None,
    discharged: list | None = None,
) -> str:
    """A seat's raw answer, in the grammar the seat prompt asks for."""
    return json.dumps(
        {
            "decision": decision,
            "blocking": blocking,
            "reason": reason or f"{decision} from a panel member",
            "feedback": feedback,
            "concerns": [],
            "carry_forward": carry_forward or [],
            "discharged": discharged or [],
        }
    )


def _debt(text: str = DEBT, target: str = "03_study_design") -> dict:
    return {"obligation": text, "target_stage": target}


class PromptTestBase(unittest.TestCase):
    """A run whose ledger and policy are non-empty, and a panel built over it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Study the thing.")
        write_text(self.paths.memory, "# Approved Run Memory\n")
        ensure_run_config(self.paths, model="sonnet", venue="neurips_2025")

        record_correction(self.paths, stage=STAGE_01, attempt_no=1, text=RULE)
        record_correction(self.paths, stage=STAGE_03, attempt_no=1, text=OWN_STAGE_RULE)
        record_obligations(self.paths, stage=STAGE_01, entries=[_debt()])

        self.ui = TerminalUI(output_stream=io.StringIO(), interactive=False)
        self.panel = ReviewPanel(DEFAULT_PANEL, backend_name="claude", model="sonnet", ui=self.ui)

    def rendered_rules(self, *, stage=STAGE_03) -> str:
        """What either gate should be showing, for a review of ``stage``."""
        return format_policy_for_prompt(load_policy(self.paths), stage=stage)

    def seat_prompt(self, role=None, *, previous=None, round_no: int = 1, stage=STAGE_03) -> str:
        return self.panel._build_member_prompt(
            paths=self.paths, stage=stage, attempt_no=1, stage_markdown="# Stage\n",
            suggestions=SUGGESTIONS, role=role or DEFAULT_PANEL[0], previous=previous,
            round_no=round_no,
        )

    def chair_prompt(self, deliberation=None, *, stage=STAGE_03) -> str:
        return self.panel._build_chair_prompt(
            paths=self.paths, stage=stage, attempt_no=1, stage_markdown="# Stage\n",
            suggestions=SUGGESTIONS,
            deliberation=deliberation or PanelDeliberation(stage_slug=stage.slug, attempt_no=1, chair_key="pi"),
        )

    def solo_prompt(self, *, stage=STAGE_03) -> str:
        solo = AutomatedReviewer("claude", model="sonnet", ui=self.ui)
        return solo._build_review_prompt(
            paths=self.paths, stage=stage, attempt_no=1, stage_markdown="# Stage\n",
            suggestions=SUGGESTIONS,
        )


class ParityWithTheSoloReviewerTests(PromptTestBase):
    """The dial must not lose a mechanism as it is turned up."""

    def test_the_fixture_really_does_hold_a_rule_and_a_debt(self) -> None:
        # Guards every assertion below: against an empty policy and an empty ledger the
        # renderers return "", and "the panel prompt contains it" would pass on nothing.
        self.assertTrue(self.rendered_rules())
        self.assertTrue(format_for_review_prompt(load_ledger(self.paths), STAGE_03))

    def test_the_fixture_holds_a_rule_the_stage_filter_has_to_reject(self) -> None:
        """Otherwise the parity assertions below hold with the `stage` argument deleted."""
        self.assertIn(OWN_STAGE_RULE, format_policy_for_prompt(load_policy(self.paths)))
        self.assertNotIn(OWN_STAGE_RULE, self.rendered_rules())
        self.assertIn(RULE, self.rendered_rules())

    def test_a_seat_argues_from_the_same_standing_rules_as_the_solo_reviewer(self) -> None:
        rendered = self.rendered_rules()
        self.assertIn(rendered, self.solo_prompt())
        self.assertIn(rendered, self.seat_prompt())

    def test_neither_gate_judges_a_stage_against_a_rule_its_own_retries_invented(self) -> None:
        """Parity is what the two gates *render*, not only which function they call.

        `format_policy_for_prompt` withholds the rules a stage's own attempts produced,
        because a review that demands anything records one and the bar would otherwise rise
        by a requirement per attempt until the retry loop could not converge. Calling the
        same renderer with a different argument list reintroduces exactly that, and under a
        panel it is five seats reading the moving bar instead of one. `assertIs` on the
        function objects cannot see it; this can.
        """
        for name, prompt in (("solo", self.solo_prompt()), ("seat", self.seat_prompt()),
                             ("chair", self.chair_prompt())):
            with self.subTest(prompt=name):
                self.assertIn(RULE, prompt)
                self.assertNotIn(OWN_STAGE_RULE, prompt)

    def test_a_seat_is_asked_about_the_same_inherited_obligations(self) -> None:
        rendered = format_for_review_prompt(load_ledger(self.paths), STAGE_03)
        self.assertIn(rendered, self.solo_prompt())
        self.assertIn(rendered, self.seat_prompt())

    def test_the_chair_sees_both_as_well(self) -> None:
        prompt = self.chair_prompt()
        self.assertIn(self.rendered_rules(), prompt)
        self.assertIn(format_for_review_prompt(load_ledger(self.paths), STAGE_03), prompt)

    def test_every_seat_in_the_roster_sees_both(self) -> None:
        rules = self.rendered_rules()
        debts = format_for_review_prompt(load_ledger(self.paths), STAGE_03)
        for role in DEFAULT_PANEL:
            with self.subTest(role=role.key):
                prompt = self.seat_prompt(role)
                self.assertIn(rules, prompt)
                self.assertIn(debts, prompt)

    def test_the_seat_that_is_shown_nothing_of_the_room_is_still_shown_the_run(self) -> None:
        """`exposure="none"` withholds the peers, not the run's own accumulated record."""
        skeptic = next(role for role in DEFAULT_PANEL if role.exposure == "none")
        previous = [
            PanelVerdict(role_key="pi", role_title="Principal Investigator", backend="claude",
                         model="sonnet", choice="5", decision_token="approve", blocking=False,
                         reason="fine", feedback=""),
        ]
        prompt = self.seat_prompt(skeptic, previous=previous, round_no=2)
        self.assertIn("hold or revise, independently", prompt)
        self.assertIn(self.rendered_rules(), prompt)
        self.assertIn(format_for_review_prompt(load_ledger(self.paths), STAGE_03), prompt)

    def test_both_paths_ask_for_the_two_ledger_fields(self) -> None:
        for name, prompt in (("seat", self.seat_prompt()), ("chair", self.chair_prompt()),
                             ("solo", self.solo_prompt())):
            with self.subTest(prompt=name):
                self.assertIn('"carry_forward"', prompt)
                self.assertIn('"discharged"', prompt)

    def test_a_seat_is_told_that_only_the_chair_closes_a_debt(self) -> None:
        self.assertIn("Only the chair's list closes a debt", self.seat_prompt())

    def test_both_gates_call_the_same_two_renderers(self) -> None:
        """Not "both prompts say something similar": both prompts call one function.

        The prompt assertions above compare rendered strings, which would still pass if the
        panel grew its own copy of the wording that happened to agree today. This is the
        structural half of the same claim, and the reason `docs/review-panel.md` can say the
        two gates argue from one copy of the rules.

        Necessary and not sufficient: one renderer called with two different argument lists
        passes this and diverges anyway, which is what
        `test_neither_gate_judges_a_stage_against_a_rule_its_own_retries_invented` is for.
        """
        self.assertIs(review_panel.format_policy_for_prompt, review_policy_module.format_policy_for_prompt)
        self.assertIs(review_panel.format_for_review_prompt, obligations_module.format_for_review_prompt)
        self.assertIs(approval_agent.format_policy_for_prompt, review_policy_module.format_policy_for_prompt)
        self.assertIs(approval_agent.format_for_review_prompt, obligations_module.format_for_review_prompt)

    def test_the_doc_names_the_renderers_it_claims_are_shared(self) -> None:
        doc = (Path(__file__).resolve().parent.parent / "docs" / "review-panel.md").read_text(encoding="utf-8")
        for symbol in ("format_policy_for_prompt", "format_for_review_prompt", "_context_block"):
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, doc)

    def test_a_run_with_nothing_learned_yet_gets_no_empty_sections(self) -> None:
        """An empty ledger is silence, not a heading over nothing."""
        fresh = build_run_paths(Path(self._tmp.name) / "run_0002")
        ensure_run_layout(fresh)
        write_text(fresh.user_input, "Study the thing.")
        write_text(fresh.memory, "# Approved Run Memory\n")
        ensure_run_config(fresh, model="sonnet", venue="neurips_2025")
        prompt = self.panel._build_member_prompt(
            paths=fresh, stage=STAGE_03, attempt_no=1, stage_markdown="# Stage\n",
            suggestions=SUGGESTIONS, role=DEFAULT_PANEL[0], previous=None, round_no=1,
        )
        self.assertNotIn("# Standing Review Rules", prompt)
        self.assertNotIn("# Inherited Obligations", prompt)

    def test_an_obligation_aimed_at_another_stage_does_not_reach_this_room(self) -> None:
        """`open_for` decides, here as for the solo reviewer: the debt targets Stage 03."""
        self.assertNotIn(DEBT, self.seat_prompt(stage=STAGE_01))


class _StubOperator:
    model = "opus"
    backend_name = "claude"


class AnySeatCanCreateADebtTests(unittest.TestCase):
    """A panel run that cannot leave an obligation behind has nothing to inherit later."""

    def _panel(self, script: dict) -> _ScriptedPanel:
        return _ScriptedPanel(self, script)

    def test_a_unanimous_approval_still_carries_what_a_seat_asked_for(self) -> None:
        """The ordinary path. No chair call happens here at all."""
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", carry_forward=[_debt()])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        decision = panel.review()
        self.assertEqual(decision.choice, "5")
        self.assertEqual(len(decision.carry_forward), 1)
        self.assertEqual(decision.carry_forward[0]["obligation"], DEBT)
        self.assertNotIn("__chair__", [key for key, _label in panel.calls])

    def test_a_debt_survives_the_chair_and_joins_the_chairs_own(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("custom_feedback", feedback="fix the citation",
                                   carry_forward=[_debt()])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("custom_feedback", feedback="do the thing",
                                     carry_forward=[_debt(OTHER_DEBT, "05_experiments")])],
        }
        # `--panel-rounds 1` keeps the script to one round per seat; the second round is
        # tested elsewhere and would only lengthen the fixture.
        panel = _ScriptedPanel(self, script, deliberation_rounds=1)
        decision = panel.review()
        carried = [entry["obligation"] for entry in decision.carry_forward]
        self.assertEqual(carried, [DEBT, OTHER_DEBT])

    def test_an_overridden_chair_does_not_drop_the_debts(self) -> None:
        """`_enforce_blocking_objections` builds a fresh decision; the ledger rides through."""
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", carry_forward=[_debt()])],
            "method": [_seat_json("custom_feedback", blocking=True, feedback="blocked")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("approve")],
        }
        panel = _ScriptedPanel(self, script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.choice, "4")
        self.assertTrue(panel.record()["chair_overridden"])
        self.assertEqual([entry["obligation"] for entry in decision.carry_forward], [DEBT])

    def test_a_seat_that_could_not_be_reached_carries_nothing(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": ["__FAIL__"],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("approve")],
        }
        panel = _ScriptedPanel(self, script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.carry_forward, [])

    def test_what_a_seat_writes_is_in_the_shape_the_ledger_accepts(self) -> None:
        """End to end through the manager funnel: seat JSON in, obligation on disk out."""
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", carry_forward=[_debt()])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        decision = panel.review()

        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=panel.paths.run_root.parent,
            operator=_StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        manager._settle_obligations(paths=panel.paths, stage=STAGE_01, attempt_no=1, decision=decision)

        ledger = load_ledger(panel.paths)
        self.assertEqual([o.text for o in ledger.obligations], [DEBT])
        self.assertEqual(ledger.obligations[0].target_stage, "03_study_design")
        self.assertIn("obligation_recorded", read_text(panel.paths.logs))


class OnlyTheChairClosesADebtTests(unittest.TestCase):
    """Creating a debt is the strict direction; closing one is not, so they differ."""

    def _panel(self, script: dict, **kwargs) -> _ScriptedPanel:
        panel = _ScriptedPanel(self, script, **kwargs)
        record_obligations(panel.paths, stage=STAGE_01, entries=[_debt(target="01_literature_survey")])
        return panel

    def test_a_seat_alone_cannot_write_an_obligation_off(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", discharged=["O001"])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        decision = panel.review()
        self.assertEqual(decision.discharged, [])

    def test_the_claim_the_chair_did_not_take_is_still_on_the_record(self) -> None:
        """Refused in code, not hidden: the chair reads it, and so does an auditor."""
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", discharged=["O001"])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        panel.review()
        record = panel.record()
        seats = {v["role"]: v for v in record["rounds"][0]}
        self.assertEqual(seats["domain"]["discharged"], ["O001"])
        self.assertEqual(record["discharged"], [])

    def test_the_chair_seat_closes_a_debt_when_the_room_never_split(self) -> None:
        """No chair call is made on a unanimous approval, so its seat verdict is its word."""
        script = {
            "pi": [_seat_json("approve", discharged=["O001"])],
            "domain": [_seat_json("approve")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        decision = panel.review()
        self.assertEqual(decision.discharged, ["O001"])

    def test_the_chairs_synthesis_closes_a_debt(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("custom_feedback", feedback="tighten it")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("approve", discharged=["O001"])],
        }
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.discharged, ["O001"])

    def test_once_the_room_splits_the_chairs_earlier_seat_verdict_stops_counting(self) -> None:
        """It was a position taken before the chair heard the objections."""
        script = {
            "pi": [_seat_json("approve", discharged=["O001"])],
            "domain": [_seat_json("custom_feedback", feedback="tighten it")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("custom_feedback", feedback="tighten it")],
        }
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.discharged, [])

    def test_nothing_is_discharged_while_a_blocking_objection_stands(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("custom_feedback", blocking=True, feedback="blocked")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [_seat_json("approve", discharged=["O001"])],
        }
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.discharged, [])

    def test_a_refusing_chair_cannot_close_a_debt_on_its_way_out(self) -> None:
        """The blocking rule has to be written onto the decision, not onto the override.

        A chair does not have to approve to claim a discharge. `_enforce_blocking_objections`
        rebuilds the decision only when the chair *approved* — that is the whole of its job —
        so on this script it returns the chair's own decision untouched, `chair_overridden`
        stays false, and the chair's `discharged` list is still on it. The refusal therefore
        has to come from `_attach_ledger_positions` writing the room's empty list over it
        unconditionally. The sibling test above passes with an approving chair and cannot
        reach this arm.
        """
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("custom_feedback", blocking=True, feedback="blocked")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": [
                _seat_json("custom_feedback", feedback="tighten it", discharged=["O001"])
            ],
        }
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        record = panel.record()
        self.assertEqual(decision.choice, "4")
        # The override arm did not run, so nothing else rebuilt this decision.
        self.assertFalse(record["chair_overridden"])
        self.assertEqual(decision.discharged, [])
        # The audit record and the channel the manager reads must not be able to disagree.
        self.assertEqual(record["discharged"], [])

        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=panel.paths.run_root.parent,
            operator=_StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        manager._settle_obligations(paths=panel.paths, stage=STAGE_01, attempt_no=1, decision=decision)
        self.assertEqual(load_ledger(panel.paths).by_id("O001").status, OPEN)

        # The control: `O001` is a real open id and this funnel does close it, so the
        # assertion above is the panel's rule refusing rather than a typo in an id.
        manager._settle_obligations(
            paths=panel.paths, stage=STAGE_01, attempt_no=2,
            decision=ReviewDecision(choice="5", decision_token="approve", reason="ok",
                                    discharged=["O001"]),
        )
        self.assertEqual(load_ledger(panel.paths).by_id("O001").status, DISCHARGED)

    def test_a_chair_that_could_not_be_reached_discharges_nothing(self) -> None:
        script = {
            "pi": [_seat_json("approve", discharged=["O001"])],
            "domain": [_seat_json("custom_feedback", feedback="tighten it")],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
            "__chair__": ["__FAIL__"],
        }
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.discharged, [])

    def test_a_total_outage_settles_nothing_in_either_direction(self) -> None:
        script = {key: ["__FAIL__"] for key in ("pi", "domain", "method", "repro", "skeptic")}
        script["__chair__"] = ["__FAIL__"]
        panel = self._panel(script, deliberation_rounds=1)
        decision = panel.review()
        self.assertEqual(decision.carry_forward, [])
        self.assertEqual(decision.discharged, [])

    def test_an_applied_discharge_reaches_the_ledger_and_a_refused_one_does_not(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", discharged=["O001"])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = self._panel(script)
        decision = panel.review()
        manager = ResearchManager(
            project_root=Path(__file__).resolve().parent.parent,
            runs_dir=panel.paths.run_root.parent,
            operator=_StubOperator(),
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        manager._settle_obligations(paths=panel.paths, stage=STAGE_01, attempt_no=1, decision=decision)
        self.assertEqual(load_ledger(panel.paths).by_id("O001").status, OPEN)

        # The control: the id is real and the funnel does close it, so the assertion above
        # is the panel's rule refusing and not a typo in an obligation id.
        manager._settle_obligations(
            paths=panel.paths, stage=STAGE_01, attempt_no=2,
            decision=ReviewDecision(choice="5", decision_token="approve", reason="ok",
                                    discharged=["O001"]),
        )
        self.assertEqual(load_ledger(panel.paths).by_id("O001").status, DISCHARGED)


class LedgerPositionsTests(unittest.TestCase):
    """The aggregation rules, at the level where they are decidable.

    Driving these through a scripted panel cannot reach them: a seat that abstains or fails
    is constructed with empty ledger fields, so the filters below would look correct while
    holding nothing. Built by hand, each filter has a case that dies without it.
    """

    def _verdict(self, key: str, **kwargs) -> PanelVerdict:
        base = dict(
            role_key=key, role_title=key.title(), backend="claude", model="sonnet",
            choice="5", decision_token="approve", blocking=False, reason="", feedback="",
        )
        base.update(kwargs)
        return PanelVerdict(**base)

    def _deliberation(self, verdicts: list[PanelVerdict]) -> PanelDeliberation:
        deliberation = PanelDeliberation(stage_slug=STAGE_01.slug, attempt_no=1, chair_key="pi")
        deliberation.rounds.append(verdicts)
        return deliberation

    def test_a_seat_that_abstained_is_not_carrying_a_debt(self) -> None:
        """Abstention is "nothing to add", and a debt is something to add."""
        deliberation = self._deliberation(
            [self._verdict("domain", abstained=True, choice="", decision_token="abstain",
                           carry_forward=(_debt(),))]
        )
        self.assertEqual(deliberation.carried_obligations(), [])

    def test_a_seat_that_could_not_be_reached_is_not_carrying_a_debt(self) -> None:
        deliberation = self._deliberation(
            [self._verdict("domain", failed=True, choice="4", decision_token="custom_feedback",
                           carry_forward=(_debt(),))]
        )
        self.assertEqual(deliberation.carried_obligations(), [])

    def test_two_seats_naming_one_debt_are_both_kept_for_the_record(self) -> None:
        """`record_obligations` deduplicates; who raised it is information the record keeps."""
        deliberation = self._deliberation(
            [self._verdict("domain", carry_forward=(_debt(),)),
             self._verdict("method", carry_forward=(_debt(),))]
        )
        self.assertEqual(len(deliberation.carried_obligations()), 2)

    def test_only_the_final_round_carries(self) -> None:
        """A debt a seat withdrew in cross-examination is not one the run inherits."""
        deliberation = self._deliberation([self._verdict("domain", carry_forward=(_debt(),))])
        deliberation.rounds.append([self._verdict("domain")])
        self.assertEqual(deliberation.carried_obligations(), [])

    def test_a_chair_that_abstained_closes_nothing(self) -> None:
        deliberation = self._deliberation(
            [self._verdict("pi", abstained=True, choice="", decision_token="abstain",
                           discharged=("O001",))]
        )
        self.assertEqual(deliberation.settled_obligations(), [])

    def test_a_roster_with_no_seated_chair_closes_nothing(self) -> None:
        deliberation = self._deliberation([self._verdict("domain", discharged=("O001",))])
        self.assertEqual(deliberation.settled_obligations(), [])


class AVerdictIsNotHashableAtAllTests(unittest.TestCase):
    """The ledger fields made `PanelVerdict` hashable only for seats that used neither.

    `frozen=True` generates a `__hash__` over every field. `carry_forward` holds whatever
    `record_obligations` accepts, and that includes dicts, so before the refusal a verdict
    from a seat that carried nothing hashed and the identical verdict from a seat that
    carried one raised `TypeError` from inside the tuple. A container that works until a
    seat uses a feature is the worse of the two, so it is refused for every verdict.
    """

    def _verdict(self, **kwargs) -> PanelVerdict:
        base = dict(
            role_key="domain", role_title="Domain Expert", backend="claude", model="sonnet",
            choice="5", decision_token="approve", blocking=False, reason="", feedback="",
        )
        base.update(kwargs)
        return PanelVerdict(**base)

    def test_neither_an_empty_verdict_nor_a_carrying_one_can_be_hashed(self) -> None:
        for label, verdict in (
            ("carries nothing", self._verdict()),
            ("carries a debt", self._verdict(carry_forward=(_debt(),))),
        ):
            with self.subTest(seat=label):
                with self.assertRaises(TypeError):
                    hash(verdict)
                with self.assertRaises(TypeError):
                    {verdict}

    def test_the_refusal_did_not_cost_equality(self) -> None:
        """`__hash__ = None` on a dataclass can take `__eq__` with it if it is misdeclared."""
        self.assertEqual(self._verdict(carry_forward=(_debt(),)), self._verdict(carry_forward=(_debt(),)))
        self.assertNotEqual(self._verdict(), self._verdict(carry_forward=(_debt(),)))


class NoStandInVerdictClaimsADischargeTests(unittest.TestCase):
    """`chair_verdict` is read without asking who wrote it, and this is why that is safe.

    When the chair cannot be read, `parse_with_retry` hands back a decision AutoR assembled
    on its behalf. The panel records that as the chair's word for ledger purposes, which is
    only harmless while every stand-in in the tree is empty in both fields — one that
    inherited the seats' discharge claims would close a debt no chair ever agreed to. The
    alternative was a "did the chair really write this" flag that no test could distinguish
    from its absence, so the invariant is pinned here instead of guarded there.
    """

    def _panel(self) -> ReviewPanel:
        return ReviewPanel(
            DEFAULT_PANEL, backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )

    def _verdict(self, **kwargs) -> PanelVerdict:
        base = dict(
            role_key="domain", role_title="Domain Expert", backend="claude", model="sonnet",
            choice="4", decision_token="custom_feedback", blocking=False, reason="no",
            feedback="fix it", discharged=("O001",), carry_forward=(_debt(),),
        )
        base.update(kwargs)
        return PanelVerdict(**base)

    def test_no_verdict_autor_writes_in_a_reviewers_place_settles_the_ledger(self) -> None:
        panel = self._panel()
        reviewer = AutomatedReviewer(
            "claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        stand_ins = {
            "dissent": panel._decision_from_dissent([self._verdict()], reason="chair gone"),
            "total outage": panel._decision_from_dissent(
                [self._verdict(failed=True)], reason="everyone gone"
            ),
            "unreadable": reviewer._unreadable_verdict("not json at all"),
            "unsupported token": reviewer._parse_decision('{"decision":"maybe","discharged":["O001"]}'),
        }
        for label, decision in stand_ins.items():
            with self.subTest(stand_in=label):
                self.assertEqual(list(decision.carry_forward), [])
                self.assertEqual(list(decision.discharged), [])


class TheChairIsShownWhatTheRoomProposedTests(PromptTestBase):
    def _deliberation(self) -> PanelDeliberation:
        deliberation = PanelDeliberation(stage_slug=STAGE_03.slug, attempt_no=1, chair_key="pi")
        deliberation.rounds.append(
            [
                PanelVerdict(
                    role_key="domain", role_title="Domain Expert", backend="claude",
                    model="sonnet", choice="5", decision_token="approve", blocking=False,
                    reason="fine", feedback="", carry_forward=(_debt(),), discharged=("O001",),
                )
            ]
        )
        return deliberation

    def test_the_transcript_names_the_debts_and_the_claims(self) -> None:
        prompt = self.chair_prompt(self._deliberation())
        self.assertIn(f"Carries forward: {DEBT} (target: 03_study_design)", prompt)
        self.assertIn("Claims discharged: O001", prompt)

    def test_the_chair_is_told_which_of_the_two_is_its_decision(self) -> None:
        prompt = self.chair_prompt(self._deliberation())
        self.assertIn("the discharges are yours alone", prompt)


class TheRecordSaysWhatTheLedgerGotTests(unittest.TestCase):
    def test_the_markdown_and_the_log_name_the_carried_debt(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", carry_forward=[_debt()])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = _ScriptedPanel(self, script)
        panel.review()
        markdown = read_text(
            panel.paths.reviews_dir / "panel" / f"{STAGE_01.slug}_attempt_01.md"
        )
        self.assertIn(f"Carried forward: {DEBT}", markdown)
        self.assertIn("obligations: 1 carried forward, 0 discharged", read_text(panel.paths.logs))

    def test_the_json_record_carries_both_lists(self) -> None:
        script = {
            "pi": [_seat_json("approve")],
            "domain": [_seat_json("approve", carry_forward=[_debt()])],
            "method": [_seat_json("approve")],
            "repro": [_seat_json("approve")],
            "skeptic": [_seat_json("approve")],
        }
        panel = _ScriptedPanel(self, script)
        panel.review()
        record = panel.record()
        self.assertEqual(record["carry_forward"][0]["obligation"], DEBT)
        self.assertEqual(record["discharged"], [])


class ASingleSeatPanelStillHasAChairTests(unittest.TestCase):
    def test_the_lone_seat_holds_the_gavel_and_can_close_a_debt(self) -> None:
        """`resolve_roles` gives the first seat the gavel, so the rule still has a subject."""
        roles = resolve_roles(["repro"])
        panel = _ScriptedPanel(
            self, {"repro": [_seat_json("approve", discharged=["O001"])]}, roles=roles
        )
        record_obligations(panel.paths, stage=STAGE_01, entries=[_debt(target="01_literature_survey")])
        decision = panel.review()
        self.assertEqual(decision.discharged, ["O001"])


if __name__ == "__main__":
    unittest.main()
