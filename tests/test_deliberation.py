"""Stopping to think, and checking whether it was worth stopping.

Uniform deliberation lost to a single pass in the pre-registered comparison. The bet here is
that *selective* deliberation is different — so the tests that matter are the ones about
selection: can a crux be raised, is the budget real, and does the ledger admit when escalating
confirmed what the agent already believed.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from src.deliberation import (
    DEFAULT_MAX_DELIBERATIONS,
    DEFAULT_VOICES,
    LEDGER_FILENAME,
    MIN_QUESTION_CHARS,
    REQUEST_FILENAME,
    CruxPanel,
    CruxRequest,
    Position,
    Resolution,
    apply_voice_models,
    clear_requests,
    escalation_offer,
    format_resolution_for_prompt,
    parse_requests,
    read_requests,
    record_resolution,
    resolve_voices,
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


STAGE_03 = next(stage for stage in STAGES if stage.slug == "03_study_design")

_QUESTION = (
    "Should identification rely on the 2019 policy discontinuity or on household fixed effects?"
)
_WORKING = "Use household fixed effects, because the discontinuity sample is too small."
_DIFFERENT = "Use the 2019 discontinuity and report fixed effects only as a robustness check."


def _request(**overrides) -> dict:
    base = {
        "question": _QUESTION,
        "why_it_matters": "Every downstream estimate inherits this choice.",
        "already_considered": ["Matching on pre-period covariates, rejected for lack of overlap."],
        "working_answer": _WORKING,
        "help_wanted": "both",
    }
    base.update(overrides)
    return base


class RequestTests(unittest.TestCase):
    def test_a_well_formed_request_parses(self) -> None:
        requests = parse_requests(_request(), stage=STAGE_03)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].stage_slug, STAGE_03.slug)
        self.assertEqual(requests[0].help_wanted, "both")
        self.assertEqual(len(requests[0].already_considered), 1)

    def test_a_list_of_requests_parses(self) -> None:
        self.assertEqual(len(parse_requests([_request(), _request()], stage=STAGE_03)), 2)

    def test_a_question_too_vague_to_answer_is_dropped(self) -> None:
        # "What should we do about the data?" has no answer; a panel asked it writes essays.
        self.assertLess(len("what about the data?"), MIN_QUESTION_CHARS)
        self.assertEqual(parse_requests(_request(question="what about the data?"), stage=STAGE_03), [])

    def test_an_unknown_help_kind_falls_back_to_both(self) -> None:
        self.assertEqual(parse_requests(_request(help_wanted="telepathy"), stage=STAGE_03)[0].help_wanted, "both")

    def test_malformed_input_costs_the_escalation_not_the_stage(self) -> None:
        self.assertEqual(parse_requests(None, stage=STAGE_03), [])
        self.assertEqual(parse_requests(["not a dict"], stage=STAGE_03), [])
        self.assertEqual(parse_requests({}, stage=STAGE_03), [])

    def test_requests_round_trip_through_the_file(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.notes_dir / REQUEST_FILENAME, json.dumps(_request()))

        self.assertEqual(len(read_requests(paths, STAGE_03)), 1)
        clear_requests(paths)
        # Consumed, so the same crux is never deliberated twice.
        self.assertEqual(read_requests(paths, STAGE_03), [])

    def test_a_corrupt_request_file_reads_as_no_request(self) -> None:
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        write_text(paths.notes_dir / REQUEST_FILENAME, "{ not json")
        self.assertEqual(read_requests(paths, STAGE_03), [])


class OfferTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        return paths

    def test_the_offer_says_most_steps_are_just_execution(self) -> None:
        offer = escalation_offer(self._paths(), budget_left=3)
        self.assertIn("Most of this stage is execution", offer)
        self.assertIn(REQUEST_FILENAME, offer)
        self.assertIn("you are not blocked", offer)

    def test_the_offer_states_the_remaining_budget(self) -> None:
        self.assertIn("2 more", escalation_offer(self._paths(), budget_left=2))

    def test_a_spent_budget_withdraws_the_offer(self) -> None:
        offer = escalation_offer(self._paths(), budget_left=0)
        self.assertIn("spent its deliberation budget", offer)
        self.assertNotIn(REQUEST_FILENAME, offer)


class VoiceTests(unittest.TestCase):
    def test_the_default_voices_have_distinct_angles(self) -> None:
        self.assertEqual(len(DEFAULT_VOICES), 4)
        self.assertEqual(len({voice.charter for voice in DEFAULT_VOICES}), 4)

    def test_a_subset_keeps_order_and_an_unknown_voice_is_refused(self) -> None:
        self.assertEqual([v.key for v in resolve_voices(["critic", "theorist"])], ["critic", "theorist"])
        with self.assertRaises(ValueError):
            resolve_voices(["oracle"])

    def test_models_can_be_assigned_per_voice(self) -> None:
        voices = apply_voice_models(DEFAULT_VOICES, ["critic=opus", "theorist=codex:default"])
        by_key = {voice.key: voice for voice in voices}
        self.assertEqual(by_key["critic"].model, "opus")
        self.assertEqual((by_key["theorist"].backend, by_key["theorist"].model), ("codex", "default"))

    def test_a_malformed_assignment_is_refused(self) -> None:
        for bad in ("critic", "critic=", "nobody=opus"):
            with self.assertRaises(ValueError, msg=bad):
                apply_voice_models(DEFAULT_VOICES, [bad])


class _ScriptedPanel:
    """A crux panel whose voices answer from a script."""

    def __init__(self, testcase: unittest.TestCase, script: dict[str, object], **kwargs):
        tmp_dir = tempfile.TemporaryDirectory()
        testcase.addCleanup(tmp_dir.cleanup)
        self.paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "Goal")
        write_text(self.paths.memory, "# Approved Run Memory\n")
        ensure_run_config(self.paths, model="sonnet", venue="neurips_2025")
        self.labels: list[str] = []

        self.panel = CruxPanel(
            kwargs.pop("voices", DEFAULT_VOICES),
            backend_name="claude", model="sonnet",
            ui=TerminalUI(output_stream=io.StringIO(), interactive=False),
            **kwargs,
        )

        def make(key):
            def run_prompt(*, paths, stage, attempt_no, prompt, label, watch=None):
                self.labels.append(label)
                if label == "crux_brief":
                    return 0, str(script.get("__brief__", "Standard practice is contested.")), ""
                if label == "crux_resolve":
                    response = script.get("__resolve__")
                    if response == "__FAIL__":
                        return 1, "", "boom"
                    return 0, json.dumps(response), ""
                response = script.get(key)
                if response == "__FAIL__":
                    return 1, "", "boom"
                return 0, json.dumps(response if response is not None else {"answer": f"{key} says X"}), ""
            return run_prompt

        for voice in self.panel.voices:
            self.panel._members[voice.key].run_prompt = make(voice.key)

    def run(self, **overrides) -> Resolution | None:
        return self.panel.deliberate(
            paths=self.paths, stage=STAGE_03, attempt_no=1,
            request=parse_requests(_request(**overrides), stage=STAGE_03)[0],
        )


class DeliberationTests(unittest.TestCase):
    def _script(self, resolve_answer: str = _DIFFERENT) -> dict[str, object]:
        return {
            "theorist": {"answer": _DIFFERENT, "argument": "The discontinuity identifies the estimand.",
                         "against_self": "The bandwidth choice is arbitrary."},
            "empiricist": {"answer": _WORKING, "argument": "n is too small at the cutoff."},
            "critic": {"answer": _DIFFERENT, "argument": "Fixed effects leave time-varying confounds."},
            "pragmatist": {"answer": _DIFFERENT, "argument": "Both are affordable."},
            "__resolve__": {"answer": resolve_answer, "reason": "Weight of argument.",
                            "falsifier": "If the cutoff sample is under 200, revert.",
                            "dissent": "The empiricist's precision objection stands."},
        }

    def test_every_voice_is_heard_and_the_crux_resolves(self) -> None:
        harness = _ScriptedPanel(self, self._script())
        resolution = harness.run()
        assert resolution is not None
        self.assertEqual(len(resolution.positions), 4)
        self.assertEqual(resolution.answer, _DIFFERENT)
        self.assertEqual(resolution.falsifier, "If the cutoff sample is under 200, revert.")
        self.assertEqual(resolution.dissent, "The empiricist's precision objection stands.")

    def test_expertise_is_gathered_before_anyone_opines(self) -> None:
        harness = _ScriptedPanel(self, self._script())
        harness.run(help_wanted="both")
        # Opinions arrive faster than evidence, so the brief goes first.
        self.assertEqual(harness.labels[0], "crux_brief")

    def test_asking_only_for_perspectives_skips_the_brief(self) -> None:
        harness = _ScriptedPanel(self, self._script())
        harness.run(help_wanted="perspectives")
        self.assertNotIn("crux_brief", harness.labels)

    def test_a_resolution_that_differs_from_the_agent_is_flagged(self) -> None:
        resolution = _ScriptedPanel(self, self._script(_DIFFERENT)).run()
        assert resolution is not None
        self.assertIs(resolution.changed_the_answer, True)
        self.assertIn("different answer", resolution.verdict())

    def test_a_resolution_that_confirms_the_agent_says_so(self) -> None:
        resolution = _ScriptedPanel(self, self._script(_WORKING)).run()
        assert resolution is not None
        self.assertIs(resolution.changed_the_answer, False)
        self.assertIn("did not need escalating", resolution.verdict())

    def test_distinct_positions_are_counted_not_just_voices(self) -> None:
        script = self._script()
        # Three voices give the same answer; that is one position, not three.
        script["pragmatist"] = {"answer": _DIFFERENT}
        script["critic"] = {"answer": _DIFFERENT}
        resolution = _ScriptedPanel(self, script).run()
        assert resolution is not None
        self.assertEqual(resolution.distinct_answers, 2)

    def test_an_unreachable_voice_does_not_stop_the_deliberation(self) -> None:
        script = self._script()
        script["critic"] = "__FAIL__"
        resolution = _ScriptedPanel(self, script).run()
        assert resolution is not None
        self.assertTrue(any(position.failed for position in resolution.positions))
        self.assertEqual(resolution.answer, _DIFFERENT)

    def test_a_failed_resolution_leaves_no_answer(self) -> None:
        script = self._script()
        script["__resolve__"] = "__FAIL__"
        resolution = _ScriptedPanel(self, script).run()
        assert resolution is not None
        self.assertEqual(resolution.answer, "")
        self.assertIn("no answer", resolution.verdict())

    def test_fake_mode_never_deliberates(self) -> None:
        self.assertIsNone(_ScriptedPanel(self, {}, fake_mode=True).run())

    def test_an_empty_roster_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            CruxPanel((), backend_name="claude", model="sonnet")


class BudgetTests(unittest.TestCase):
    """Scarcity is what makes 'think hard here' mean anything."""

    def _script(self) -> dict[str, object]:
        return {"__resolve__": {"answer": _DIFFERENT, "reason": "r", "falsifier": "f", "dissent": "d"}}

    def test_the_budget_is_spent_down_and_then_refuses(self) -> None:
        harness = _ScriptedPanel(self, self._script(), max_deliberations=2)
        self.assertEqual(harness.panel.budget_left, 2)
        self.assertIsNotNone(harness.run())
        self.assertIsNotNone(harness.run())
        self.assertEqual(harness.panel.budget_left, 0)
        # An agent that can escalate everything has prioritised nothing.
        self.assertIsNone(harness.run())

    def test_a_zero_budget_never_deliberates(self) -> None:
        harness = _ScriptedPanel(self, self._script(), max_deliberations=0)
        self.assertIsNone(harness.run())
        self.assertEqual(harness.labels, [])

    def test_the_default_budget_is_small(self) -> None:
        self.assertLessEqual(DEFAULT_MAX_DELIBERATIONS, 5)


class LedgerTests(unittest.TestCase):
    def _paths(self):
        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        paths = build_run_paths(Path(tmp_dir.name) / "run")
        ensure_run_layout(paths)
        return paths

    def _resolution(self, changed: bool | None) -> Resolution:
        return Resolution(
            request=parse_requests(_request(), stage=STAGE_03)[0],
            positions=[Position(voice="theorist", title="Theorist", backend="claude",
                                model="sonnet", answer=_DIFFERENT)],
            answer=_DIFFERENT, reason="r", falsifier="f", dissent="d",
            voice_calls=5, changed_the_answer=changed,
        )

    def test_a_resolution_is_recorded_with_its_positions(self) -> None:
        paths = self._paths()
        record_resolution(paths, STAGE_03, self._resolution(True))
        payload = json.loads(read_text(paths.reviews_dir / LEDGER_FILENAME))
        self.assertEqual(payload["summary"]["cruxes_raised"], 1)
        self.assertEqual(payload["summary"]["changed_the_agents_answer"], 1)
        self.assertEqual(len(payload["deliberations"][0]["positions"]), 1)

    def test_escalations_that_only_confirmed_the_agent_are_called_out(self) -> None:
        paths = self._paths()
        record_resolution(paths, STAGE_03, self._resolution(False))
        record_resolution(paths, STAGE_03, self._resolution(False))
        summary = json.loads(read_text(paths.reviews_dir / LEDGER_FILENAME))["summary"]
        self.assertEqual(summary["confirmed_the_agents_answer"], 2)
        self.assertIn("stopping to think changed nothing", summary["verdict"])

    def test_the_verdict_reaches_the_run_log(self) -> None:
        paths = self._paths()
        record_resolution(paths, STAGE_03, self._resolution(True))
        self.assertIn("crux_deliberation", read_text(paths.logs))

    def test_a_corrupt_ledger_is_replaced_rather_than_crashing(self) -> None:
        paths = self._paths()
        paths.reviews_dir.mkdir(parents=True, exist_ok=True)
        write_text(paths.reviews_dir / LEDGER_FILENAME, "{ not json")
        record_resolution(paths, STAGE_03, self._resolution(True))
        self.assertEqual(len(json.loads(read_text(paths.reviews_dir / LEDGER_FILENAME))["deliberations"]), 1)


class HandbackTests(unittest.TestCase):
    def _resolution(self) -> Resolution:
        return Resolution(
            request=parse_requests(_request(), stage=STAGE_03)[0],
            answer=_DIFFERENT, reason="Weight of argument.",
            falsifier="If the cutoff sample is under 200, revert.",
            dissent="The precision objection stands.",
        )

    def test_the_stage_gets_the_answer_its_reason_and_its_falsifier(self) -> None:
        rendered = format_resolution_for_prompt([self._resolution()])
        self.assertIn(_QUESTION, rendered)
        self.assertIn(_DIFFERENT, rendered)
        self.assertIn("What would change this", rendered)
        self.assertIn("Surviving dissent", rendered)

    def test_the_answer_is_a_conclusion_not_an_order(self) -> None:
        # A resolution the stage cannot argue with is a manager, not a colleague.
        self.assertIn("not orders", format_resolution_for_prompt([self._resolution()]))

    def test_no_resolutions_render_nothing(self) -> None:
        self.assertEqual(format_resolution_for_prompt([]), "")

    def test_an_unresolved_crux_tells_the_stage_to_keep_its_own(self) -> None:
        unresolved = Resolution(request=parse_requests(_request(), stage=STAGE_03)[0])
        self.assertIn("keep your own", format_resolution_for_prompt([unresolved]))


class ManagerIntegrationTests(unittest.TestCase):
    def _manager_and_paths(self, **panel_kwargs):
        from unittest.mock import MagicMock
        from src.manager import ResearchManager

        tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_dir.cleanup)
        runs_dir = Path(tmp_dir.name) / "runs"
        runs_dir.mkdir()
        paths = build_run_paths(runs_dir / "20260101_000000")
        ensure_run_layout(paths)
        write_text(paths.user_input, "Goal")
        write_text(paths.memory, "# Approved Run Memory\n")
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
        harness = _ScriptedPanel(self, {
            "__resolve__": {"answer": _DIFFERENT, "reason": "r", "falsifier": "f", "dissent": "d"},
        }, **panel_kwargs)
        harness.paths = paths
        manager.crux_panel = harness.panel
        return manager, paths

    def test_a_raised_crux_sends_the_stage_back_with_the_answer(self) -> None:
        manager, paths = self._manager_and_paths()
        write_text(paths.notes_dir / REQUEST_FILENAME, json.dumps(_request()))

        feedback = manager._settle_cruxes(paths, STAGE_03, 1)

        self.assertIsNotNone(feedback)
        assert feedback is not None
        self.assertIn("Resolved Cruxes", feedback)
        self.assertEqual(len(manager._crux_resolutions), 1)
        # Consumed, so the next attempt does not re-deliberate the same crux.
        self.assertFalse((paths.notes_dir / REQUEST_FILENAME).exists())
        self.assertTrue((paths.reviews_dir / LEDGER_FILENAME).exists())

    def test_no_request_means_the_stage_proceeds_untouched(self) -> None:
        manager, paths = self._manager_and_paths()
        self.assertIsNone(manager._settle_cruxes(paths, STAGE_03, 1))

    def test_no_panel_means_the_feature_is_absent(self) -> None:
        manager, paths = self._manager_and_paths()
        manager.crux_panel = None
        write_text(paths.notes_dir / REQUEST_FILENAME, json.dumps(_request()))
        self.assertIsNone(manager._settle_cruxes(paths, STAGE_03, 1))
        # The request is left alone rather than silently eaten.
        self.assertTrue((paths.notes_dir / REQUEST_FILENAME).exists())

    def test_a_spent_budget_refuses_rather_than_stranding_the_stage(self) -> None:
        manager, paths = self._manager_and_paths(max_deliberations=0)
        write_text(paths.notes_dir / REQUEST_FILENAME, json.dumps(_request()))
        self.assertIsNone(manager._settle_cruxes(paths, STAGE_03, 1))
        self.assertIn("crux_budget_spent", read_text(paths.logs))

    def test_a_panel_that_throws_cannot_strand_a_usable_draft(self) -> None:
        manager, paths = self._manager_and_paths()

        def explode(**_kwargs):
            raise RuntimeError("panel is down")

        manager.crux_panel.deliberate = explode
        write_text(paths.notes_dir / REQUEST_FILENAME, json.dumps(_request()))

        self.assertIsNone(manager._settle_cruxes(paths, STAGE_03, 1))
        self.assertIn("panel is down", read_text(paths.logs))


if __name__ == "__main__":
    unittest.main()
