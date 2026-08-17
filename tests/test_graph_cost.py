"""Replay cost: what a backward move discards, derived rather than tabulated.

Two backward moves out of Stage 07 differ by 3.5x in the work they throw away —
`07 -> 01` discards seven stages, `07 -> 06` discards two — and the router
presented them identically. Cost is now on the menu.

The tests hold two properties. First, the cost is *derived from the stage
ordering*: a per-edge constant sitting beside a derivable one is where drift
starts, and this repo has already been bitten by hand-copied constants that were
stale. Second, cost is shown as information, not as a reason to be thrifty — a
correct expensive correction beats a wrong cheap one, and a router that shops on
price writes up around the flaw it should have gone back for. The second property
grew a balance to weigh the price against; ``tests/test_router_budget.py`` holds
that half, and the two assertions here keep both halves of the sentence at once.
"""

from __future__ import annotations

import unittest

from src.stage_graph import (
    FINISH,
    REVISIT_EDGES,
    GraphState,
    StageGraph,
    WalkBudget,
    _advance_edges,
    replay_cost,
)
from src.utils import STAGES


ORDER = [stage.slug for stage in STAGES]


class ReplayCostTest(unittest.TestCase):
    def test_a_forward_move_discards_nothing(self) -> None:
        for edge in _advance_edges(guarded=True):
            with self.subTest(edge=f"{edge.source}->{edge.target}"):
                self.assertEqual(replay_cost(edge.source, edge.target), 0)

    def test_a_backward_move_costs_the_stages_it_throws_away(self) -> None:
        self.assertEqual(replay_cost("07_writing", "06_analysis"), 2)
        self.assertEqual(replay_cost("07_writing", "01_literature_survey"), 7)
        self.assertEqual(replay_cost("02_hypothesis_generation", "01_literature_survey"), 2)

    def test_finishing_costs_nothing(self) -> None:
        self.assertEqual(replay_cost("08_dissemination", FINISH), 0)

    def test_every_declared_backward_edge_has_a_positive_cost(self) -> None:
        for edge in REVISIT_EDGES:
            with self.subTest(edge=f"{edge.source}->{edge.target}"):
                self.assertGreater(replay_cost(edge.source, edge.target), 0)

    def test_the_cost_is_derived_from_the_ordering_not_stored(self) -> None:
        """Insert a stage and the costs must move with it.

        This is the property that a hand-written table cannot have. If someone
        later replaces the derivation with a literal, this fails.
        """
        import src.stage_graph as graph_module
        from src.utils import StageSpec

        original = graph_module.STAGES
        before = replay_cost("07_writing", "01_literature_survey")
        try:
            extended = list(original)
            extended.insert(1, StageSpec(99, "01b_interlude", "Interlude"))
            graph_module.STAGES = extended
            after = replay_cost("07_writing", "01_literature_survey")
        finally:
            graph_module.STAGES = original
        self.assertEqual(before, 7)
        self.assertEqual(after, 8, "cost did not follow the topology; is it tabulated?")

    def test_an_unknown_stage_does_not_raise(self) -> None:
        self.assertEqual(replay_cost("99_nonexistent", "01_literature_survey"), 0)


class CostOnTheMenuTest(unittest.TestCase):
    def test_the_move_table_has_a_discards_column(self) -> None:
        graph = StageGraph.named("adaptive")
        rendered = graph.describe_for_prompt([], WalkBudget.of(GraphState(), "06_analysis"))
        self.assertIn("Discards", rendered)

    def test_the_router_says_cost_is_not_a_reason_to_be_cheap(self) -> None:
        """A router that optimises for thrift routes badly."""
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / "src" / "router.py").read_text(encoding="utf-8")
        self.assertIn("**Discards**", text, "the router never explains the column")
        self.assertIn("correct expensive", text)
        self.assertIn("break a tie", text)

    def test_it_no_longer_says_that_without_saying_what_is_left(self) -> None:
        """The other half of the same sentence, and the half that was false.

        "A correct expensive correction beats a wrong cheap one" was addressed to an
        agent with no idea what it had left to spend, and the paragraph went on to tell
        it not to look. Keeping only the first assertion above would let the paragraph
        revert to that: it is the sentence the reverted version also contains.
        """
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / "src" / "router.py").read_text(encoding="utf-8")
        self.assertIn("afford to finish", text, "cost is weighed against nothing")
        self.assertNotIn(
            "Use it only to break a tie",
            text,
            "the column is still presented as tie-break-only, with no balance beside it",
        )


class NewBackwardEdgesTest(unittest.TestCase):
    """The cheap early corrections that were missing while expensive late ones existed."""

    def setUp(self) -> None:
        self.edges = {(edge.source, edge.target): edge for edge in REVISIT_EDGES}

    def test_hypothesis_generation_can_reopen_the_survey(self) -> None:
        self.assertIn(("02_hypothesis_generation", "01_literature_survey"), self.edges)

    def test_study_design_can_send_a_hypothesis_back(self) -> None:
        self.assertIn(("03_study_design", "02_hypothesis_generation"), self.edges)

    def test_analysis_can_reach_the_implementation(self) -> None:
        self.assertIn(("06_analysis", "04_implementation"), self.edges)

    def test_the_cheapest_route_to_a_stage_is_never_dearer_than_the_dearest(self) -> None:
        """The inversion this fixed: 07->01 existed at cost 7 while 02->01 did not exist.

        For every target that any backward edge reaches, there must be an edge
        into it from the *nearest* source that can plausibly discover the
        problem — otherwise the only way back is the expensive one.
        """
        into: dict[str, list[int]] = {}
        for edge in REVISIT_EDGES:
            into.setdefault(edge.target, []).append(replay_cost(edge.source, edge.target))
        for target, costs in sorted(into.items()):
            with self.subTest(target=target):
                self.assertLessEqual(
                    min(costs),
                    3,
                    f"the cheapest way back to {target} costs {min(costs)} stages; "
                    "a late expensive correction is the only route",
                )

    def test_no_edge_ships_without_a_rationale(self) -> None:
        """Only what is mechanically checkable.

        Two earlier versions of this test asserted a minimum length and then a
        keyword list, and both rejected rationales that are simply good:
        "Packaging it showed the deliverable is not what a reader would need"
        is 68 characters, and "The finding turns out to relate to work the
        survey missed" names a discovery without using any of the words I had
        guessed. Whether a rationale is well written is a review question, not
        a test one. What a test can hold is that the field is not a
        placeholder.
        """
        for edge in REVISIT_EDGES:
            with self.subTest(edge=f"{edge.source}->{edge.target}"):
                rationale = edge.rationale.strip()
                self.assertGreater(len(rationale), 40, rationale)
                self.assertNotIn("TODO", rationale)


class DefaultTopologyUnchangedTest(unittest.TestCase):
    """Adding edges must not change what a plain run does."""

    def test_the_linear_topology_has_no_backward_edges(self) -> None:
        linear = StageGraph.named("linear")
        self.assertEqual([e for e in linear.edges if e.kind == "revisit"], [])

    def test_the_forward_spine_is_still_one_edge_per_stage(self) -> None:
        forward = [e for e in StageGraph.named("adaptive").edges if e.kind == "advance"]
        sources = [e.source for e in forward]
        self.assertEqual(len(sources), len(set(sources)), "a stage has two forward edges")


if __name__ == "__main__":
    unittest.main()
