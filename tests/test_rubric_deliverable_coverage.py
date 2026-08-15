"""The one criterion that reads a document the run did not write.

Every other criterion in `src/rubric.py` measures the run against its own record:
whether the paths it named resolve, whether the ledger it wrote is four different
things, whether the numbers it reported appear in the files it produced. A run that
studies the wrong question rigorously satisfies all of them — measured on a
ResearchClawBench pass, the eight read 0.97 at Stage 06 on the one run the external
judge scored 0.0, and the run's own `What I Did` said in plain words that the task's
first named output had not been derived.

So this criterion reads the task statement. Two halves, and both are load-bearing:
without the number the score is moved by keyword-stuffing, and without the terms it is
`numeric_fidelity` again.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.rubric import score_stage
from src.utils import (
    STAGES,
    build_run_paths,
    ensure_run_layout,
    write_text,
)

STAGE_01 = next(stage for stage in STAGES if stage.number == 1)
STAGE_03 = next(stage for stage in STAGES if stage.number == 3)
STAGE_06 = next(stage for stage in STAGES if stage.number == 6)

#: Two demands under a brief heading, wrapped in the delivery contract every shipped
#: task carries. The contract lines must not become demands — see
#: `tests/test_task_deliverables_contract.py`.
TASK = (
    "## Research Task\n\n"
    "### Task Description\n"
    "Derive the Hartree-Fock Hamiltonian for the target bilayer; compute the "
    "quasiparticle gap in meV and compare it against the published value.\n\n"
    "## Execution Protocol\n\n"
    "Your primary goal is to complete the research task and produce a high-quality "
    "`report/report.md`.\n"
    "**Figures are mandatory** - generate plots and save to `report/images/`.\n"
)


def draft(*, objective: str, what_i_did: str, key_results: str) -> str:
    return (
        "# Stage\n\n"
        f"## Objective\n\n{objective}\n\n"
        f"## What I Did\n\n{what_i_did}\n\n"
        f"## Key Results\n\n{key_results}\n\n"
        "## Files Produced\n\n- `workspace/results/metrics.json`\n\n"
        "## Decision Ledger\n\n"
        "- Open Questions: none.\n- Locked Decisions: none.\n"
        "- Assumptions: none.\n- Rejected Alternatives: none.\n\n"
        "## Suggestions for Refinement\n\n1. More.\n"
    )


class DeliverableCoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.paths = build_run_paths(Path(tmp.name) / "run")
        ensure_run_layout(self.paths)
        write_text(self.paths.user_input, TASK)
        write_text(
            self.paths.results_dir / "metrics.json",
            json.dumps({"gap_meV": 41.7, "published_gap_meV": 43.2}),
        )
        write_text(self.paths.results_dir / "hamiltonian.md", "H_HF = ...\n" * 20)

    def score(self, markdown: str, stage=STAGE_06) -> float:
        criteria = score_stage(paths=self.paths, stage=stage, markdown=markdown).by_key
        return criteria["deliverable_coverage"].score

    def observed(self, markdown: str, stage=STAGE_06) -> str:
        criteria = score_stage(paths=self.paths, stage=stage, markdown=markdown).by_key
        return criteria["deliverable_coverage"].observed

    def shortfall(self, markdown: str, stage=STAGE_06) -> str:
        criteria = score_stage(paths=self.paths, stage=stage, markdown=markdown).by_key
        return criteria["deliverable_coverage"].shortfall

    # -- the failure it exists for ------------------------------------------------

    def test_a_rigorous_study_of_something_else_scores_zero(self) -> None:
        """The observed failure, in one draft.

        Real artifacts, real numbers, numbers that trace to real files, no hedging —
        and the task was not attempted. Every other criterion passes this.
        """
        markdown = draft(
            objective="Characterise the corpus of candidate systems.",
            what_i_did="Counted the papers in the corpus and scored the extraction pipeline.",
            key_results="Extraction accuracy reached 90.9% over 55 attempts.",
        )
        self.assertEqual(self.score(markdown), 0.0)

    def test_answering_the_task_with_a_traceable_number_scores_one(self) -> None:
        """Each demand answered where it lands on disk: one as a file, one as a number.

        The file half is not slack. A task that names an object as its output — a
        derivation, an equation set, a table — has no statistic to report, and a
        criterion that only accepted numbers would cap exactly the deliverable it exists
        to protect at half marks.
        """
        markdown = draft(
            objective="Answer the task.",
            what_i_did=(
                "Derived the Hartree-Fock Hamiltonian for the bilayer and reduced it to "
                "its quadratic terms."
            ),
            key_results=(
                "The derived Hartree-Fock Hamiltonian for the target bilayer is written "
                "out in `workspace/results/hamiltonian.md`. The quasiparticle gap is "
                "41.7 meV, against the published 43.2 meV."
            ),
        )
        self.assertEqual(self.score(markdown), 1.0)

    def test_naming_a_file_that_does_not_exist_answers_nothing(self) -> None:
        markdown = draft(
            objective="Answer the task.",
            what_i_did="Derived the Hartree-Fock Hamiltonian for the bilayer.",
            key_results=(
                "The derived Hartree-Fock Hamiltonian for the target bilayer is written "
                "out in `workspace/results/not_written.md`. The quasiparticle gap is "
                "41.7 meV, against the published 43.2 meV."
            ),
        )
        self.assertEqual(self.score(markdown), 0.75)

    def test_the_shortfall_names_the_demand_that_was_dropped(self) -> None:
        markdown = draft(
            objective="Answer half the task.",
            what_i_did="Computed the gap.",
            key_results="The quasiparticle gap is 41.7 meV against the published 43.2 meV.",
        )
        self.assertLess(self.score(markdown), 1.0)
        self.assertIn("Hartree-Fock", self.shortfall(markdown))

    # -- what it must not reward ---------------------------------------------------

    def test_the_task_s_nouns_without_a_number_are_not_an_answer(self) -> None:
        """Keyword-stuffing is the attack; the disk match is the whole defence.

        Both demands are engaged and neither is answered, so the score is exactly half.
        """
        markdown = draft(
            objective="Discuss.",
            what_i_did="Read about Hartree-Fock Hamiltonians and quasiparticle gaps.",
            key_results=(
                "We discuss the derived Hartree-Fock Hamiltonian for the target bilayer "
                "at length, qualitatively. We compare the quasiparticle gap against the "
                "published literature in words rather than numbers."
            ),
        )
        self.assertEqual(self.score(markdown), 0.5)
        self.assertIn("without a measured value", self.shortfall(markdown))

    def test_a_number_no_artifact_holds_does_not_answer_a_demand(self) -> None:
        """Catching the invented number is `numeric_fidelity`'s job; not counting it
        as an answer is this one's."""
        markdown = draft(
            objective="Answer the task.",
            what_i_did="Derived the Hartree-Fock Hamiltonian for the bilayer.",
            key_results=(
                "The derived Hartree-Fock Hamiltonian gives a quasiparticle gap of "
                "88.8 meV, compared against a published value of 99.1 meV."
            ),
        )
        self.assertEqual(self.score(markdown), 0.5)

    def test_the_delivery_contract_is_not_one_of_the_demands(self) -> None:
        """A draft that saves PNGs and says nothing else has answered nothing."""
        markdown = draft(
            objective="Deliver.",
            what_i_did="Studied the related work and saved plots to report/images/.",
            key_results="Produced a high-quality report with mandatory figures, 5 of them.",
        )
        self.assertEqual(self.score(markdown), 0.0)

    # -- shape ---------------------------------------------------------------------

    def test_before_stage_05_only_the_engagement_half_is_scored(self) -> None:
        """A survey has no results to carry a number and must not be failed for it."""
        markdown = draft(
            objective="Survey.",
            what_i_did="Reviewed prior derivations.",
            key_results=(
                "Prior work derives the Hartree-Fock Hamiltonian for related target "
                "bilayers. Two of those papers compare a published quasiparticle gap "
                "against a computed one."
            ),
        )
        self.assertEqual(self.score(markdown, stage=STAGE_03), 1.0)
        self.assertLess(self.score(markdown, stage=STAGE_06), 1.0)

    def test_a_task_stating_no_demand_does_not_penalise_the_draft(self) -> None:
        write_text(self.paths.user_input, "Some background prose about bilayers.")
        markdown = draft(objective="x", what_i_did="y", key_results="z")
        self.assertEqual(self.score(markdown), 1.0)
        self.assertIn("no demand sentence", self.observed(markdown))

    def test_it_reaches_stage_01(self) -> None:
        """`min_stage` on this one would make an early total a different measurement."""
        markdown = draft(objective="x", what_i_did="y", key_results="z")
        criteria = score_stage(paths=self.paths, stage=STAGE_01, markdown=markdown).by_key
        self.assertIn("deliverable_coverage", criteria)

    # -- the property the whole module rests on ------------------------------------

    def test_it_is_verdict_blind(self) -> None:
        """A refuted answer with a traceable number is worth what a supported one is."""
        supported = draft(
            objective="Answer the task.",
            what_i_did="Derived the Hartree-Fock Hamiltonian for the bilayer.",
            key_results=(
                "The derived Hartree-Fock Hamiltonian reproduces the published result: "
                "the quasiparticle gap is 41.7 meV against the published 43.2 meV."
            ),
        )
        refuted = draft(
            objective="Answer the task.",
            what_i_did="Derived the Hartree-Fock Hamiltonian for the bilayer.",
            key_results=(
                "The derived Hartree-Fock Hamiltonian fails to reproduce the published "
                "result: the quasiparticle gap is 41.7 meV against the published 43.2 meV."
            ),
        )
        self.assertEqual(self.score(supported), self.score(refuted))


