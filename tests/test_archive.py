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
    DEFAULT_MIN_OBSERVATIONS,
    BASELINE_VARIANT,
    RunRecord,
    Variant,
    edge_payoffs,
    resolve_graph,
)
from src.inference import unpaired_floor
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
    topology: str = "adaptive",
    provenance: str = "live",
    offered: dict[str, list[str]] | None = None,
) -> RunRecord:
    """A run record, with a decision per edge it took.

    ``offered`` gives the choice set at each source; it defaults to "the target
    taken plus the other target this file uses at that node", so a record built the
    short way still produces a usable contrast. The estimator needs the choice set:
    an edge that was never offered is not an edge that was declined.
    """
    decisions = []
    for edge in edges:
        source, target = edge.split("->", 1)
        alternatives = (offered or {}).get(source)
        if alternatives is None:
            alternatives = sorted({target, "07_writing", "05_experimentation"})
        decisions.append({"source": source, "chose": target, "offered": list(alternatives)})
    return RunRecord(
        run_id=run_id,
        variant_id=variant_id,
        rubric_version=rubric_version or RUBRIC_VERSION,
        edges=edges,
        stage_fitness={"05_experimentation": fitness, "06_analysis": fitness},
        topology=topology,
        provenance=provenance,
        route="",
        steps=len(edges),
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="2026-08-06T00:00:00",
        decisions=decisions,
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
        """Six a side, which is the derived floor rather than a round number.

        An exact two-sided permutation test over three and three bottoms out at
        0.10, so the old fixture could not have licensed anything the corrected
        threshold would accept. `minimum_arms_for` computes six.
        """
        self.seed(
            [record(f"back{i}", edges={BACK: 1}, fitness=taken) for i in range(6)]
            + [record(f"fwd{i}", edges={FORWARD: 1}, fitness=skipped) for i in range(6)]
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
            + [record("newctl", edges={FORWARD: 1}, fitness=0.5)]
        )
        payoff = edge_payoffs(self.archive.runs())[BACK]
        self.assertEqual((payoff.taken_runs, payoff.skipped_runs), (1, 1))
        self.assertAlmostEqual(payoff.taken_mean, 0.4, places=6)

    # -- the composition of a run is not allowed to be the improvement --------

    def test_a_run_that_stopped_early_is_not_compared_against_one_that_finished(self) -> None:
        """The Goodhart hole this closes, measured on real scores.

        A stage's score is a weighted mean over the criteria that apply to it, and
        later stages face no fewer of them — 01 and 02 face the same set, and so do
        05 through 08, but the count rises twice on the way. On a scripted
        `--fake-operator` run, mean fitness over stages 01-02 is 0.973 against 0.817
        over all eight. Pool those and "stop early" is worth nearly eight times what
        a promotion needs — so the archive would find it, and promote whatever
        topology halts soonest.
        """
        short = RunRecord(
            run_id="short", variant_id="baseline", rubric_version=RUBRIC_VERSION,
            edges={BACK: 1}, stage_fitness={"01_literature_survey": 0.97, "02_hypothesis_generation": 1.0},
            topology="adaptive", provenance="live",
            route="", steps=2, revisits=0, agent_directed=0, bypassed=0, recorded_at="t",
        )
        long_runs = [
            RunRecord(
                run_id=f"long{i}", variant_id="baseline", rubric_version=RUBRIC_VERSION,
                edges={FORWARD: 1},
                stage_fitness={f"0{n}_s": 0.80 for n in range(1, 9)},
                topology="adaptive", provenance="live",
                route="", steps=8, revisits=0, agent_directed=0, bypassed=0, recorded_at="t",
            )
            for i in range(3)
        ]
        self.seed([short, *long_runs])

        self.assertNotEqual(short.basis, long_runs[0].basis)
        payoff = edge_payoffs(self.archive.runs()).get(BACK)
        self.assertEqual(
            (payoff.taken_runs, payoff.skipped_runs),
            (0, 0),
            msg="a two-stage run was contrasted against eight-stage runs",
        )

    def test_a_basis_with_only_one_arm_contributes_no_observations(self) -> None:
        """It carries no contrast, so counting its runs would inflate the number
        that decides believability without adding anything to the delta."""
        self.seed([record(f"a{i}", edges={BACK: 1}, fitness=0.9) for i in range(5)])
        payoff = edge_payoffs(self.archive.runs())[BACK]
        self.assertEqual((payoff.taken_runs, payoff.skipped_runs), (0, 0))
        self.assertFalse(payoff.believable(3))

    def test_a_challenger_that_loses_on_any_composition_is_not_promoted(self) -> None:
        """Winning on average while losing on some composition is the signature of a
        variant that traded one kind of run for another."""
        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive")])
        wide = {f"0{n}_s": 0.0 for n in range(1, 9)}
        narrow = {"01_a": 0.0, "02_b": 0.0}

        def run(name, variant, shape, value):
            return RunRecord(
                run_id=name, variant_id=variant, rubric_version=RUBRIC_VERSION, edges={},
                stage_fitness={k: value for k in shape}, topology="adaptive",
                provenance="live", route="", steps=len(shape),
                revisits=0, agent_directed=0, bypassed=0, recorded_at="t",
            )

        self.seed(
            [run(f"bw{i}", "baseline", wide, 0.50) for i in range(3)]
            + [run(f"cw{i}", "challenger", wide, 0.90) for i in range(3)]
            + [run(f"bn{i}", "baseline", narrow, 0.90) for i in range(3)]
            + [run(f"cn{i}", "challenger", narrow, 0.50) for i in range(3)]
        )
        self.assertFalse(self.archive.promote("challenger"))

    def test_a_partial_run_is_averaged_over_what_it_measured(self) -> None:
        """A run stopped at Stage 07 by `--final-stage` did not fail Stage 08."""
        partial = RunRecord(
            run_id="p",
            variant_id="baseline",
            rubric_version=RUBRIC_VERSION,
            edges={},
            stage_fitness={"01_literature_survey": 0.8},
            topology="adaptive",
            provenance="live",
            route="",
            steps=1,
            revisits=0,
            agent_directed=0,
            bypassed=0,
            recorded_at="t",
        )
        self.assertAlmostEqual(partial.mean_fitness, 0.8)

    def test_a_malformed_line_does_not_lose_the_archive(self) -> None:
        self.seed([record("a", edges={BACK: 1}, fitness=0.7)])
        with self.archive.runs_file.open("a", encoding="utf-8") as handle:
            handle.write("{not json at all\n")
        self.seed([record("b", edges={BACK: 1}, fitness=0.8)])
        self.assertEqual([item.run_id for item in self.archive.runs()], ["a", "b"])

    def test_a_linear_run_is_not_in_the_control_arm_of_an_edge_it_never_had(self) -> None:
        """The sign flip. A linear run never had the revisit edge, so counting it as
        a run that "reached the node and declined" puts a run that was never offered
        the choice into the control arm — and the answer comes out backwards.
        """
        self.seed(
            [record(f"t{i}", edges={BACK: 1}, fitness=0.60) for i in range(3)]
            + [record(f"d{i}", edges={FORWARD: 1}, fitness=0.70) for i in range(3)]
            + [
                record(f"L{i}", edges={FORWARD: 1}, fitness=0.40, topology="linear")
                for i in range(6)
            ]
        )
        payoff = edge_payoffs(self.archive.runs())[BACK]
        self.assertEqual((payoff.taken_runs, payoff.skipped_runs), (3, 3))
        self.assertAlmostEqual(payoff.delta, -0.10, places=6)

    def test_a_run_recorded_twice_counts_once(self) -> None:
        """`record_into_archive` fires on the fresh path and the resume path, and the
        run id is the run directory. A resumed run would otherwise be two free
        observations, pushing the count past `min_observations` with no new evidence.
        """
        self.seed([record("same", edges={BACK: 1}, fitness=0.5) for _ in range(3)])
        self.assertEqual(len(self.archive.runs()), 1)

    def test_a_fake_run_is_kept_and_never_estimated_from(self) -> None:
        """A fake operator's scores measure the script. Recorded — it is the only
        end-to-end exercise of this seam — and excluded from every estimate."""
        self.seed(
            [record(f"f{i}", edges={BACK: 1}, fitness=0.99, provenance="fake") for i in range(6)]
            + [record(f"g{i}", edges={FORWARD: 1}, fitness=0.10, provenance="fake") for i in range(6)]
        )
        self.assertEqual(len(self.archive.runs()), 12)
        self.assertEqual(self.archive.variant_fitness(), {})
        # Not merely zeroed — absent. A fake run contributes no edge to the
        # estimator's domain, so there is nothing for a payoff to be computed over.
        self.assertNotIn(BACK, edge_payoffs(self.archive.runs()))
        self.assertIsNone(self.archive.propose_variant())

    def test_a_row_written_before_provenance_existed_is_not_assumed_live(self) -> None:
        import json as _json

        legacy = record("old", edges={BACK: 1}, fitness=0.9).to_dict()
        legacy.pop("provenance")
        legacy.pop("topology")
        self.archive.runs_file.parent.mkdir(parents=True, exist_ok=True)
        with self.archive.runs_file.open("a", encoding="utf-8") as handle:
            handle.write(_json.dumps(legacy) + "\n")
        loaded = self.archive.runs()[0]
        self.assertEqual(loaded.provenance, "unknown")
        self.assertFalse(loaded.usable)

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
            [record(f"b{i}", edges={}, fitness=0.50) for i in range(DEFAULT_MIN_OBSERVATIONS)]
            + [
                record(f"c{i}", edges={}, fitness=0.80, variant_id="challenger")
                for i in range(DEFAULT_MIN_OBSERVATIONS)
            ]
        )
        self.assertTrue(self.archive.promote("challenger"))
        self.assertTrue(self.archive.variant("challenger").promoted)

    def test_three_a_side_cannot_promote_however_large_the_gap(self) -> None:
        """The floor is derived, and this is what deriving it changed.

        `DEFAULT_MIN_OBSERVATIONS` was 3, with a docstring saying three "is enough to
        stop acting on a single lucky run" — intent, not arithmetic. An exact
        two-sided permutation test over three and three bottoms out at p = 0.10, so
        three a side could never have licensed a claim at any threshold anyone would
        use, whatever the effect size.
        """
        # Equality, not a floor. `minimum_arms_for(0.05, family=f)` is 6 for every
        # family from 7 to 23 and becomes 7 at 24, so the graph is three edges away
        # from silently needing a seventh observation a side. A `>= 6` assertion
        # would not notice that happening.
        self.assertEqual(DEFAULT_MIN_OBSERVATIONS, 6)
        self.assertGreater(unpaired_floor(3, 3), 0.05)

        self.archive._save_variants([BASELINE_VARIANT, Variant("challenger", "adaptive")])
        self.seed(
            [record(f"b{i}", edges={}, fitness=0.10) for i in range(3)]
            + [record(f"c{i}", edges={}, fitness=0.99, variant_id="challenger") for i in range(3)]
        )
        self.assertFalse(self.archive.promote("challenger"))

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
