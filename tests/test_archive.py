"""The cross-run archive: what it learns, and what it is not allowed to conclude.

An archive that acts on one run is a superstition generator. Most of these tests
are the refusals — too few observations, a rubric version change, a variant that
beat the incumbent once — and one is the invariant that matters more than any of
them: a learned prior reorders preferences and can never open a guarded edge.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.archive import (
    Archive,
    BASELINE_VARIANT,
    RunRecord,
    Variant,
    edge_payoffs,
    resolve_graph,
)
from src.rubric import RUBRIC_VERSION
from src.stage_graph import StageGraph
from src.utils import append_jsonl


def record(
    run_id: str,
    *,
    edges: dict[str, int],
    fitness: float,
    variant_id: str = "baseline",
    rubric_version: str | None = None,
) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        variant_id=variant_id,
        rubric_version=rubric_version or RUBRIC_VERSION,
        edges=edges,
        stage_fitness={"05_experimentation": fitness, "06_analysis": fitness},
        route="",
        steps=len(edges),
        revisits=0,
        agent_directed=0,
        recorded_at="2026-08-06T00:00:00",
    )


BACK = "06_analysis->05_experimentation"
FORWARD = "06_analysis->07_writing"


class ArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.archive = Archive(Path(self._tmp.name) / "archive")

    def seed(self, records) -> None:
        for item in records:
            append_jsonl(self.archive.runs_file, item.to_dict())

    def seed_a_believable_payoff(self, *, taken: float = 0.85, skipped: float = 0.60) -> None:
        self.seed(
            [record(f"back{i}", edges={BACK: 1}, fitness=taken) for i in range(3)]
            + [record(f"fwd{i}", edges={FORWARD: 1}, fitness=skipped) for i in range(3)]
        )

    # -- payoff arithmetic ---------------------------------------------------

    def test_an_edge_is_compared_against_runs_that_reached_the_same_node(self) -> None:
        """Comparing against the whole archive would credit the edge with the
        difference between runs that got to Stage 06 and runs that never did."""
        self.seed(
            [
                record("a", edges={BACK: 1}, fitness=0.9),
                record("b", edges={FORWARD: 1}, fitness=0.6),
                record("c", edges={"01_literature_survey->02_hypothesis_generation": 1}, fitness=0.1),
            ]
        )
        payoff = edge_payoffs(self.archive.runs())[BACK]
        self.assertEqual((payoff.taken_runs, payoff.skipped_runs), (1, 1))
        self.assertAlmostEqual(payoff.delta, 0.3, places=6)

    def test_one_lucky_run_is_not_believable(self) -> None:
        self.seed([record("a", edges={BACK: 1}, fitness=0.95), record("b", edges={FORWARD: 1}, fitness=0.2)])
        self.assertFalse(edge_payoffs(self.archive.runs())[BACK].believable(3))

    def test_runs_measured_under_another_rubric_are_not_mixed_in(self) -> None:
        """A reweight would otherwise read as every archived run having moved."""
        self.seed(
            [record(f"old{i}", edges={BACK: 1}, fitness=0.99, rubric_version="0") for i in range(5)]
            + [record("new", edges={BACK: 1}, fitness=0.4)]
        )
        payoff = edge_payoffs(self.archive.runs())[BACK]
        self.assertEqual(payoff.taken_runs, 1)
        self.assertAlmostEqual(payoff.taken_mean, 0.4, places=6)

    def test_a_partial_run_is_averaged_over_what_it_measured(self) -> None:
        """A run stopped at Stage 07 by `--final-stage` did not fail Stage 08."""
        partial = RunRecord(
            run_id="p",
            variant_id="baseline",
            rubric_version=RUBRIC_VERSION,
            edges={},
            stage_fitness={"01_literature_survey": 0.8},
            route="",
            steps=1,
            revisits=0,
            agent_directed=0,
            recorded_at="t",
        )
        self.assertAlmostEqual(partial.mean_fitness, 0.8)

    def test_a_malformed_line_does_not_lose_the_archive(self) -> None:
        self.seed([record("a", edges={BACK: 1}, fitness=0.7)])
        with self.archive.runs_file.open("a", encoding="utf-8") as handle:
            handle.write("{not json at all\n")
        self.seed([record("b", edges={BACK: 1}, fitness=0.8)])
        self.assertEqual([item.run_id for item in self.archive.runs()], ["a", "b"])

    # -- variation -----------------------------------------------------------

    def test_nothing_is_proposed_from_an_empty_archive(self) -> None:
        """A proposer that always proposes turns an archive into a random walk."""
        self.assertIsNone(self.archive.propose_variant())

    def test_a_believable_payoff_produces_a_child_that_explains_itself(self) -> None:
        self.seed_a_believable_payoff()
        variant = self.archive.propose_variant()
        self.assertIsNotNone(variant)
        self.assertEqual(variant.parent_id, BASELINE_VARIANT.variant_id)
        self.assertEqual(variant.generation, 1)
        self.assertFalse(variant.promoted)
        self.assertIn(BACK, variant.note)
        self.assertIn("0.85", variant.note)

    def test_a_child_changes_one_edge_at_a_time(self) -> None:
        """A variant that reshuffles five edges cannot be told apart from one that
        got lucky on one of them."""
        self.seed_a_believable_payoff()
        variant = self.archive.propose_variant()
        self.assertEqual(len(variant.edge_priority), 1)

    def test_the_same_child_is_not_proposed_twice(self) -> None:
        self.seed_a_believable_payoff()
        self.assertIsNotNone(self.archive.propose_variant())
        self.assertIsNone(self.archive.propose_variant())

    def test_a_losing_edge_is_deprioritised_rather_than_removed(self) -> None:
        self.seed_a_believable_payoff(taken=0.55, skipped=0.85)
        variant = self.archive.propose_variant()
        graph = variant.apply_to(StageGraph.adaptive())
        edge = next(e for e in graph.edges if f"{e.source}->{e.target}" == BACK)
        original = next(e for e in StageGraph.adaptive().edges if f"{e.source}->{e.target}" == BACK)
        self.assertGreater(edge.priority, original.priority)
        self.assertIn(BACK, {f"{e.source}->{e.target}" for e in graph.edges})

    # -- the invariant -------------------------------------------------------

    def test_a_variant_cannot_open_a_guarded_edge(self) -> None:
        """The guards are the correctness argument for letting an agent route at
        all, and the component that learns from outcomes is exactly the one that
        must not be able to weaken them: the cheapest way to raise mean fitness
        would be to stop checking that hypotheses were adjudicated."""
        base = StageGraph.adaptive()
        hostile = Variant(
            variant_id="hostile",
            topology="adaptive",
            edge_priority={FORWARD: -99, "06_analysis->99_nonexistent": 0},
        )
        rebuilt = hostile.apply_to(base)

        self.assertEqual(
            {(e.source, e.target, e.guard) for e in rebuilt.edges},
            {(e.source, e.target, e.guard) for e in base.edges},
        )
        self.assertNotIn("99_nonexistent", {e.target for e in rebuilt.edges})

    def test_an_untouched_edge_keeps_its_priority(self) -> None:
        base = StageGraph.adaptive()
        rebuilt = Variant("v", "adaptive", edge_priority={BACK: 0}).apply_to(base)
        for edge in base.edges:
            key = f"{edge.source}->{edge.target}"
            if key == BACK:
                continue
            match = next(e for e in rebuilt.edges if e.source == edge.source and e.target == edge.target)
            self.assertEqual(match.priority, edge.priority)

    # -- promotion -----------------------------------------------------------

    def test_beating_the_incumbent_once_does_not_promote(self) -> None:
        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive", parent_id="baseline")])
        self.seed(
            [record("b1", edges={}, fitness=0.5), record("c1", edges={}, fitness=0.9, variant_id="challenger")]
        )
        self.assertFalse(self.archive.promote("challenger"))

    def test_an_improvement_that_replays_is_promoted(self) -> None:
        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive", parent_id="baseline")])
        self.seed(
            [record(f"b{i}", edges={}, fitness=0.50) for i in range(3)]
            + [record(f"c{i}", edges={}, fitness=0.80, variant_id="challenger") for i in range(3)]
        )
        self.assertTrue(self.archive.promote("challenger"))
        self.assertTrue(self.archive.variant("challenger").promoted)

    def test_a_challenger_that_only_ties_is_not_promoted(self) -> None:
        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive")])
        self.seed(
            [record(f"b{i}", edges={}, fitness=0.70) for i in range(4)]
            + [record(f"c{i}", edges={}, fitness=0.705, variant_id="challenger") for i in range(4)]
        )
        self.assertFalse(self.archive.promote("challenger"))

    # -- sampling ------------------------------------------------------------

    def test_sampling_is_reproducible_from_the_archive(self) -> None:
        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive")])
        self.seed([record("b1", edges={}, fitness=0.6)])
        self.assertEqual(
            self.archive.sample_parent().variant_id, self.archive.sample_parent().variant_id
        )

    def test_an_unproven_variant_stays_in_the_draw(self) -> None:
        """Fitness-proportional sampling alone locks the archive onto whatever won
        first and stops generating the observations that would overturn it."""
        self.archive._save_variants([BASELINE_VARIANT, Variant("unproven", "adaptive")])
        self.seed([record(f"b{i}", edges={}, fitness=0.9) for i in range(8)])
        picks = {self.archive.sample_parent(seed=seed).variant_id for seed in range(40)}
        self.assertIn("unproven", picks)
        self.assertIn(BASELINE_VARIANT.variant_id, picks)

    # -- resolution ----------------------------------------------------------

    def test_no_archive_means_the_declared_topology_unchanged(self) -> None:
        graph, variant_id = resolve_graph(None, "adaptive")
        self.assertEqual(variant_id, "baseline")
        self.assertEqual(
            {(e.source, e.target, e.priority) for e in graph.edges},
            {(e.source, e.target, e.priority) for e in StageGraph.adaptive().edges},
        )

    def test_a_variant_for_another_topology_is_not_applied(self) -> None:
        self.archive._save_variants(
            [BASELINE_VARIANT, Variant("adaptive-child", "adaptive", edge_priority={BACK: 0})]
        )
        graph, variant_id = resolve_graph(self.archive, "linear")
        self.assertEqual(variant_id, "baseline")
        self.assertEqual(graph.name, "linear")

    def test_the_report_marks_which_payoffs_are_believable(self) -> None:
        self.seed_a_believable_payoff()
        self.seed([record("lonely", edges={"07_writing->06_analysis": 1}, fitness=0.99)])
        report = self.archive.report()
        self.assertIn(f"rubric: v{RUBRIC_VERSION}", report)
        self.assertIn(BACK, report)
        self.assertIn("| no |", report)


if __name__ == "__main__":
    unittest.main()
