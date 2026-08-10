"""What the archive is allowed to say inside a routing prompt.

The archive's learned value reached nothing: 0 of 400 measured node-comparisons
changed `default_move`, because it filters to forward edges and every node has one.
Three independent reviews refused the obvious fix — wiring the statistic into
`default_move` — on the grounds that it would put an unrandomised, guard-selected,
n=3 number in charge of what the run does at the moment a guard has just failed.

This is the other route: the archive shows the agent what earlier runs measured, and
the agent — which can see the actual research, and the archive cannot — decides. The
objections that killed the first version are the properties these tests hold.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.archive import Archive, RunRecord
from src.decisions import believable_evidence, decisions_from, offered_payoffs
from src.router import StageRouter
from src.rubric import RUBRIC_VERSION
from src.stage_graph import GraphState, StageGraph
from src.utils import STAGES, append_jsonl, build_run_paths, ensure_run_layout, write_text


STAGE_06 = next(stage for stage in STAGES if stage.number == 6)
BOTH = ["05_experimentation", "07_writing"]
EIGHT = [f"0{n}_s" for n in range(1, 9)]


def run(run_id: str, *, fitness: float, chose: str) -> RunRecord:
    return RunRecord(
        run_id=run_id,
        variant_id="baseline",
        rubric_version=RUBRIC_VERSION,
        edges={},
        stage_fitness={key: fitness for key in EIGHT},
        topology="adaptive",
        provenance="live",
        route="",
        steps=1,
        revisits=0,
        agent_directed=0,
        bypassed=0,
        recorded_at="t",
        decisions=[{"source": "06_analysis", "chose": chose, "offered": BOTH}],
    )


class EvidenceGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.archive = Archive(Path(self._tmp.name) / "archive")

    def seed(self, pairs: int, took: float, declined: float) -> None:
        for index in range(pairs):
            append_jsonl(
                self.archive.runs_file,
                run(f"t{index}", fitness=took, chose="05_experimentation").to_dict(),
            )
            append_jsonl(
                self.archive.runs_file,
                run(f"d{index}", fitness=declined, chose="07_writing").to_dict(),
            )

    def evidence(self):
        payoffs = offered_payoffs(decisions_from(self.archive.runs()))
        return believable_evidence(payoffs, BOTH, "06_analysis")

    def test_a_thin_archive_shows_nothing_at_all(self) -> None:
        """Three a side has an opinion about every edge and is entitled to none.

        Shown with a caveat, it would be read; the caveat would not. So it is not
        shown.
        """
        self.seed(3, took=0.90, declined=0.10)
        self.assertEqual(self.evidence(), [])

    def test_a_believable_contrast_is_shown_for_both_sides_of_the_choice(self) -> None:
        """At a two-way node the two rows are mirror images, and both are true.

        Evidence that taking the revisit paid *is* evidence that taking the advance
        did not, so showing one and hiding the other would be presenting half of a
        symmetric fact.
        """
        self.seed(6, took=0.90, declined=0.10)
        shown = {payoff.edge: payoff.delta for payoff in self.evidence()}

        self.assertEqual(len(shown), 2)
        self.assertGreater(shown["06_analysis->05_experimentation"], 0)
        self.assertLess(shown["06_analysis->07_writing"], 0)
        self.assertAlmostEqual(
            shown["06_analysis->05_experimentation"],
            -shown["06_analysis->07_writing"],
            places=6,
        )

    def test_a_large_sample_with_no_effect_is_not_shown(self) -> None:
        """Attainability is necessary, not sufficient."""
        self.seed(8, took=0.50, declined=0.50)
        self.assertEqual(self.evidence(), [])

    def test_only_moves_on_this_menu_are_shown(self) -> None:
        """A node's evidence is filtered to the moves actually available here. An
        agent shown a contrast for an edge it cannot take is being argued at about a
        decision it does not have."""
        self.seed(6, took=0.90, declined=0.10)
        shown = believable_evidence(
            offered_payoffs(decisions_from(self.archive.runs())), ["07_writing"], "06_analysis"
        )
        self.assertEqual([payoff.edge for payoff in shown], ["06_analysis->07_writing"])


class PromptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = build_run_paths(Path(self._tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, "goal")
        write_text(self.paths.stage_file(STAGE_06), "# Stage 06: Analysis\n\nBody.\n")
        write_text(self.paths.code_dir / "run.py", "print(1)\n")
        self.archive = Archive(Path(self._tmp.name) / "archive")
        self.graph = StageGraph.adaptive()

    def seed(self, pairs: int, took: float, declined: float) -> None:
        for index in range(pairs):
            append_jsonl(self.archive.runs_file, run(f"t{index}", fitness=took, chose="05_experimentation").to_dict())
            append_jsonl(self.archive.runs_file, run(f"d{index}", fitness=declined, chose="07_writing").to_dict())

    def prompt(self, *, archive) -> str:
        router = StageRouter(None, mode="agent", archive=archive)
        moves = self.graph.moves(self.paths, STAGE_06.slug, GraphState())
        return router.build_prompt(
            paths=self.paths, stage=STAGE_06, moves=moves, state=GraphState(), score=None
        )

    def test_with_no_archive_the_prompt_is_unchanged(self) -> None:
        """The default. `--archive-steer` is off, so the routing prompt of an
        ordinary run says nothing about earlier runs at all."""
        self.assertNotIn("earlier runs measured", self.prompt(archive=None))

    def test_a_thin_archive_adds_nothing_to_the_prompt(self) -> None:
        self.seed(3, took=0.90, declined=0.10)
        self.assertNotIn("earlier runs measured", self.prompt(archive=self.archive))

    def test_a_believable_contrast_reaches_the_prompt_as_numbers(self) -> None:
        """Numbers, sample sizes and the test — not a recommendation.

        The reviewer objection that killed the first version was an archive-authored
        sentence inside the prompt that decides the route, with no gate that could
        fire on a wrong sentence. There is no sentence: there is a row, and the row
        carries what it rests on.
        """
        self.seed(6, took=0.90, declined=0.10)
        rendered = self.prompt(archive=self.archive)

        self.assertIn("earlier runs measured", rendered)
        self.assertIn("06_analysis->05_experimentation", rendered)
        self.assertIn("n=6", rendered)
        self.assertIn("p=", rendered)
        self.assertIn("evidence, not an instruction", rendered)
        self.assertIn("weaker than what you can see in front of you", rendered)

    def test_a_broken_archive_does_not_break_the_route(self) -> None:
        """A research aid being unavailable is not a reason to fail a decision."""

        class Exploding:
            def runs(self):
                raise RuntimeError("disk on fire")

        self.assertNotIn("earlier runs measured", self.prompt(archive=Exploding()))

    def test_the_archive_never_reaches_the_guards_or_the_default(self) -> None:
        """The invariant the reviews were protecting. Evidence is shown; nothing
        about which moves are admissible, or which one is taken with nobody asked,
        may depend on it."""
        self.seed(20, took=0.99, declined=0.01)
        state = GraphState()

        without = StageGraph.adaptive().default_move(self.paths, STAGE_06.slug, state)
        live_without = {m.target for m in self.graph.admissible_moves(self.paths, STAGE_06.slug, state)}

        router = StageRouter(None, mode="off", archive=self.archive)
        decision = router.choose(
            paths=self.paths, stage=STAGE_06, graph=self.graph, state=state
        )
        live_with = {m.target for m in self.graph.admissible_moves(self.paths, STAGE_06.slug, state)}

        self.assertEqual(live_with, live_without)
        self.assertEqual(decision.target, without.target)
        self.assertFalse(decision.agent_directed)


if __name__ == "__main__":
    unittest.main()
