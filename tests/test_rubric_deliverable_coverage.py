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

    def test_the_shortfall_names_the_dropped_demand_without_quoting_it(self) -> None:
        """Actionable, and not pasteable.

        The shortfall used to carry the demand verbatim. The ratchet prints it into the
        next polish prompt, so pasting it back raised the *total* on 88 of the 118
        archived drafts that carried one — median +0.036, every one past
        `DEFAULT_MIN_GAIN`. It now names the
        subject instead, and `_SHORTFALL_MARKERS` filters the text itself.
        """
        markdown = draft(
            objective="Answer half the task.",
            what_i_did="Computed the gap.",
            key_results="The quasiparticle gap is 41.7 meV against the published 43.2 meV.",
        )
        shortfall = self.shortfall(markdown)
        self.assertLess(self.score(markdown), 1.0)
        self.assertIn("demand 1 of", shortfall)
        # Nothing in it can be pasted into a sentence about the demand: no subject words,
        # no quote. The numbered list it points at is in the same prompt.
        self.assertNotIn("Hartree", shortfall)
        self.assertNotIn("hamiltonian", shortfall.casefold())

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
        self.assertIn("nothing checkable behind it", self.shortfall(markdown))

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

    def test_an_early_stage_is_held_to_the_same_contract(self) -> None:
        """The on-disk half applies at every stage, and it is reachable at every stage.

        v6 scored only the engagement half below Stage 05, on the theory that an early
        stage has no results to point at. It has: Stage 01 writes `literature/`. What the
        exemption actually bought was a draft of restated demands scoring 1.000 at Stages
        01, 03 and 04 on 40 of 40 archived tasks.
        """
        talk = draft(
            objective="Survey.",
            what_i_did="Reviewed prior derivations.",
            key_results=(
                "Prior work derives the Hartree-Fock Hamiltonian for related target "
                "bilayers. Two of those papers compare a published quasiparticle gap "
                "against a computed one."
            ),
        )
        self.assertEqual(self.score(talk, stage=STAGE_03), 0.5)

        write_text(self.paths.literature_dir / "prior_derivations.md", "notes\n" * 40)
        grounded = draft(
            objective="Survey.",
            what_i_did="Reviewed prior derivations.",
            key_results=(
                "Prior work derives the Hartree-Fock Hamiltonian for related target "
                "bilayers, collected in `workspace/literature/prior_derivations.md`. Two "
                "papers compare a published quasiparticle gap against a computed one, "
                "also in `workspace/literature/prior_derivations.md`."
            ),
        )
        self.assertEqual(self.score(grounded, stage=STAGE_03), 1.0)

    # -- the three free routes to a higher score, all measured open in v6 ---------------

    def test_restating_a_demand_in_its_own_words_is_not_engagement(self) -> None:
        """Scored 1.000 at Stages 01/03/04 on 40 of 40 archived tasks before this."""
        markdown = draft(
            objective="x",
            what_i_did="y",
            key_results=(
                "Hartree-Fock Hamiltonian target bilayer derive.\n"
                "Quasiparticle compare published value compute against."
            ),
        )
        self.assertEqual(self.score(markdown), 0.0)

    def test_quoting_the_task_statement_back_is_not_engagement(self) -> None:
        markdown = draft(
            objective="x",
            what_i_did="y",
            key_results=(
                "Derive the Hartree-Fock Hamiltonian for the target bilayer; compute the "
                "quasiparticle gap in meV and compare it against the published value."
            ),
        )
        self.assertEqual(self.score(markdown), 0.0)

    def test_pasting_the_shortfall_back_earns_nothing(self) -> None:
        """The ratchet prints the shortfall into the next polish prompt.

        Before the filter this was the cheapest new champion in the system: +0.036 median
        on the total across 89 archived drafts, all past `DEFAULT_MIN_GAIN`, for a paste.
        """
        markdown = draft(objective="x", what_i_did="y", key_results="Nothing yet.")
        before = self.score(markdown)
        pasted = draft(
            objective="x",
            what_i_did="y",
            key_results="Nothing yet. " + self.shortfall(markdown),
        )
        self.assertEqual(self.score(pasted), before)

    def test_citing_a_path_that_merely_resolves_is_not_evidence(self) -> None:
        """The largest exploit this criterion has had, and the cheapest to write.

        `_sentence_lands_on_disk` asked `_listed_file_exists` against the run root, which
        answers *does this path resolve*. One sentence per demand citing `/etc/hostname`
        — or the stage's own summary under `stages/`, which exists on every run by
        construction — took the criterion to 1.000 on 263 of 263 archived drafts for a
        median total gain of +0.0476. A real polish round in the same archive gained a
        median +0.0221, so four sentences were worth twice doing the work.
        """
        from src.rubric import _result_file_cited

        write_text(self.paths.results_dir / "experiment_manifest.json", '{"experiments": []}')
        # The benchmark copies its reference papers into `literature/` before the agent
        # starts. A directory whitelist called that a result; an mtime does not.
        handed_over = self.paths.literature_dir / "paper_000.pdf"
        write_text(handed_over, "%PDF-1.4\n" + "x" * 400)
        import os

        stamp = os.path.getmtime(self.paths.user_input) - 3600
        os.utime(handed_over, (stamp, stamp))

        for path in (
            "/etc/hostname",
            "stages/06_analysis.md",
            "workspace/artifacts/deliverables_coverage.json",
            "workspace/notes/open_questions.md",
            "workspace/data/input.csv",
            "workspace/results/experiment_manifest.json",
            "workspace/literature/paper_000.pdf",
        ):
            with self.subTest(path=path):
                self.assertFalse(
                    _result_file_cited(f"The answer is in `{path}`.", self.paths),
                    f"{path} is not something this run produced as a result",
                )

    def test_a_result_this_run_wrote_is_evidence(self) -> None:
        from src.rubric import _result_file_cited

        write_text(self.paths.figures_dir / "gap.png", "x" * 200)
        write_text(self.paths.report_dir / "report.md", "# Report\n\nBody.\n")
        for path in (
            "workspace/results/hamiltonian.md",
            "results/metrics.json",
            "workspace/figures/gap.png",
            "workspace/report/report.md",
        ):
            with self.subTest(path=path):
                self.assertTrue(
                    _result_file_cited(f"The answer is in `{path}`.", self.paths), path
                )

    def test_talking_about_everything_and_grounding_nothing_caps_at_half(self) -> None:
        markdown = draft(
            objective="Discuss.",
            what_i_did="Considered both parts of the brief at length.",
            key_results=(
                "Our treatment of the derived Hartree-Fock Hamiltonian across the target "
                "bilayer remains qualitative throughout. Similarly we compare the "
                "quasiparticle gap against published expectations only in narrative form."
            ),
        )
        self.assertEqual(self.score(markdown), 0.5)

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

    def test_a_percentage_is_matched_against_its_own_fraction_not_a_neighbourhood(self) -> None:
        """`74.1%` was satisfied by a results file holding `0.700`.

        The fraction branch read `max(0.5 * 10**-decimals / 100, tolerance)`, and the
        first term is a hundredth of the second, so the max is always `tolerance` — the
        window was ±0.05 on the fraction where the docstring three lines above promised
        ±0.0005. Five percentage points. The same function decides `numeric_fidelity`.
        """
        from src.rubric import _matches_artifact_number

        self.assertTrue(_matches_artifact_number(74.1, "74.1", True, {0.741}))
        self.assertTrue(_matches_artifact_number(74.1, "74.1", True, {74.1}))
        self.assertFalse(_matches_artifact_number(74.1, "74.1", True, {0.700}))
        self.assertFalse(_matches_artifact_number(74.1, "74.1", True, {0.79}))
        self.assertFalse(_matches_artifact_number(0.741, "0.741", False, {0.700}))

    def test_a_measurement_is_still_a_measurement(self) -> None:
        from src.rubric import _is_measurement_like

        self.assertTrue(_is_measurement_like("41.7", 41.7, prefix="the gap is "))
        self.assertTrue(_is_measurement_like("0.741", 0.741, prefix="accuracy of "))
        self.assertTrue(_is_measurement_like("2048", 2048.0, prefix="context of "))

    def test_the_prefix_needs_a_word_boundary_on_its_left(self) -> None:
        """Shipped without one, and it opened a hole bigger than the one it closed.

        `v` matched the *tail* of CV, HIV, dev, MeV and .csv; `table` matched stable;
        `section` matched cross-section. Measured over the 263 archived stage drafts, 29
        numeric tokens across 11 of the 40 runs were silently dropped. It cut both ways:
        an invented number written "CV 0.821" escaped `numeric_fidelity` for +0.0476 of
        total — the same size as the gradient the filter was added to remove — and an
        honest on-disk "CV 0.0230" stopped counting as an answer for
        `deliverable_coverage`.
        """
        from src.rubric import _is_measurement_like

        for prefix in (
            "AUROC on HIV ", "the CV ", "mean dev ", "a stable ", "cross-section ",
            "measured in mSv ", "the ratio D_DV ", "sub-section width ",
        ):
            with self.subTest(prefix=prefix):
                self.assertTrue(_is_measurement_like("0.821", 0.821, prefix=prefix))

        for prefix in ("see arXiv:", "Fig. ", "in equation ", "Table ", "see Section ", "ref. "):
            with self.subTest(prefix=prefix):
                self.assertFalse(_is_measurement_like("3.5", 3.5, prefix=prefix))


if __name__ == "__main__":
    unittest.main()
