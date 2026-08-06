from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.archive import (
    RUBRIC_VERSION,
    Archive,
    RunRecord,
    edge_payoffs,
)
from src.stage_graph import Edge, StageGraph
from src.utils import append_jsonl


def _record(run_id: str, edges: list[str], fitness: float = 0.5) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges={edge: 1 for edge in edges},
        stage_fitness={"05_experimentation": fitness, "06_analysis": fitness},
        topology="adaptive",
        provenance="live",
        route="",
        steps=len(edges),
        revisits=0,
        agent_directed=0,
        recorded_at="2026-08-06T00:00:00",
    )


class ExplorableOnlyWithARivalTest(unittest.TestCase):
    """An edge with no rival at its source is not explorable.

    Preferring it changes nothing — a run reaching that node was going to take it
    anyway — so a proposal naming it buys a variant for a trial that cannot run.
    Held by its own test rather than as a side effect of the `linear` case, which
    only exercises it while `linear` happens to have a non-zero priority somewhere.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.archive = Archive(Path(self._tmp.name) / "archive")
        for index in range(5):
            append_jsonl(
                self.archive.runs_file,
                _record(f"r{index}", ["01_literature_survey->02_hypothesis_generation"]).to_dict(),
            )

    def _graph(self, edges):
        return StageGraph(edges, name="adaptive")

    def test_a_lone_untaken_advance_is_not_offered_for_exploration(self) -> None:
        graph = self._graph(
            [
                Edge("01_literature_survey", "02_hypothesis_generation", "advance", "on", priority=0),
                Edge("02_hypothesis_generation", "03_study_design", "advance", "on", priority=2),
            ]
        )
        self.assertIsNone(self.archive.propose_exploration(graph=graph))

    def test_an_untaken_edge_with_a_rival_is_offered(self) -> None:
        graph = self._graph(
            [
                Edge("01_literature_survey", "02_hypothesis_generation", "advance", "on", priority=0),
                Edge("02_hypothesis_generation", "03_study_design", "advance", "on", priority=0),
                Edge("02_hypothesis_generation", "01_literature_survey", "revisit", "back", priority=2),
            ]
        )
        variant = self.archive.propose_exploration(graph=graph)
        self.assertIsNotNone(variant)
        self.assertIn("02_hypothesis_generation->01_literature_survey", variant.edge_priority)

    def test_a_terminal_does_not_count_as_a_rival(self) -> None:
        """`06_analysis->finish` is live only when the round concluded the question
        cannot be answered, and in that case it is the only live forward move — so
        its priority relative to the writing edge decides nothing either."""
        graph = self._graph(
            [
                Edge("01_literature_survey", "02_hypothesis_generation", "advance", "on", priority=0),
                Edge("02_hypothesis_generation", "03_study_design", "advance", "on", priority=2),
                Edge("02_hypothesis_generation", "finish", "finish", "stop", guard="round_abandoned"),
            ]
        )
        self.assertIsNone(self.archive.propose_exploration(graph=graph))


class EdgeVisibilityTest(unittest.TestCase):
    """An edge nothing has taken must still be visible, or it cannot be reasoned about."""

    def test_an_untaken_edge_is_invisible_without_the_declared_set(self) -> None:
        payoffs = edge_payoffs([_record("r1", ["01_literature_survey->02_hypothesis_generation"], 0.5)])
        self.assertNotIn("06_analysis->05_experimentation", payoffs)

    def test_the_declared_set_makes_it_visible_with_zero_takers(self) -> None:
        payoffs = edge_payoffs(
            [_record("r1", ["01_literature_survey->02_hypothesis_generation"], 0.5)],
            known_edges=["06_analysis->05_experimentation"],
        )
        self.assertIn("06_analysis->05_experimentation", payoffs)
        self.assertEqual(payoffs["06_analysis->05_experimentation"].taken_runs, 0)

    def test_a_visible_untaken_edge_is_still_not_believable(self) -> None:
        """Visibility is not evidence. It must not become promotable by being seen."""
        payoffs = edge_payoffs([_record("r1", ["a->b"], 0.5)], known_edges=["x->y"])
        self.assertFalse(payoffs["x->y"].believable(min_observations=2))

    def test_taken_edges_are_unaffected_by_the_declared_set(self) -> None:
        records = [_record("r1", ["a->b"], 0.8), _record("r2", ["a->c"], 0.4)]
        without = edge_payoffs(records)
        with_declared = edge_payoffs(records, known_edges=["a->b", "a->c", "a->z"])
        self.assertEqual(without["a->b"].to_dict(), with_declared["a->b"].to_dict())


class ArchiveTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.archive = Archive(Path(self._tmp.name) / "archive", min_observations=2)
        self.graph = StageGraph.adaptive()

    def _add(self, run_id: str, edges: list[str], fitness: float = 0.5) -> None:
        append_jsonl(self.archive.runs_file, _record(run_id, edges, fitness).to_dict())


class UnexploredEdgeTest(ArchiveTestBase):
    def test_an_empty_archive_reports_every_declared_edge_unexplored(self) -> None:
        declared = {f"{e.source}->{e.target}" for e in self.graph.edges}
        self.assertEqual(set(self.archive.unexplored_edges(self.graph)), declared)

    def test_a_taken_edge_stops_being_unexplored(self) -> None:
        edge = f"{self.graph.edges[0].source}->{self.graph.edges[0].target}"
        self._add("r1", [edge])
        self.assertNotIn(edge, self.archive.unexplored_edges(self.graph))

    def test_a_linear_topology_offers_exploration_nothing(self) -> None:
        """Every edge is priority 0, so there is no ordering to correct."""
        linear = StageGraph.linear()
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        self.assertIsNone(self.archive.propose_exploration(graph=linear))

    def test_unexplored_edges_come_back_in_priority_order(self) -> None:
        ordered = self.archive.unexplored_edges(self.graph)
        by_priority = {f"{e.source}->{e.target}": e.priority for e in self.graph.edges}
        self.assertEqual(ordered, sorted(ordered, key=lambda e: (by_priority[e], e)))


class ProposeExplorationTest(ArchiveTestBase):
    """The proposer that gives the archive an entry into its own blind spot."""

    def _nonzero_priority_edge(self) -> str:
        edge = next(e for e in self.graph.edges if e.priority > 0)
        return f"{edge.source}->{edge.target}"

    def test_a_thin_archive_proposes_nothing(self) -> None:
        """With almost no runs the incumbent is barely evidenced; deviating is noise."""
        self._add("r1", ["01_literature_survey->02_hypothesis_generation"])
        self.assertIsNone(self.archive.propose_exploration(graph=self.graph))

    def test_an_unexplored_edge_is_proposed_once_the_archive_is_worth_trusting(self) -> None:
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        variant = self.archive.propose_exploration(graph=self.graph)
        self.assertIsNotNone(variant)
        self.assertEqual(len(variant.edge_priority), 1)
        self.assertIn("no archived run has", variant.note)

    def test_the_proposal_moves_exactly_one_edge_by_one_step(self) -> None:
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        variant = self.archive.propose_exploration(graph=self.graph)
        edge_key, new_priority = next(iter(variant.edge_priority.items()))
        source, target = edge_key.split("->", 1)
        original = next(
            e.priority for e in self.graph.edges if e.source == source and e.target == target
        )
        self.assertEqual(new_priority, original - 1)

    def test_it_arrives_unpromoted_so_it_buys_a_trial_not_a_verdict(self) -> None:
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        self.assertFalse(self.archive.propose_exploration(graph=self.graph).promoted)

    def test_the_same_proposal_is_not_made_twice(self) -> None:
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        self.assertIsNotNone(self.archive.propose_exploration(graph=self.graph))
        self.assertIsNone(self.archive.propose_exploration(graph=self.graph))

    def test_nothing_is_proposed_once_every_edge_has_been_tried(self) -> None:
        declared = [f"{e.source}->{e.target}" for e in self.graph.edges]
        for index in range(3):
            self._add(f"r{index}", declared)
        self.assertIsNone(self.archive.propose_exploration(graph=self.graph))

    def test_exploration_never_touches_a_guard(self) -> None:
        """The safety argument: it reorders preferences and nothing else."""
        for index in range(3):
            self._add(f"r{index}", ["01_literature_survey->02_hypothesis_generation"])
        variant = self.archive.propose_exploration(graph=self.graph)
        applied = variant.apply_to(self.graph)

        before = {(e.source, e.target): e.guard for e in self.graph.edges}
        after = {(e.source, e.target): e.guard for e in applied.edges}
        self.assertEqual(set(before), set(after), "no edge added or removed")
        for key, guard in before.items():
            self.assertIs(after[key], guard, f"guard changed on {key}")


class ClosedLoopRegressionTest(ArchiveTestBase):
    """The defect this exists for: exploit-only learning can never reach an untaken edge."""

    def test_the_exploit_proposer_alone_never_reaches_an_untaken_edge(self) -> None:
        taken = "01_literature_survey->02_hypothesis_generation"
        for index in range(6):
            self._add(f"r{index}", [taken], fitness=0.5 + 0.01 * index)

        exploit = self.archive.propose_variant(graph=self.graph)
        touched = set(exploit.edge_priority) if exploit else set()
        untaken = set(self.archive.unexplored_edges(self.graph))
        self.assertTrue(untaken, "fixture must leave something unexplored")
        self.assertFalse(touched & untaken, "exploit proposer cannot reach an untaken edge")

        # ...and the explore proposer can.
        explore = self.archive.propose_exploration(graph=self.graph)
        self.assertIsNotNone(explore)
        self.assertTrue(set(explore.edge_priority) & untaken)


if __name__ == "__main__":
    unittest.main()