class IdentifiersAreNotMeasurementsTest(unittest.TestCase):
    """`numeric_fidelity` demanded that the paper a task is *about* be in a results file.

    `_is_measurement_like` admitted any token containing a dot, so an arXiv id, a DOI and
    a "Fig. 3" all became numbers the draft had to justify. The cheapest way to raise the
    criterion was to delete the research subject's name from the prose, and the gain was
    five times `DEFAULT_MIN_GAIN` — large enough for the ratchet to record the deletion
    as a new champion.
    """

    def test_an_arxiv_id_is_not_a_reported_measurement(self) -> None:
        from src.rubric import _is_measurement_like

        self.assertFalse(_is_measurement_like("2111.01152", 2111.01152))
        self.assertFalse(_is_measurement_like("2205.09876", 2205.09876, prefix="see arXiv:"))

    def test_a_labelled_reference_is_not_a_reported_measurement(self) -> None:
        from src.rubric import _is_measurement_like

        for prefix in ("as shown in Fig. ", "in equation ", "see Section ", "Table "):
            with self.subTest(prefix=prefix):
                self.assertFalse(_is_measurement_like("3.5", 3.5, prefix=prefix))

    def test_a_measurement_is_still_a_measurement(self) -> None:
        from src.rubric import _is_measurement_like

        self.assertTrue(_is_measurement_like("41.7", 41.7, prefix="the gap is "))
        self.assertTrue(_is_measurement_like("0.741", 0.741, prefix="accuracy of "))
        self.assertTrue(_is_measurement_like("2048", 2048.0, prefix="context of "))


if __name__ == "__main__":
    unittest.main()
