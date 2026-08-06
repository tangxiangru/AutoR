"""Routing: the agent proposes, the graph disposes.

Everything here is about the disagreement path. When the backend picks a live move
and explains itself, there is nothing to test but a passthrough. The design lives
in what happens when it picks a blocked move, picks a move that does not exist,
picks without a reason, or asks to go back somewhere it has already been for the
same reason — and in the guarantee that every one of those degrades to the forward
edge rather than to a stall.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.router import ROUTING_MODES, RoutingDecision, StageRouter, format_decision, routing_summary
from src.stage_graph import FINISH, GraphState, StageGraph, Visit, enter, leave
from src.utils import STAGES, build_run_paths, ensure_run_layout, read_text, write_text
from tests import prereg_support


STAGE_06 = next(stage for stage in STAGES if stage.number == 6)


class FakeRoutingOperator:
    """Stands in for a backend CLI at the two private seams the router uses.

    Serving the boundary rather than stubbing `StageRouter._ask` keeps the prompt
    construction, the JSON recovery and the exit-code handling under test; a stub
    at the method would assert only that the fake was called.
    """

    fake_mode = False

    def __init__(self, response: str, *, exit_code: int = 0) -> None:
        self.response = response
        self.exit_code = exit_code
        self.prompts: list[str] = []

    def _prepare_invocation(self, prompt_path, session_id, *, paths, resume):
        self.prompts.append(read_text(prompt_path))
        return (["fake-backend"], paths.run_root, None)

    def _run_streaming_command(self, *, command, cwd, stage, attempt_no, paths, mode, stdin_text):
        return (self.exit_code, self.response, "", session_placeholder := None, {})


class RouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.stage_file(STAGE_06), "# Stage 06: Analysis\n\nBody.\n")
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        write_text(self.paths.results_dir / "metrics.json", json.dumps({"acc": 0.7}))
        write_text(
            self.paths.experiment_manifest, json.dumps({"experiments": [{"id": "e1"}]})
        )
        self.graph = StageGraph.adaptive()

    def choose(self, response: str, *, state: GraphState | None = None, mode: str = "agent"):
        operator = FakeRoutingOperator(response)
        router = StageRouter(operator, mode=mode)
        decision = router.choose(
            paths=self.paths,
            stage=STAGE_06,
            graph=self.graph,
            state=state or GraphState(),
        )
        return decision, operator

    # -- the agreement path --------------------------------------------------

    def test_a_live_move_with_a_reason_is_taken(self) -> None:
        decision, _ = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "H1 rests on a single seed."})
        )
        self.assertEqual(decision.target, "05_experimentation")
        self.assertEqual(decision.kind, "revisit")
        self.assertTrue(decision.agent_directed)
        self.assertEqual(decision.refusal, "")

    def test_the_default_is_recorded_even_when_the_agent_agrees(self) -> None:
        """An agreement is evidence about the topology too. Without both on record
        the archive cannot tell a confirmed default from a default nobody was asked
        about."""
        self.adjudicate()
        decision, _ = self.choose(
            json.dumps({"target": "07_writing", "reason": "Everything is adjudicated."})
        )
        self.assertEqual(decision.target, "07_writing")
        self.assertEqual(decision.default_target, "07_writing")
        self.assertTrue(decision.agent_directed)

    def adjudicate(self) -> None:
        """Open the writing edge: frozen hypotheses, a verdict on each, a figure."""
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        write_text(self.paths.figures_dir / "fig.png", "x" * 64)
        prereg = json.loads(self.paths.preregistration.read_text(encoding="utf-8"))
        write_text(
            self.paths.hypothesis_outcomes,
            json.dumps(
                {
                    "preregistration_digest": prereg["digest"],
                    "outcomes": [
                        {
                            "id": prereg_support.HYPOTHESIS_ID,
                            "verdict": "refuted",
                            "rationale": "The gap did not clear the rule.",
                            "evidence": ["results/metrics.json"],
                        }
                    ],
                }
            ),
        )

    # -- refusals ------------------------------------------------------------

    def test_a_blocked_move_is_refused_even_when_the_fallback_goes_there_anyway(self) -> None:
        """Writing is closed until the hypotheses are adjudicated, and an agent asked
        where to go next reaches for the deliverable.

        The run still ends up at Stage 07, because the default is always the forward
        edge and taking it with the precondition unmet beats halting with nothing —
        the stage's own validation is the correctness gate and will refuse a write-up
        of unadjudicated hypotheses. What must not survive is the *attribution*: this
        was not the agent's decision, the refusal is on the record with the reason,
        and the route says the precondition was unmet. Otherwise the archive later
        learns from a step labelled as a considered choice that was nothing of the
        kind.
        """
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        decision, _ = self.choose(
            json.dumps({"target": "07_writing", "reason": "The results look conclusive."})
        )
        self.assertFalse(decision.agent_directed)
        self.assertIn("07_writing", decision.refusal)
        self.assertIn(prereg_support.HYPOTHESIS_ID, decision.refusal)

    def test_a_default_taken_with_its_guard_failing_says_so_on_the_route(self) -> None:
        """A step recorded as an ordinary advance when its precondition was unmet is
        a mislabelled observation, and the archive learns from these."""
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        decision = StageRouter(None, mode="off").choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=GraphState()
        )
        self.assertEqual(decision.target, "07_writing")
        self.assertIn("precondition unmet", decision.reason)
        self.assertIn(prereg_support.HYPOTHESIS_ID, decision.reason)

    def test_a_move_that_does_not_exist_is_refused(self) -> None:
        decision, _ = self.choose(json.dumps({"target": "04_implementation", "reason": "Rebuild."}))
        self.assertFalse(decision.agent_directed)
        self.assertIn("not a move", decision.refusal)

    def test_a_choice_with_no_reason_is_refused(self) -> None:
        decision, _ = self.choose(json.dumps({"target": "05_experimentation", "reason": "   "}))
        self.assertFalse(decision.agent_directed)
        self.assertIn("no stated reason", decision.refusal)

    def test_going_back_for_the_same_reason_twice_is_refused(self) -> None:
        state = GraphState(
            path=[
                Visit(
                    stage="06_analysis",
                    entered_at="t",
                    chose="05_experimentation",
                    kind="revisit",
                    reason="Only one seed was run.",
                )
            ]
        )
        decision, _ = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "only one seed was run."}),
            state=state,
        )
        self.assertFalse(decision.agent_directed)
        self.assertIn("same reason", decision.refusal)

    def test_going_back_for_a_different_reason_is_allowed(self) -> None:
        state = GraphState(
            path=[
                Visit(
                    stage="06_analysis",
                    entered_at="t",
                    chose="05_experimentation",
                    kind="revisit",
                    reason="Only one seed was run.",
                )
            ]
        )
        decision, _ = self.choose(
            json.dumps(
                {"target": "05_experimentation", "reason": "The ablation condition was never run."}
            ),
            state=state,
        )
        self.assertTrue(decision.agent_directed)

    def test_unreadable_output_falls_forward_rather_than_stalling(self) -> None:
        decision, _ = self.choose("I think we should probably continue to the next stage.")
        self.assertFalse(decision.agent_directed)
        self.assertIn("no readable decision", decision.refusal)

    def test_a_backend_that_exits_nonzero_does_not_end_the_run(self) -> None:
        operator = FakeRoutingOperator("", exit_code=3)
        decision = StageRouter(operator, mode="agent").choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=GraphState()
        )
        self.assertFalse(decision.agent_directed)
        self.assertTrue(decision.target)

    def test_every_refusal_is_written_where_it_can_be_read_later(self) -> None:
        self.choose(json.dumps({"target": "04_implementation", "reason": "Rebuild."}))
        rows = [
            json.loads(line)
            for line in read_text(self.paths.evolution_dir / "routing_refusals.jsonl").splitlines()
            if line.strip()
        ]
        self.assertEqual(rows[-1]["stage"], STAGE_06.slug)
        self.assertTrue(rows[-1]["fell_back_to"])

    def test_the_agent_cannot_decline_the_run_s_own_abandonment(self) -> None:
        """Making the terminal the *default* is not enough, and this is why.

        The default is only what happens when nobody is asked, and `auto` — the
        shipped default — asks wherever more than one move is live. Measured before
        this rule existed: a run whose round concluded the question cannot be
        answered still offered five live moves at Stage 06, so the backend was
        consulted, and a backend answering "the refutation is the contribution" got
        `07_writing` with `agent_directed=True` and no refusal. The run talked itself
        out of its own finding.

        A person may still overrule it — `/back` and `--rollback-stage` do not go
        through the router at all.
        """
        self.adjudicate()
        self.abandon()
        operator = FakeRoutingOperator(
            json.dumps({"target": "07_writing", "reason": "The refutation is the contribution."})
        )
        decision = StageRouter(operator, mode="auto").choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=GraphState()
        )
        self.assertEqual(decision.target, FINISH)
        self.assertFalse(decision.agent_directed)
        self.assertEqual(operator.prompts, [], msg="the backend was asked about a settled question")

    def test_every_other_move_is_recorded_as_moot_rather_than_guard_blocked(self) -> None:
        """An estimator must be able to tell "this was shut by a research condition"
        from "the run had already stopped"."""
        self.adjudicate()
        self.abandon()
        decision = StageRouter(None, mode="off").choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=GraphState()
        )
        self.assertEqual(set(decision.blocked.values()), {"concluded"})
        self.assertIn("07_writing", decision.blocked)

    def abandon(self) -> None:
        from src.research_rounds import record_round

        write_text(
            self.paths.round_decision,
            json.dumps(
                {
                    "decision": "abandon",
                    "rationale": "The effect cannot be separated from tuning noise here.",
                    "what_we_learned": "Every arm we can afford sits within noise of baseline.",
                    "what_changes_next": "",
                    "negative_result": False,
                }
            ),
        )
        record_round(self.paths, acted_on=True)

    # -- when to ask ---------------------------------------------------------

    def test_off_never_asks(self) -> None:
        decision, operator = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "H1 rests on one seed."}),
            mode="off",
        )
        self.assertEqual(operator.prompts, [])
        self.assertFalse(decision.agent_directed)

    def test_auto_does_not_ask_where_there_is_only_one_move(self) -> None:
        """On a linear graph `auto` costs nothing, which is what makes it a safe
        default for someone turning routing on for the first time."""
        operator = FakeRoutingOperator(json.dumps({"target": FINISH, "reason": "done"}))
        StageRouter(operator, mode="auto").choose(
            paths=self.paths,
            stage=STAGE_06,
            graph=StageGraph.linear(),
            state=GraphState(),
        )
        self.assertEqual(operator.prompts, [])

    def test_auto_asks_where_the_answer_can_differ(self) -> None:
        operator = FakeRoutingOperator(
            json.dumps({"target": "05_experimentation", "reason": "H1 rests on one seed."})
        )
        StageRouter(operator, mode="auto").choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=GraphState()
        )
        self.assertEqual(len(operator.prompts), 1)

    def test_an_unknown_mode_is_refused_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            StageRouter(None, mode="vibes")
        self.assertEqual(set(ROUTING_MODES), {"off", "auto", "agent"})

    # -- the prompt ----------------------------------------------------------

    def test_the_prompt_shows_blocked_moves_with_the_reason_they_are_blocked(self) -> None:
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        _, operator = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "H1 rests on one seed."})
        )
        prompt = operator.prompts[0]
        self.assertIn("07_writing", prompt)
        self.assertIn(prereg_support.HYPOTHESIS_ID, prompt)

    # -- what the decision records -------------------------------------------

    def test_the_choice_set_is_recorded_on_the_accepted_path(self) -> None:
        """"This edge was taken" and "this edge was offered and taken" are different
        observations, and only the second can be a control arm."""
        self.adjudicate()
        decision, _ = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "H1 rests on one seed."})
        )
        self.assertIn("05_experimentation", decision.offered)
        self.assertIn("07_writing", decision.offered)
        # The abandonment terminal is on the record as shut. That is the useful
        # state to capture: an estimator has to be able to tell "the run could have
        # stopped and did not" from "stopping was never on the table".
        self.assertEqual(decision.blocked, {"finish": "guard"})
        self.assertNotIn("finish", decision.offered)

    def test_the_choice_set_is_recorded_on_the_refusal_path_too(self) -> None:
        """A refusal is still an observation of what was on the table. Recording it
        with an empty choice set would make it indistinguishable from a jump, which
        genuinely had none."""
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        decision, _ = self.choose(json.dumps({"target": "04_implementation", "reason": "Rebuild."}))
        self.assertTrue(decision.refusal)
        self.assertIn("05_experimentation", decision.offered)
        self.assertEqual(decision.blocked.get("07_writing"), "guard")

    def test_a_blocked_target_records_which_kind_of_block(self) -> None:
        """The kind is the discriminator: a guard is a statement about the research
        and a budget is a statement about the run, and an estimator that cannot tell
        them apart is pooling two different reasons for not taking an edge."""
        prereg_support.write_hypothesis_manifest(self.paths)
        prereg_support.freeze_preregistration(self.paths)
        decision, _ = self.choose(
            json.dumps({"target": "05_experimentation", "reason": "one seed"})
        )
        self.assertEqual(set(decision.blocked.values()) - {"guard", "visits", "steps"}, set())
        self.assertEqual(decision.blocked["07_writing"], "guard")

    # -- reporting -----------------------------------------------------------

    def test_the_summary_counts_edges_rather_than_stages(self) -> None:
        """The same target reached from two sources is two different decisions."""
        state = GraphState()
        enter(self.paths, state, STAGE_06)
        leave(
            self.paths,
            state,
            chose="05_experimentation",
            kind="revisit",
            reason="thin",
            default_choice="07_writing",
            agent_directed=True,
            score_total=0.6,
        )
        summary = routing_summary(self.paths)
        self.assertEqual(summary["edges"], {"06_analysis->05_experimentation": 1})
        self.assertEqual(summary["revisits"], 1)
        self.assertEqual(summary["agent_directed"], 1)

    def test_the_terminal_line_says_who_chose(self) -> None:
        self.assertIn("agent", format_decision(RoutingDecision("07_writing", "advance", "r", "07_writing", True)))
        self.assertIn(
            "refused",
            format_decision(RoutingDecision("07_writing", "advance", "r", "07_writing", False, "nope")),
        )


if __name__ == "__main__":
    unittest.main()
