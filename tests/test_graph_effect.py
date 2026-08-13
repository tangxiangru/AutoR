"""What the adaptive graph bought over the linear pipeline inside it.

The graph is one of this project's two central claims and no run could say whether it had
done anything. Measured across twelve benchmark runs, with the verdict-parsing fix already
in so the router's answers actually arrive: 81 decision points, 74 agreements, 6 departures,
1 refusal. The freedom is real, it reaches the router, and the router declines it 91% of the
time. This file exists so a run states that itself instead of leaving the claim unmeasured.

Three ways to compute the rate wrongly, one field of `Visit` against each: `bypassed`
(operator interventions are not routing decisions), `offered` (a node with one live move is
not a choice), and `refusal` (an answer that was lost is not an agreement).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.stage_graph import (
    GraphState,
    Visit,
    effect_file,
    graph_effect,
    record_graph_effect,
    save_graph_state,
)
from src.utils import build_run_paths, ensure_run_layout


def visit(stage="01", *, offered=(), chose="", default="", refusal="", bypassed=False,
          blocked=None) -> Visit:
    return Visit(stage=stage, entered_at="t", offered=tuple(offered), chose=chose,
                 default_choice=default, refusal=refusal, bypassed=bypassed,
                 blocked=dict(blocked or {}), kind="advance", left_at="t")


def state(*visits: Visit) -> GraphState:
    s = GraphState()
    s.path = list(visits)
    return s


class DenominatorTest(unittest.TestCase):
    """A node without a real alternative is not a decision the graph made."""

    def test_a_single_live_move_is_not_a_decision_point(self) -> None:
        e = graph_effect(state(visit(offered=("02",), chose="02", default="02")))
        self.assertEqual(e["decision_points"], 0)
        self.assertEqual(e["nodes_with_one_live_move"], 1)
        self.assertIsNone(e["departure_rate"])

    def test_a_bypassed_move_is_not_a_decision_point(self) -> None:
        """A /back or a rollback had no choice set; counting it reads an operator as an edge."""
        e = graph_effect(state(visit(offered=("02", "03"), chose="03", bypassed=True)))
        self.assertEqual(e["decision_points"], 0)
        self.assertEqual(e["nodes_bypassing_the_router"], 1)

    def test_a_run_with_no_choices_says_it_is_not_evidence(self) -> None:
        e = graph_effect(state(visit(offered=("02",), chose="02", default="02")))
        self.assertIn("nothing here is evidence about it", e["verdict"])


class WhatTheRouterDidTest(unittest.TestCase):
    def test_agreeing_with_the_default_is_counted_as_agreement(self) -> None:
        e = graph_effect(state(visit(offered=("02", "05"), chose="02", default="02")))
        self.assertEqual((e["decision_points"], e["agreed_with_the_default"]), (1, 1))
        self.assertEqual(e["departed_from_the_default"], 0)

    def test_a_departure_is_counted_and_rated(self) -> None:
        e = graph_effect(state(
            visit(offered=("02", "05"), chose="05", default="02"),
            visit(offered=("03", "06"), chose="03", default="03"),
        ))
        self.assertEqual(e["departed_from_the_default"], 1)
        self.assertEqual(e["departure_rate"], 0.5)

    def test_a_refused_answer_is_not_an_agreement(self) -> None:
        """The difference between "the graph is not wanted" and "it reaches nobody"."""
        e = graph_effect(state(
            visit(offered=("02", "05"), chose="02", default="02", refusal="off-menu")
        ))
        self.assertEqual(e["answers_refused_or_lost"], 1)
        self.assertEqual(e["agreed_with_the_default"], 0)
        self.assertIn("routing channel, not about the topology", e["verdict"])

    def test_blocked_moves_are_tallied_by_kind(self) -> None:
        e = graph_effect(state(
            visit(offered=("02",), chose="02", blocked={"05": "guard", "07": "visits"}),
            visit(offered=("03",), chose="03", blocked={"06": "guard"}),
        ))
        self.assertEqual(e["moves_blocked_by"], {"guard": 2, "visits": 1})


class TheVerdictIsUnflatteringWhenTrueTest(unittest.TestCase):
    def test_a_purely_linear_run_says_so_in_words(self) -> None:
        """Nine of twelve benchmark runs looked exactly like this."""
        e = graph_effect(state(*[visit(offered=("02", "05"), chose="02", default="02")] * 6))
        self.assertIn("the graph was a linear pipeline", e["verdict"])

    def test_a_run_that_used_the_graph_reports_the_rate(self) -> None:
        e = graph_effect(state(
            visit(offered=("02", "05"), chose="05", default="02"),
            *[visit(offered=("03", "06"), chose="03", default="03")] * 3,
        ))
        self.assertIn("1 of 4", e["verdict"])
        self.assertIn("25%", e["verdict"])


class PersistenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run_0001")
        ensure_run_layout(self.paths)

    def test_saving_the_state_writes_the_effect_beside_it(self) -> None:
        save_graph_state(self.paths, state(visit(offered=("02", "05"), chose="05", default="02")))
        payload = json.loads(effect_file(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(payload["departed_from_the_default"], 1)

    def test_it_is_derived_not_accumulated_so_a_rollback_cannot_leave_a_stale_tally(self) -> None:
        record_graph_effect(self.paths, state(
            visit(offered=("02", "05"), chose="05", default="02"),
            visit(offered=("03", "06"), chose="06", default="03"),
        ))
        record_graph_effect(self.paths, state(visit(offered=("02", "05"), chose="02", default="02")))
        payload = json.loads(effect_file(self.paths).read_text(encoding="utf-8"))
        self.assertEqual(payload["departed_from_the_default"], 0)
        self.assertEqual(payload["decision_points"], 1)


if __name__ == "__main__":
    unittest.main()
