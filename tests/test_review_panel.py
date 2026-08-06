"""The panel is a gate, so the thing worth pinning is whether it can say no.

Most of these tests drive real `AutomatedReviewer` members with only their transport stubbed,
so the JSON grammar, the decision mapping and the blocking-objection rule are all exercised
for real rather than against a mock of themselves.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.approval_agent import ReviewDecision
from src.review_panel import (
    DEFAULT_PANEL,
    PANEL_EFFECT_FILENAME,
    apply_model_assignments,
    PanelRole,
    ReviewPanel,
    load_persona,
    resolve_roles,
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


STAGE_01 = next(stage for stage in STAGES if stage.slug == "01_literature_survey")
SUGGESTIONS = ["Tighten the scope.", "Strengthen the evidence.", "Clarify the risks."]


def _verdict_json(decision: str, *, blocking: bool = False, reason: str = "", feedback: str = "",
                  concerns: list[str] | None = None) -> str:
    return json.dumps(
        {
            "decision": decision,
            "blocking": blocking,
            "reason": reason or f"{decision} from a panel member",
            "feedback": feedback,
            "concerns": concerns or [],
        }
    )


class _ScriptedPanel:
    """A panel whose members answer from a script instead of a subprocess."""

    def __init__(self, testcase: unittest.TestCase, script: dict[str, list[str]], **kwargs):
        self.calls: list[tuple[str, str]] = []
        tmp_dir = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Study the thing.")
        write_text(self.paths.memory, "# Approved Run Memory\n")
        ensure_run_config(self.paths, model="sonnet", venue="neurips_2025")

        self.panel = ReviewPanel(
            kwargs.pop("roles", DEFAULT_PANEL),
            backend_name="claude",
            model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            **kwargs,
        )

        remaining = {key: list(values) for key, values in script.items()}

        def make(label_key: str, member):
            def run_prompt(*, paths, stage, attempt_no, prompt, label):
                self.calls.append((label_key, label))
                queue = remaining.get(label_key)
                if not queue:
                    raise AssertionError(f"No scripted response left for {label_key} ({label})")
                response = queue.pop(0)
                if response == "__FAIL__":
                    return 1, "", "backend exploded"
                return 0, response, ""

            member.run_prompt = run_prompt
            return member

        for role in self.panel.roles:
            make(role.key, self.panel._members[role.key])
        # The chair's synthesis call reuses the chair member, so its script is keyed separately.
        chair_member = self.panel._members[self.panel.chair.key]
        chair_queue = list(script.get("__chair__", []))
        member_run = chair_member.run_prompt

        def chair_aware_run(*, paths, stage, attempt_no, prompt, label):
            if label == "panel_chair":
                self.calls.append(("__chair__", label))
                if not chair_queue:
                    raise AssertionError("No scripted chair response left")
                response = chair_queue.pop(0)
                if response == "__FAIL__":
                    return 1, "", "chair exploded"
                return 0, response, ""
            return member_run(paths=paths, stage=stage, attempt_no=attempt_no, prompt=prompt, label=label)

        chair_member.run_prompt = chair_aware_run

    def review(self, attempt_no: int = 1) -> ReviewDecision:
        return self.panel.review_stage(
            paths=self.paths,
            stage=STAGE_01,
            attempt_no=attempt_no,
            stage_markdown="# Stage 01\n\n## Key Results\n\nSomething happened.\n",
            suggestions=SUGGESTIONS,
        )

    def rounds_for(self, role_key: str) -> int:
        return sum(1 for key, _label in self.calls if key == role_key)

    def record(self, attempt_no: int = 1) -> dict:
        path = self.paths.reviews_dir / "panel" / f"{STAGE_01.slug}_attempt_{attempt_no:02d}.json"
        return json.loads(read_text(path))


class RosterTests(unittest.TestCase):
    def test_the_default_roster_is_five_seats_with_one_chair(self) -> None:
        self.assertEqual(len(DEFAULT_PANEL), 5)
        self.assertEqual([role.key for role in DEFAULT_PANEL if role.chair], ["pi"])

    def test_every_seat_has_a_distinct_mandate(self) -> None:
        charters = {role.charter for role in DEFAULT_PANEL}
        self.assertEqual(len(charters), len(DEFAULT_PANEL))
        for role in DEFAULT_PANEL:
            self.assertTrue(role.looks_for, role.key)

    def test_a_subset_keeps_the_callers_order(self) -> None:
        roles = resolve_roles(["skeptic", "method"])
        self.assertEqual([role.key for role in roles], ["skeptic", "method"])

    def test_a_roster_without_the_pi_still_gets_a_chair(self) -> None:
        roles = resolve_roles(["method", "repro"])
        self.assertEqual([role.key for role in roles if role.chair], ["method"])

    def test_duplicate_keys_do_not_seat_the_same_member_twice(self) -> None:
        self.assertEqual([role.key for role in resolve_roles(["pi", "pi"])], ["pi"])

    def test_an_unknown_role_is_refused_rather_than_dropped(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            resolve_roles(["methodologist"])
        self.assertIn("Unknown panel role", str(ctx.exception))

    def test_an_empty_roster_falls_back_to_the_default(self) -> None:
        self.assertEqual(resolve_roles(None), DEFAULT_PANEL)
        self.assertEqual(resolve_roles([]), DEFAULT_PANEL)


class DeliberationTests(unittest.TestCase):
    def test_a_unanimous_approval_needs_no_second_round_and_no_chair(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        self.assertEqual(decision.choice, "5")
        for role in DEFAULT_PANEL:
            self.assertEqual(harness.rounds_for(role.key), 1, role.key)
        # Nothing to deliberate and nothing to synthesize.
        self.assertEqual(harness.rounds_for("__chair__"), 0)
        self.assertEqual(len(harness.record()["rounds"]), 1)

    def test_disagreement_triggers_a_cross_examination_round(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("custom_feedback", feedback="Add a baseline."),
                       _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve", reason="Objection resolved in round 2.")],
        }
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        self.assertEqual(harness.rounds_for("method"), 2)
        self.assertEqual(len(harness.record()["rounds"]), 2)
        self.assertEqual(decision.choice, "5")

    def test_round_one_members_are_not_shown_each_others_positions(self) -> None:
        seen: list[str] = []
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        original = harness.panel._build_member_prompt

        def capture(**kwargs):
            prompt = original(**kwargs)
            seen.append(prompt)
            return prompt

        harness.panel._build_member_prompt = capture
        harness.review()

        for prompt in seen:
            self.assertIn("independent review", prompt)
            self.assertNotIn("cross-examination", prompt)

    def test_the_second_round_shows_a_member_what_the_others_concluded(self) -> None:
        prompts: list[str] = []
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("custom_feedback", reason="No baseline anywhere."),
                       _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        original = harness.panel._build_member_prompt

        def capture(**kwargs):
            prompt = original(**kwargs)
            prompts.append(prompt)
            return prompt

        harness.panel._build_member_prompt = capture
        harness.review()

        second_round = [p for p in prompts if "cross-examination" in p]
        # Every seat but the adversarial reviewer, which is deliberately kept independent.
        self.assertEqual(len(second_round), len(DEFAULT_PANEL) - 1)
        self.assertTrue(any("No baseline anywhere." in p for p in second_round))
        # A member is not shown its own verdict as somebody else's position.
        methodologist = next(p for p in second_round if "You are the **Methodologist**" in p)
        self.assertIn("Your own round-1 position", methodologist)

    def test_peer_positions_are_anonymised_in_cross_examination(self) -> None:
        prompts: list[str] = []
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("custom_feedback", reason="No baseline anywhere."),
                       _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        original = harness.panel._build_member_prompt

        def capture(**kwargs):
            prompt = original(**kwargs)
            prompts.append(prompt)
            return prompt

        harness.panel._build_member_prompt = capture
        harness.review()

        peer_views = [p for p in prompts if "cross-examination" in p]
        for prompt in peer_views:
            # The substance survives; the attribution does not, so an objection is weighed on
            # its evidence rather than deferred to because the chair signed it.
            body = prompt.split("cross-examination", 1)[1].split("## Review Policy", 1)[0]
            self.assertIn("Reviewer A", body)
            self.assertNotIn("**Principal Investigator** ->", body)
        self.assertTrue(any("No baseline anywhere." in p for p in peer_views))

    def test_the_adversarial_seat_is_never_shown_the_room(self) -> None:
        prompts: list[str] = []
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("custom_feedback", reason="No baseline."),
                       _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        original = harness.panel._build_member_prompt

        def capture(**kwargs):
            prompt = original(**kwargs)
            prompts.append(prompt)
            return prompt

        harness.panel._build_member_prompt = capture
        harness.review()

        skeptic_round2 = [
            p for p in prompts
            if "You are the **Adversarial Reviewer**" in p and "Round 2" in p
        ]
        self.assertEqual(len(skeptic_round2), 1)
        self.assertIn("deliberately **not** being shown", skeptic_round2[0])
        self.assertNotIn("No baseline.", skeptic_round2[0])


class BlockingObjectionTests(unittest.TestCase):
    """The rule that makes this a gate rather than a formality."""

    def _panel_with_blocker(self, chair_decision: str):
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": [
                _verdict_json("custom_feedback", blocking=True,
                              reason="metrics.json does not exist.",
                              feedback="Produce the results file the summary cites."),
                _verdict_json("custom_feedback", blocking=True,
                              reason="metrics.json still does not exist.",
                              feedback="Produce the results file the summary cites."),
            ],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [chair_decision],
        }
        return _ScriptedPanel(self, script)

    def test_a_chair_cannot_approve_over_a_blocking_objection(self) -> None:
        harness = self._panel_with_blocker(
            _verdict_json("approve", reason="Minor gap; proceeding.")
        )

        decision = harness.review()

        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.decision_token, "custom_feedback")
        self.assertIn("Reproducibility Engineer", decision.feedback)
        self.assertIn("metrics.json", decision.feedback)

    def test_the_override_is_recorded_rather_than_silent(self) -> None:
        harness = self._panel_with_blocker(_verdict_json("approve"))
        harness.review()

        record = harness.record()
        self.assertTrue(record["chair_overridden"])
        self.assertIn("Reproducibility Engineer", record["override_reason"])
        self.assertEqual(record["blocking_after_deliberation"], ["repro"])

    def test_a_chair_that_already_refines_is_left_alone(self) -> None:
        harness = self._panel_with_blocker(
            _verdict_json("custom_feedback", feedback="Rebuild the results file.",
                          reason="Agreeing with the reproducibility objection.")
        )

        decision = harness.review()

        self.assertEqual(decision.choice, "4")
        self.assertEqual(decision.feedback, "Rebuild the results file.")
        self.assertFalse(harness.record()["chair_overridden"])

    def test_a_blocking_objection_withdrawn_in_round_two_stops_blocking(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": [
                _verdict_json("custom_feedback", blocking=True, reason="Cannot find metrics.json."),
                _verdict_json("approve", reason="Found it under results/; withdrawing."),
            ],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve", reason="Objection withdrawn.")],
        }
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        self.assertEqual(decision.choice, "5")
        self.assertFalse(harness.record()["chair_overridden"])
        self.assertEqual(harness.record()["blocking_after_deliberation"], [])

    def test_an_unparseable_answer_cannot_masquerade_as_a_veto(self) -> None:
        # parse_decision degrades junk to abort; that must not also count as a blocking veto.
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": ['{"decision":"nonsense","blocking":true}', _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        harness.review()
        self.assertEqual(harness.record()["rounds"][0][3]["blocking"], False)


class MemberFailureTests(unittest.TestCase):
    def test_an_unreachable_member_is_not_counted_as_agreeing(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": ["__FAIL__", _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        harness.review()

        # A failure breaks unanimity, so the panel deliberates rather than waving it through.
        self.assertEqual(len(harness.record()["rounds"]), 2)
        self.assertTrue(harness.record()["rounds"][0][2]["failed"])

    def test_an_unreachable_chair_falls_back_to_the_panels_own_objections(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [
                _verdict_json("custom_feedback", feedback="Add an ablation."),
                _verdict_json("custom_feedback", feedback="Add an ablation."),
            ],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": ["__FAIL__"],
        }
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        self.assertEqual(decision.choice, "4")
        self.assertIn("Add an ablation.", decision.feedback)


class RecordTests(unittest.TestCase):
    def test_dissent_that_lost_is_still_written_down(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [
                _verdict_json("custom_feedback", reason="The claim outruns the evidence.",
                              concerns=["No baseline", "n is tiny"]),
                _verdict_json("custom_feedback", reason="The claim outruns the evidence."),
            ],
            "__chair__": [_verdict_json("approve", reason="Overruling: the claim is hedged already.")],
        }
        harness = _ScriptedPanel(self, script)
        harness.review()

        markdown = read_text(harness.paths.reviews_dir / "panel" / f"{STAGE_01.slug}_attempt_01.md")
        self.assertIn("Adversarial Reviewer", markdown)
        self.assertIn("The claim outruns the evidence.", markdown)
        self.assertIn("No baseline", markdown)
        self.assertIn("Overruling", markdown)

    def test_the_record_lands_where_stage_08_reads_reviews(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        harness.review(attempt_no=3)

        panel_dir = harness.paths.reviews_dir / "panel"
        self.assertTrue((panel_dir / f"{STAGE_01.slug}_attempt_03.json").exists())
        self.assertTrue((panel_dir / f"{STAGE_01.slug}_attempt_03.md").exists())


class PersonaTests(unittest.TestCase):
    def test_a_persona_reaches_every_panelist(self) -> None:
        prompts: list[str] = []
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(
            self, script, persona_text="I care about effect sizes, not p-values."
        )
        original = harness.panel._build_member_prompt

        def capture(**kwargs):
            prompt = original(**kwargs)
            prompts.append(prompt)
            return prompt

        harness.panel._build_member_prompt = capture
        harness.review()

        self.assertEqual(len(prompts), len(DEFAULT_PANEL))
        for prompt in prompts:
            self.assertIn("I care about effect sizes, not p-values.", prompt)

    def test_no_persona_adds_no_section(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        prompt = harness.panel._build_member_prompt(
            paths=harness.paths, stage=STAGE_01, attempt_no=1,
            stage_markdown="x", suggestions=SUGGESTIONS,
            role=DEFAULT_PANEL[0], previous=None, round_no=1,
        )
        self.assertNotIn("The Researcher You Are Standing In For", prompt)

    def test_a_missing_persona_file_is_an_error_not_a_silent_empty(self) -> None:
        self.assertEqual(load_persona(None), "")
        with self.assertRaises(FileNotFoundError):
            load_persona("/nonexistent/persona.md")

    def test_a_persona_file_is_read(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        path = Path(tmp_dir.name) / "persona.md"
        path.write_text("# PI\n\nRigour over speed.\n", encoding="utf-8")
        self.assertIn("Rigour over speed.", load_persona(path))


class DropInContractTests(unittest.TestCase):
    def test_the_panel_satisfies_what_the_manager_reads_off_a_reviewer(self) -> None:
        panel = ReviewPanel(
            DEFAULT_PANEL,
            backend_name="claude",
            model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        self.assertEqual(panel.backend_name, "claude")
        self.assertEqual(panel.model, "sonnet")
        self.assertTrue(callable(panel.review_stage))

    def test_fake_mode_approves_so_smoke_runs_still_finish(self) -> None:
        script: dict[str, list[str]] = {}
        harness = _ScriptedPanel(self, script, fake_mode=True)
        decision = harness.review()
        self.assertEqual(decision.choice, "5")
        self.assertEqual(harness.calls, [])

    def test_a_single_seat_panel_is_legal(self) -> None:
        harness = _ScriptedPanel(
            self, {"skeptic": [_verdict_json("approve")]}, roles=resolve_roles(["skeptic"])
        )
        self.assertEqual(harness.review().choice, "5")

    def test_an_empty_roster_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            ReviewPanel((), backend_name="claude", model="sonnet")

    def test_roles_can_carry_their_own_backend_and_model(self) -> None:
        role = PanelRole(
            key="skeptic", title="Adversarial Reviewer", charter="c", looks_for=("x",),
            backend="codex", model="opus", chair=True,
        )
        panel = ReviewPanel(
            (role,), backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
        )
        member = panel._members["skeptic"]
        self.assertEqual(member.backend_name, "codex")
        self.assertEqual(member.model, "opus")


if __name__ == "__main__":
    unittest.main()


class PanelEffectTests(unittest.TestCase):
    """The panel must be able to report, in its own artifacts, that it did not help.

    A pre-registered comparison of two multi-agent feedback tools against a plain single pass
    found the single pass preferred, by the tools' own builders' measurement. A panel that
    cannot be shown to change a decision is that null wearing a costume, so the run records
    the comparison whether or not it flatters the feature.
    """

    def _effect(self, harness) -> dict:
        path = harness.paths.reviews_dir / "panel" / PANEL_EFFECT_FILENAME
        return json.loads(read_text(path))

    def test_a_unanimous_panel_reports_that_it_bought_nothing(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        harness.review()

        summary = self._effect(harness)["summary"]
        self.assertEqual(summary["gates_reviewed"], 1)
        self.assertEqual(summary["gates_where_the_panel_changed_the_decision"], 0)
        self.assertEqual(summary["cost_multiple"], 5.0)
        self.assertIn("did not earn that cost", summary["verdict"])

    def test_a_panel_that_overturns_the_chair_reports_the_change(self) -> None:
        script = {
            "pi": [_verdict_json("approve"), _verdict_json("approve")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": [
                _verdict_json("custom_feedback", blocking=True, reason="metrics.json absent."),
                _verdict_json("custom_feedback", blocking=True, reason="metrics.json absent."),
            ],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        harness.review()

        summary = self._effect(harness)["summary"]
        self.assertEqual(summary["gates_where_the_panel_changed_the_decision"], 1)
        self.assertEqual(summary["gates_where_round_1_disagreed"], 1)
        self.assertEqual(summary["chair_overrides"], 1)
        self.assertIn("changed the decision at 1 of 1", summary["verdict"])

    def test_the_baseline_is_the_chairs_own_round_one_verdict(self) -> None:
        # One model, one call, no peer input: every panel run contains its control arm free.
        script = {
            "pi": [_verdict_json("suggestion_2"), _verdict_json("suggestion_2")],
            "domain": [_verdict_json("approve"), _verdict_json("approve")],
            "method": [_verdict_json("approve"), _verdict_json("approve")],
            "repro": [_verdict_json("approve"), _verdict_json("approve")],
            "skeptic": [_verdict_json("approve"), _verdict_json("approve")],
            "__chair__": [_verdict_json("approve")],
        }
        harness = _ScriptedPanel(self, script)
        harness.review()

        gate = self._effect(harness)["gates"][0]
        self.assertEqual(gate["solo_choice"], "2")
        self.assertEqual(gate["panel_choice"], "5")
        self.assertTrue(gate["changed_decision"])

    def test_gates_accumulate_across_the_run(self) -> None:
        script = {role.key: [_verdict_json("approve")] * 3 for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        for stage in STAGES[:3]:
            harness.panel.review_stage(
                paths=harness.paths, stage=stage, attempt_no=1,
                stage_markdown="# S\n\n## Key Results\n\nx\n", suggestions=SUGGESTIONS,
            )
        self.assertEqual(self._effect(harness)["summary"]["gates_reviewed"], 3)

    def test_re_reviewing_one_attempt_replaces_rather_than_double_counts(self) -> None:
        script = {role.key: [_verdict_json("approve")] * 2 for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        harness.review(attempt_no=1)
        harness.review(attempt_no=1)
        self.assertEqual(self._effect(harness)["summary"]["gates_reviewed"], 1)

    def test_a_corrupt_effect_file_does_not_break_the_gate(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        path = harness.paths.reviews_dir / "panel" / PANEL_EFFECT_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text(path, "{ not json")
        self.assertEqual(harness.review().choice, "5")
        self.assertEqual(self._effect(harness)["summary"]["gates_reviewed"], 1)


class AbstentionTests(unittest.TestCase):
    def test_a_seat_with_nothing_to_add_may_abstain(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        script["domain"] = ['{"decision":"abstain","reason":"no field claim in this stage"}']
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        # An abstention is not disagreement, so the room is still unanimous and approves.
        self.assertEqual(decision.choice, "5")
        self.assertEqual(harness.rounds_for("__chair__"), 0)
        record = harness.record()
        self.assertTrue(record["rounds"][0][1]["abstained"])
        self.assertEqual(record["effect"]["abstentions"], 1)

    def test_an_all_abstaining_panel_is_not_treated_as_approval(self) -> None:
        script = {role.key: ['{"decision":"abstain","reason":"nothing"}'] * 2 for role in DEFAULT_PANEL}
        script["__chair__"] = [_verdict_json("custom_feedback", feedback="Nobody reviewed this.")]
        harness = _ScriptedPanel(self, script)

        decision = harness.review()

        # Silence from every seat must reach the chair rather than pass as consensus.
        self.assertGreater(harness.rounds_for("__chair__"), 0)
        self.assertEqual(decision.choice, "4")


class HeterogeneityTests(unittest.TestCase):
    def test_assignments_set_backend_and_model_per_seat(self) -> None:
        roles = apply_model_assignments(DEFAULT_PANEL, ["pi=opus", "skeptic=codex:default"])
        by_key = {role.key: role for role in roles}
        self.assertEqual((by_key["pi"].backend, by_key["pi"].model), (None, "opus"))
        self.assertEqual((by_key["skeptic"].backend, by_key["skeptic"].model), ("codex", "default"))
        self.assertIsNone(by_key["method"].model)

    def test_no_assignments_leaves_the_roster_untouched(self) -> None:
        self.assertEqual(apply_model_assignments(DEFAULT_PANEL, None), DEFAULT_PANEL)
        self.assertEqual(apply_model_assignments(DEFAULT_PANEL, []), DEFAULT_PANEL)

    def test_a_malformed_or_unknown_assignment_is_refused(self) -> None:
        for bad in ("pi", "pi=", "nobody=opus"):
            with self.assertRaises(ValueError, msg=bad):
                apply_model_assignments(DEFAULT_PANEL, [bad])

    def test_the_record_says_when_every_seat_shares_one_model(self) -> None:
        script = {role.key: [_verdict_json("approve")] for role in DEFAULT_PANEL}
        harness = _ScriptedPanel(self, script)
        harness.review()
        record = harness.record()
        # Five prompts against one model are five correlated reads; the record admits it.
        self.assertTrue(record["homogeneous_panel"])
        self.assertEqual(record["distinct_models"], ["sonnet"])

    def test_a_mixed_panel_is_recorded_as_heterogeneous(self) -> None:
        roles = apply_model_assignments(resolve_roles(["pi", "skeptic"]), ["skeptic=opus"])
        harness = _ScriptedPanel(
            self,
            {"pi": [_verdict_json("approve")], "skeptic": [_verdict_json("approve")]},
            roles=roles,
        )
        harness.review()
        record = harness.record()
        self.assertFalse(record["homogeneous_panel"])
        self.assertEqual(record["distinct_models"], ["opus", "sonnet"])
