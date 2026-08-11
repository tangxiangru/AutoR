from __future__ import annotations

from contextlib import ExitStack
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.approval_agent import ReviewDecision
from src.intake import load_intake_context
from src.evolution import EvolutionConfig
from src.manager import ResearchManager
from src.manifest import load_run_manifest
from src.project_bootstrap import StageAssessment
from src.utils import (
    DEFAULT_REFINEMENT_SUGGESTIONS,
    INTAKE_STAGE,
    STAGES,
    OperatorResult,
    approved_stage_summaries,
    build_run_paths,
    load_run_config,
    read_text,
    relative_to_run,
    selected_output_format,
    write_attempt_count,
    write_text,
)


REPO_ROOT = Path(__file__).resolve().parent.parent


def _smoke_markdown_report() -> str:
    """A report long enough to clear the markdown Stage 07 gates, with a resolving figure."""
    body = (
        "Smoke-test prose describing the methodology, the measured accuracy of 0.90 on the "
        "held-out split, and the discussion that follows from it. "
    )
    return (
        "# Smoke Research Report\n\n"
        "## Abstract\n\n"
        f"{body}\n\n"
        "## Methodology\n\n"
        f"{body * 6}\n\n"
        "## Results\n\n"
        f"{body * 6}\n\n"
        "![Held-out accuracy across folds.](images/accuracy.png)\n\n"
        "## Discussion\n\n"
        f"{body * 6}\n\n"
        "## Limitations\n\n"
        f"{body}\n"
    )


STAGE_01 = next(stage for stage in STAGES if stage.slug == "01_literature_survey")
STAGE_05 = next(stage for stage in STAGES if stage.slug == "05_experimentation")
STAGE_06 = next(stage for stage in STAGES if stage.slug == "06_analysis")


class ScriptedSmokeOperator:
    def __init__(self) -> None:
        self.model = "smoke-test-model"
        self.invocations: dict[str, int] = {}
        self.continue_modes: dict[str, list[bool]] = {}
        self.prompts: dict[str, list[str]] = {}

    def run_stage(
        self,
        stage,
        prompt: str,
        paths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        invocation = self.invocations.get(stage.slug, 0) + 1
        self.invocations[stage.slug] = invocation
        self.continue_modes.setdefault(stage.slug, []).append(continue_session)
        self.prompts.setdefault(stage.slug, []).append(prompt)
        produced = self._materialize_artifacts(stage, paths, invocation)
        stage_file = paths.stage_tmp_file(stage)
        write_text(
            stage_file,
            self._build_stage_markdown(
                stage,
                paths,
                invocation,
                produced,
                continue_session,
                len(prompt.split()),
            ),
        )
        return OperatorResult(
            success=True,
            exit_code=0,
            stdout=f"scripted invocation {invocation}",
            stderr="",
            stage_file_path=stage_file,
            session_id=f"{stage.slug}-session-{invocation}",
        )

    def repair_stage_summary(
        self,
        stage,
        original_prompt: str,
        original_result: OperatorResult,
        paths,
        attempt_no: int,
    ) -> OperatorResult:
        return self.run_stage(stage, original_prompt, paths, attempt_no, continue_session=False)

    def _materialize_artifacts(self, stage, paths, invocation: int) -> list[str]:
        produced: list[str] = []

        if stage.slug == "bootstrap":
            profile_files = {
                paths.profile_dir / "research_profile.json": json.dumps(
                    {
                        "themes": ["reasoning"],
                        "terminology": ["chain-of-thought"],
                        "methods": ["prompting"],
                        "venues": ["NeurIPS"],
                        "confidence": "medium",
                        "summary": "Researcher focused on reasoning workflows.",
                    }
                ),
                paths.profile_dir / "citation_neighborhood.json": json.dumps(
                    {
                        "frequently_cited": [
                            {"title": "Chain-of-Thought Prompting", "authors": "Wei et al.", "year": "2022"},
                        ],
                        "related_authors": ["Wei et al."],
                        "key_venues": ["NeurIPS"],
                        "seed_papers": [
                            {
                                "title": "Chain-of-Thought Prompting",
                                "authors": "Wei et al.",
                                "year": "2022",
                                "why": "Foundational reasoning prior.",
                            }
                        ],
                    }
                ),
                paths.profile_dir / "style_profile.json": json.dumps(
                    {
                        "voice": "mixed",
                        "person": "first_plural",
                        "formality": "formal",
                        "avg_section_count": 6,
                        "section_ordering": ["Introduction", "Method", "Experiments", "Conclusion"],
                        "abstract_pattern": "problem-method-result",
                        "notation_conventions": ["boldface for vectors"],
                        "paragraph_style": "topic-sentence-first",
                        "notes": "Prefers concise academic prose.",
                    }
                ),
                paths.profile_dir / "style_notes.md": "# Writing Style Profile\n\n- Formal and concise.\n",
                paths.profile_dir / "bootstrap_summary.md": "This corpus suggests a reasoning-focused researcher profile.\n",
                paths.profile_dir / "corpus_manifest.json": json.dumps(
                    {
                        "corpus_path": str(paths.run_root / "paper_corpus"),
                        "scanned_at": "2026-04-08T00:00:00",
                        "total_files_found": 2,
                        "files_processed": 2,
                        "files_skipped": 0,
                        "skipped_reasons": [],
                        "papers": [],
                    }
                ),
            }
            for path, content in profile_files.items():
                write_text(path, content)
                produced.append(relative_to_run(path, paths.run_root))

        if stage.slug == "01_literature_survey":
            sources_path = paths.literature_dir / "sources.json"
            claims_path = paths.literature_dir / "claims.json"
            write_text(
                sources_path,
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_id": "S1",
                                "title": "Smoke literature source",
                                "path": "workspace/notes/01_literature_survey_smoke_note.md",
                            }
                        ]
                    }
                ),
            )
            write_text(
                claims_path,
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim_id": "CL1",
                                "statement": "Smoke literature review produced a traceable source ledger.",
                                "source_ids": ["S1"],
                            }
                        ]
                    }
                ),
            )
            produced.extend(
                [
                    relative_to_run(sources_path, paths.run_root),
                    relative_to_run(claims_path, paths.run_root),
                ]
            )

        note_path = paths.notes_dir / f"{stage.slug}_smoke_note.md"
        write_text(note_path, f"# Smoke Note\n\nStage: {stage.slug}\nInvocation: {invocation}\n")
        produced.append(relative_to_run(note_path, paths.run_root))

        if stage.number >= 3 and not paths.hypothesis_manifest.exists():
            # What the prompt's "Missing Hypotheses" block asks for: a run
            # adopted from an existing project still has to say what it tests.
            write_text(
                paths.hypothesis_manifest,
                json.dumps(
                    {
                        "generated_at": "2026-04-08T00:00:00",
                        "theoretical_propositions": [
                            {"id": "T1", "type": "theoretical",
                             "statement": "The adopted project targets long-context reasoning."}
                        ],
                        "empirical_hypotheses": [
                            {
                                "id": "H1",
                                "type": "empirical",
                                "statement": "Retrieval improves long-context benchmark accuracy by at least 8 points.",
                                "decision_rule": (
                                    "supported if retrieval-on exceeds retrieval-off by more than 8 "
                                    "accuracy points on the held-out split; refuted otherwise."
                                ),
                            }
                        ],
                        "paper_claims": [
                            {"id": "C1", "type": "paper_claim",
                             "statement": "Retrieval is a practical long-context fix."}
                        ],
                    }
                ),
            )
            produced.append(relative_to_run(paths.hypothesis_manifest, paths.run_root))

        if stage.number >= 3:
            write_text(
                paths.experimental_protocol,
                json.dumps(
                    {
                        "declared_at": "2026-04-08T00:00:00",
                        "primary_metric": "held-out benchmark accuracy",
                        "planned_seeds": 5,
                        "baselines": [
                            {
                                "name": "retrieval-off long-context prompting",
                                "why_competent": "the standard approach this method has to beat",
                                "tuning_budget": "the same 20-configuration search the method gets",
                            }
                        ],
                    }
                ),
            )
            produced.append(relative_to_run(paths.experimental_protocol, paths.run_root))

        if stage.number >= 3 and not paths.report_plan.exists():
            # One slot, naming the figure this operator actually publishes and
            # references at Stage 07. Written once rather than every stage: the
            # plan has no freshness requirement, and rewriting it would erase
            # the `declared_at` and `digest` the manager stamps on approval.
            write_text(
                paths.report_plan,
                json.dumps(
                    {
                        "figures": [
                            {
                                "slot": 1,
                                "filename": "accuracy.png",
                                "supports": ["H1"],
                                "shows": (
                                    "Held-out accuracy (%) for retrieval-on and retrieval-off "
                                    "across five folds, band = stderr."
                                ),
                                "if_supported": "the retrieval-on bar clears the retrieval-off band",
                                "if_refuted": "the two bars overlap within their bands",
                                "source_artifact": "results/metrics.json",
                                "dropped_because": "",
                            }
                        ],
                        "headline_numbers": [
                            {
                                "quantity": "held-out accuracy, retrieval-on minus retrieval-off",
                                "unit": "percentage points",
                                "source_artifact": "results/metrics.json",
                            }
                        ],
                        "task_outputs": [
                            {
                                "stated": "the retrieval-on versus retrieval-off accuracy comparison",
                                "covered_by": "figure:1",
                                "why_not": "",
                            }
                        ],
                    }
                ),
            )
            produced.append(relative_to_run(paths.report_plan, paths.run_root))

        if stage.number >= 3:
            data_path = paths.data_dir / "study_design.json"
            write_text(
                data_path,
                json.dumps({"stage": stage.slug, "invocation": invocation, "dataset": "smoke"}),
            )
            produced.append(relative_to_run(data_path, paths.run_root))

        if stage.number >= 4:
            code_path = paths.code_dir / "train.py"
            write_text(code_path, "print('smoke experiment entrypoint')\n")
            produced.append(relative_to_run(code_path, paths.run_root))

        if stage.number >= 5:
            result_path = paths.results_dir / "metrics.json"
            write_text(
                result_path,
                json.dumps({"stage": stage.slug, "invocation": invocation, "accuracy": 0.9}),
            )
            produced.append(relative_to_run(result_path, paths.run_root))

        if stage.number >= 6:
            write_text(
                paths.round_decision,
                json.dumps(
                    {
                        "decision": "converged",
                        "rationale": "The smoke comparison clears the decision rule the round declared.",
                        "what_we_learned": "Retrieval exceeded the retrieval-off baseline by the declared margin.",
                        "what_changes_next": "",
                        "negative_result": False,
                    }
                ),
            )
            produced.append(relative_to_run(paths.round_decision, paths.run_root))

        if stage.number >= 6:
            from src.preregistration import load_preregistration

            prereg = load_preregistration(paths)
            if prereg is not None:
                write_text(
                    paths.hypothesis_outcomes,
                    json.dumps(
                        {
                            "generated_at": "2026-04-08T00:00:00",
                            "preregistration_digest": prereg.digest,
                            "outcomes": [
                                {
                                    "id": identifier,
                                    "verdict": "supported",
                                    "rationale": "Smoke adjudication against the frozen decision rule.",
                                    "evidence": ["results/metrics.json"],
                                    "statistics": {
                                        "n_seeds": 5,
                                        "dispersion": 0.011,
                                        "dispersion_type": "std",
                                    },
                                }
                                for identifier in prereg.adjudicated_ids
                            ],
                            "exploratory_findings": [],
                        }
                    ),
                )
                produced.append(relative_to_run(paths.hypothesis_outcomes, paths.run_root))

        if stage.number >= 7:
            write_text(
                paths.claim_provenance,
                json.dumps(
                    {
                        "claims": [
                            {
                                "claim": "Retrieval improves long-context benchmark accuracy.",
                                "status": "confirmatory",
                                "hypothesis_id": "H1",
                                "evidence": ["results/metrics.json"],
                            }
                        ]
                    }
                ),
            )
            produced.append(relative_to_run(paths.claim_provenance, paths.run_root))

        if stage.number >= 6:
            figure_path = paths.figures_dir / "accuracy.png"
            figure_path.write_bytes(b"\x89PNG smoke image data")
            produced.append(relative_to_run(figure_path, paths.run_root))

        if stage.number >= 7:
            if selected_output_format(paths) == "markdown":
                figure_path = paths.report_images_dir / "accuracy.png"
                figure_path.parent.mkdir(parents=True, exist_ok=True)
                figure_path.write_bytes(b"\x89PNG smoke image data")
                write_text(paths.report_file, _smoke_markdown_report())
                produced.extend(
                    [
                        relative_to_run(paths.report_file, paths.run_root),
                        relative_to_run(figure_path, paths.run_root),
                    ]
                )
            else:
                sections_dir = paths.writing_dir / "sections"
                sections_dir.mkdir(parents=True, exist_ok=True)
                write_text(
                    paths.writing_dir / "main.tex",
                    (
                        "% AutoR venue: neurips_2025\n"
                        "\\documentclass{article}\n"
                        "\\usepackage{neurips_2023}\n"
                        "\\begin{document}\n"
                        "\\input{sections/introduction}\n"
                        "\\end{document}\n"
                    ),
                )
                write_text(paths.writing_dir / "references.bib", "@article{smoke2026, title={Smoke}, year={2026}}\n")
                write_text(sections_dir / "introduction.tex", "\\section{Introduction}\nSmoke content.\n")
                write_text(sections_dir / "method.tex", "\\section{Method}\nSmoke content.\n")
                (paths.artifacts_dir / "paper.pdf").write_bytes(b"%PDF-1.4 smoke paper")
                write_text(paths.artifacts_dir / "build_log.txt", "Final status: SUCCESS\n")
                produced.extend(
                    [
                        relative_to_run(paths.writing_dir / "main.tex", paths.run_root),
                        relative_to_run(paths.artifacts_dir / "paper.pdf", paths.run_root),
                    ]
                )
            write_text(
                paths.artifacts_dir / "citation_verification.json",
                json.dumps(
                    {
                        "overall_status": "pass",
                        "total_citations": 1,
                        "verified_citations": 1,
                        "unresolved_citations": 0,
                        "claim_coverage": [
                            {
                                "claim": "Smoke writing claim",
                                "citation_keys": ["smoke2026"],
                            }
                        ],
                    }
                ),
            )
            write_text(
                paths.artifacts_dir / "self_review.json",
                json.dumps({"overall_score": 8.5, "final_verdict": "ready", "rounds": 1}),
            )
            # The Stage 07 gate now also asks what the task demanded and where the report
            # answers it. Quote the statement verbatim, as a real run must.
            from src.deliverables import COVERAGE_FILENAME, demanding_sentences

            statement = read_text(paths.user_input)
            write_text(
                paths.artifacts_dir / COVERAGE_FILENAME,
                json.dumps({
                    "deliverables": [
                        {"task_quote": sentence, "addressed": False,
                         "reason": "scripted smoke operator does no research."}
                        for sentence in demanding_sentences(statement)
                    ] or [
                        {"task_quote": " ".join(statement.split())[:120], "addressed": False,
                         "reason": "scripted smoke operator does no research."}
                    ]
                }),
            )

        if stage.number >= 8:
            review_path = paths.reviews_dir / "readiness.md"
            write_text(review_path, "# Readiness\n\n- Ready for smoke release.\n")
            produced.append(relative_to_run(review_path, paths.run_root))

        return produced

    def _build_stage_markdown(
        self,
        stage,
        paths,
        invocation: int,
        produced: list[str],
        continue_session: bool,
        prompt_word_count: int,
    ) -> str:
        prior = approved_stage_summaries(read_text(paths.memory))
        mode = "continuation" if continue_session else "fresh"
        files = "\n".join(f"- `{path}`" for path in produced)
        suggestions = "\n".join(
            f"{index}. {text}"
            for index, text in enumerate(DEFAULT_REFINEMENT_SUGGESTIONS, start=1)
        )

        if stage.slug == "02_hypothesis_generation":
            files = "\n".join(
                [
                    f"- `{path}`" for path in produced
                ]
                + [f"- `{relative_to_run(paths.hypothesis_manifest, paths.run_root)}`"]
            )
            return (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Objective\n"
                "Produce typed claims that downstream stages can consume without conflating theory, hypotheses, and paper narrative.\n\n"
                "## Previously Approved Stage Summaries\n"
                f"{prior}\n\n"
                "## What I Did\n"
                f"- Executed the scripted smoke operator in {mode} mode.\n"
                "- Generated typed propositions, empirical hypotheses, and provisional paper claims.\n\n"
                "## Key Results\n\n"
                "### Theoretical Propositions\n"
                "- **T1**: Retrieval reduces context fragmentation in long-context reasoning.\n"
                "  - Derived from: Stage 01 synthesis and prior long-context literature.\n\n"
                "### Empirical Hypotheses\n"
                "- **H1**: Retrieval will improve long-context benchmark accuracy by at least 8 points.\n"
                "  - Depends on: T1\n"
                "  - Decision rule: supported if retrieval-on exceeds retrieval-off by more than 8 "
                "accuracy points on the held-out split; refuted otherwise.\n"
                "  - Verification: Compare retrieval-on vs retrieval-off conditions.\n\n"
                "### Paper Claims (Provisional)\n"
                "- **C1**: Retrieval is a practical fix for long-context reasoning failures.\n"
                "  - Status: proposed\n\n"
                "## Files Produced\n"
                f"{files}\n\n"
                "## Decision Ledger\n"
                f"- **Open Questions**: What real evidence should replace the smoke output for {stage.display_name}?\n"
                f"- **Locked Decisions**: Keep `{stage.slug}` within the current AutoR workflow.\n"
                "- **Assumptions**: Downstream stages should primarily operationalize empirical hypotheses.\n"
                "- **Rejected Alternatives**: Mixing theory, hypotheses, and provisional claims into one prose block.\n\n"
                "## Suggestions for Refinement\n"
                f"{suggestions}\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            )

        return (
            f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
            "## Objective\n"
            f"Produce a valid smoke-test stage summary for {stage.display_name}.\n\n"
            "## Previously Approved Stage Summaries\n"
            f"{prior}\n\n"
            "## What I Did\n"
            f"- Executed the scripted smoke operator in {mode} mode.\n"
            f"- Materialized the required artifacts for {stage.slug}.\n\n"
            "## Key Results\n"
            f"- Invocation marker: {invocation}\n"
            f"- Prompt words observed: {prompt_word_count}\n"
            "- The CLI workflow, validation, and approval loop all executed.\n\n"
            "## Files Produced\n"
            f"{files}\n\n"
            "## Decision Ledger\n"
            f"- **Open Questions**: What real evidence should replace the smoke output for {stage.display_name}?\n"
            f"- **Locked Decisions**: Keep `{stage.slug}` within the current AutoR workflow.\n"
            "- **Assumptions**: This run is validating orchestration behavior, not research quality.\n"
            "- **Rejected Alternatives**: Treating placeholder smoke artifacts as publishable results.\n\n"
            "## Suggestions for Refinement\n"
            f"{suggestions}\n\n"
            "## Your Options\n"
            "1. Use suggestion 1\n"
            "2. Use suggestion 2\n"
            "3. Use suggestion 3\n"
            "4. Refine with your own feedback\n"
            "5. Approve and continue\n"
            "6. Abort\n"
        )


class BootstrapAdjustingSmokeOperator(ScriptedSmokeOperator):
    def __init__(self, corrected_assessments: list[StageAssessment]) -> None:
        super().__init__()
        self.corrected_assessments = corrected_assessments

    def run_stage(
        self,
        stage,
        prompt: str,
        paths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        if stage.slug == "project_bootstrap":
            write_text(
                paths.bootstrap_dir / "stage_assessments.json",
                json.dumps([assessment.__dict__ for assessment in self.corrected_assessments], indent=2),
            )
        return super().run_stage(stage, prompt, paths, attempt_no, continue_session=continue_session)


class RepairingRevisionDeltaOperator(ScriptedSmokeOperator):
    def run_stage(
        self,
        stage,
        prompt: str,
        paths,
        attempt_no: int,
        continue_session: bool = False,
    ) -> OperatorResult:
        produced = self._materialize_artifacts(stage, paths, 1)
        stage_file = paths.stage_tmp_file(stage)
        write_text(
            stage_file,
            (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Revision Delta\n"
                "- Initial invalid delta should not survive human review.\n\n"
                "## Objective\n"
                "Broken first draft.\n\n"
                "## Previously Approved Stage Summaries\n"
                "_None yet._\n\n"
                "## What I Did\n"
                "Wrote an incomplete draft.\n\n"
                "## Files Produced\n"
                + "\n".join(f"- `{path}`" for path in produced)
                + "\n\n"
                "## Decision Ledger\n"
                "- **Open Questions**: Which section is still incomplete?\n"
                "- **Locked Decisions**: Keep the revision-delta path enabled.\n"
                "- **Assumptions**: The draft will be repaired before review.\n"
                "- **Rejected Alternatives**: Promoting the invalid first draft.\n\n"
                "## Suggestions for Refinement\n"
                "1. a\n2. b\n3. c\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            ),
        )
        return OperatorResult(
            success=True,
            exit_code=0,
            stdout="invalid first draft",
            stderr="",
            stage_file_path=stage_file,
            session_id=f"{stage.slug}-session-1",
        )

    def repair_stage_summary(
        self,
        stage,
        original_prompt: str,
        original_result: OperatorResult,
        paths,
        attempt_no: int,
    ) -> OperatorResult:
        produced = self._materialize_artifacts(stage, paths, 2)
        stage_file = paths.stage_tmp_file(stage)
        write_text(
            stage_file,
            (
                f"# Stage {stage.number:02d}: {stage.display_name}\n\n"
                "## Revision Delta\n"
                "- Repair delta should be shown to the reviewer.\n"
                "- Added the missing Key Results section.\n\n"
                "## Objective\n"
                "Produce a valid smoke-test stage summary.\n\n"
                "## Previously Approved Stage Summaries\n"
                "_None yet._\n\n"
                "## What I Did\n"
                "- Repaired the stage summary.\n\n"
                "## Key Results\n"
                "- The repaired draft is now valid.\n\n"
                "## Files Produced\n"
                + "\n".join(f"- `{path}`" for path in produced)
                + "\n\n"
                "## Decision Ledger\n"
                "- **Open Questions**: What should the reviewer tighten next?\n"
                "- **Locked Decisions**: Preserve the repaired draft structure.\n"
                "- **Assumptions**: The repaired artifacts are sufficient for smoke validation.\n"
                "- **Rejected Alternatives**: Reverting to the broken first draft.\n\n"
                "## Suggestions for Refinement\n"
                "1. Tighten scope.\n"
                "2. Strengthen evidence.\n"
                "3. Clarify next steps.\n\n"
                "## Your Options\n"
                "1. Use suggestion 1\n"
                "2. Use suggestion 2\n"
                "3. Use suggestion 3\n"
                "4. Refine with your own feedback\n"
                "5. Approve and continue\n"
                "6. Abort\n"
            ),
        )
        return OperatorResult(
            success=True,
            exit_code=0,
            stdout="repaired draft",
            stderr="",
            stage_file_path=stage_file,
            session_id=f"{stage.slug}-session-1",
        )


class ScriptedReviewer:
    def __init__(self, decisions: list[ReviewDecision]) -> None:
        self.decisions = list(decisions)
        self.calls = 0

    def review_stage(self, **_: object) -> ReviewDecision:
        self.calls += 1
        if self.decisions:
            return self.decisions.pop(0)
        return ReviewDecision(choice="5", decision_token="approve", reason="default scripted approval")


class ManagerSmokeTests(unittest.TestCase):
    def _run_roots(self, runs_dir: Path) -> list[Path]:
        return sorted(path for path in runs_dir.iterdir() if path.is_dir())

    def _build_manager(self, tmp_dir: str) -> tuple[Path, ScriptedSmokeOperator, ResearchManager]:
        runs_dir = Path(tmp_dir) / "runs"
        operator = ScriptedSmokeOperator()
        manager = ResearchManager(
            project_root=REPO_ROOT,
            runs_dir=runs_dir,
            operator=operator,
            output_stream=io.StringIO(),
            # Improvement rounds off: these tests count operator invocations to
            # measure the retry, session-reuse and round mechanics, and a polish
            # round is an invocation that is none of those. Measuring stays on, so
            # the ratchet is still exercised; `tests/test_graph_walk.py` is where
            # the rounds themselves are tested.
            evolution=EvolutionConfig(rounds=0),
        )
        return runs_dir, operator, manager

    def _auto_approve_intake(self, manager: ResearchManager, final_choice: str = "5") -> ExitStack:
        stack = ExitStack()
        stack.enter_context(patch.object(manager.ui, "choose_intake_clarification_answer", return_value=None))
        stack.enter_context(patch.object(manager.ui, "read_optional_multiline_feedback", return_value=None))
        stack.enter_context(patch.object(manager.ui, "choose_intake_final_action", return_value=final_choice))
        return stack

    def test_manager_run_completes_full_eight_stage_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, operator, manager = self._build_manager(tmp_dir)

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                success = manager.run(
                    "Smoke-test the end-to-end AutoR flow.",
                    venue="neurips_2025",
                    output_format="latex",
                )

            self.assertTrue(success)
            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            self.assertTrue(paths.run_manifest.exists())
            self.assertTrue((paths.artifacts_dir / "paper_package" / "paper.pdf").exists())
            self.assertTrue((paths.artifacts_dir / "release_package" / "artifact_bundle_manifest.json").exists())
            self.assertTrue(paths.stage_file(STAGE_06).exists())

    def test_manager_run_in_markdown_mode_produces_the_scored_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, _operator, manager = self._build_manager(tmp_dir)

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                success = manager.run("Smoke-test the markdown deliverable.", venue="neurips_2025")

            self.assertTrue(success)
            paths = build_run_paths(self._run_roots(runs_dir)[0])

            self.assertEqual(load_run_config(paths)["output_format"], "markdown")
            self.assertTrue(paths.report_file.exists())
            report = read_text(paths.report_file)
            self.assertIn("![Held-out accuracy across folds.](images/accuracy.png)", report)
            self.assertTrue((paths.report_images_dir / "accuracy.png").exists())

            review = json.loads((paths.artifacts_dir / "report_review.json").read_text(encoding="utf-8"))
            self.assertEqual(review["overall_status"], "clean")
            self.assertEqual(review["referenced_image_count"], 1)

            # The LaTeX submission bundle is not produced, and no PDF is claimed anywhere.
            self.assertFalse((paths.artifacts_dir / "paper_package" / "paper.pdf").exists())
            self.assertFalse((paths.writing_dir / "main.tex").exists())
            self.assertFalse((paths.artifacts_dir / "layout_review.json").exists())

    def test_intake_first_pass_collects_clarifications_then_final_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, operator, manager = self._build_manager(tmp_dir)
            paths = manager._create_run("Smoke-test intake clarification handling.", venue="neurips_2025")

            with (
                patch.object(
                    manager.ui,
                    "choose_intake_clarification_answer",
                    side_effect=["Focus on empirical evaluation.", None, "Target a conference paper."],
                ) as ask_question,
                patch.object(
                    manager.ui,
                    "read_optional_multiline_feedback",
                    return_value="Keep the first experiment lightweight.",
                ),
                patch.object(manager.ui, "choose_intake_final_action", return_value="5") as final_action,
            ):
                approved = manager._run_intake(paths)

            self.assertTrue(approved)
            self.assertEqual(ask_question.call_count, 3)
            self.assertEqual(final_action.call_count, 1)
            self.assertEqual(operator.continue_modes[INTAKE_STAGE.slug], [False, True])
            self.assertIn("Focus on empirical evaluation.", operator.prompts[INTAKE_STAGE.slug][1])
            self.assertIn("Keep the first experiment lightweight.", operator.prompts[INTAKE_STAGE.slug][1])
            ctx = load_intake_context(paths)
            self.assertIsNotNone(ctx)
            assert ctx is not None
            answers = [turn.answer for turn in ctx.qa_transcript]
            self.assertIn("Focus on empirical evaluation.", answers)
            self.assertIn("Skipped as non-critical.", answers)
            self.assertIn("Keep the first experiment lightweight.", answers)

    def test_resume_run_from_redo_stage_reruns_downstream_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, operator, manager = self._build_manager(tmp_dir)

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                self.assertTrue(manager.run("Smoke-test redo-stage handling.", venue="neurips_2025"))

            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            initial_stage06 = read_text(paths.stage_file(STAGE_06))
            self.assertIn("Invocation marker: 1", initial_stage06)

            with patch.object(manager, "_ask_choice", return_value="5"):
                resumed = manager.resume_run(run_root, start_stage=STAGE_06, venue="neurips_2025")

            self.assertTrue(resumed)
            rerun_stage06 = read_text(paths.stage_file(STAGE_06))
            self.assertIn("Invocation marker: 2", rerun_stage06)
            self.assertIn("Invocation marker: 1", read_text(paths.stage_file(STAGES[4])))

    def test_stage_refinement_reuses_same_stage_before_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, operator, manager = self._build_manager(tmp_dir)
            paths = manager._create_run("Smoke-test stage refinement handling.", venue="neurips_2025")

            with patch.object(manager, "_ask_choice", side_effect=["1", "5"]):
                approved = manager._run_stage(paths, STAGE_01)

            self.assertTrue(approved)
            self.assertEqual(operator.continue_modes[STAGE_01.slug], [False, True])
            self.assertIn("Invocation marker: 2", read_text(paths.stage_file(STAGE_01)))

            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            entry = next(item for item in manifest.stages if item.slug == STAGE_01.slug)
            self.assertTrue(entry.approved)
            self.assertEqual(entry.attempt_count, 2)

    def test_automated_reviewer_can_drive_refine_then_approve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            operator = ScriptedSmokeOperator()
            reviewer = ScriptedReviewer(
                [
                    ReviewDecision(
                        choice="4",
                        decision_token="custom_feedback",
                        reason="Need a sharper evidence bar.",
                        feedback="Strengthen the survey note so the stage is less toy and more traceable.",
                    ),
                    ReviewDecision(
                        choice="5",
                        decision_token="approve",
                        reason="The revised stage is now acceptable.",
                    ),
                ]
            )
            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=runs_dir,
                operator=operator,
                output_stream=io.StringIO(),
                reviewer=reviewer,
                approval_mode="agent",
                review_operator="claude",
                review_model="sonnet",
                evolution=EvolutionConfig(rounds=0),
            )
            paths = manager._create_run("Smoke-test automated approval mode.", venue="neurips_2025")

            approved = manager._run_stage(paths, STAGE_01)

            self.assertTrue(approved)
            self.assertEqual(reviewer.calls, 2)
            self.assertEqual(operator.continue_modes[STAGE_01.slug], [False, True])
            self.assertIn("Invocation marker: 2", read_text(paths.stage_file(STAGE_01)))

    def test_stage_can_be_skipped_after_exhausted_retries(self) -> None:
        class DummyTTY:
            def isatty(self) -> bool:
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            _, _, manager = self._build_manager(tmp_dir)
            paths = manager._create_run("Smoke-test stage skip recovery.", venue="neurips_2025")
            manager.ui.input_stream = DummyTTY()
            manager.ui.read_single_line = MagicMock(return_value="1")

            manager.max_stage_attempts = 0
            approved = manager._run_stage(paths, STAGE_01)

            self.assertTrue(approved)
            stage_markdown = read_text(paths.stage_file(STAGE_01))
            self.assertIn("intentionally skipped", stage_markdown)
            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            entry = next(item for item in manifest.stages if item.slug == STAGE_01.slug)
            # A skip settles the stage so the run advances, but it is not an
            # approval: nothing was reviewed and no work was done.
            self.assertTrue(entry.settled)
            self.assertFalse(entry.approved)
            self.assertTrue(entry.skipped)
            self.assertEqual(entry.status, "skipped")
            self.assertEqual(entry.skip_kind, "human")
            self.assertIsNone(entry.approved_at)
            self.assertIn("Human operator skipped", entry.skip_reason or "")

    def test_back_command_rolls_run_to_earlier_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            _, _, manager = self._build_manager(tmp_dir)
            paths = manager._create_run("Smoke-test /back command handling.", venue="neurips_2025")

            with patch.object(manager, "_ask_choice", return_value="5"):
                self.assertTrue(manager._run_stage(paths, STAGE_01))

            handled = manager._handle_stage_control_command(
                paths=paths,
                stage=STAGES[1],
                attempt_no=1,
                command_text="/back 01",
            )

            self.assertTrue(handled)
            self.assertEqual(manager._jump_target_stage, STAGE_01)
            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            stage01_entry = next(item for item in manifest.stages if item.slug == STAGE_01.slug)
            self.assertFalse(stage01_entry.approved)
            self.assertEqual(stage01_entry.status, "pending")

    def test_revision_delta_uses_repaired_draft_and_is_stripped_before_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            output = io.StringIO()
            operator = RepairingRevisionDeltaOperator()
            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=runs_dir,
                operator=operator,
                output_stream=output,
            )
            paths = manager._create_run("Smoke-test revision delta repair handling.", venue="neurips_2025")
            write_attempt_count(paths, STAGE_01, 1)

            with patch.object(manager, "_ask_choice", return_value="5"):
                approved = manager._run_stage(paths, STAGE_01)

            self.assertTrue(approved)
            rendered = output.getvalue()
            self.assertIn("Repair delta should be shown", rendered)
            self.assertNotIn("Initial invalid delta should not survive", rendered)

            final_markdown = read_text(paths.stage_file(STAGE_01))
            self.assertNotIn("## Revision Delta", final_markdown)
            self.assertNotIn("Repair delta should be shown", final_markdown)
            self.assertIn("## Key Results", final_markdown)

    def test_resume_run_with_rollback_reruns_invalidated_downstream_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, operator, manager = self._build_manager(tmp_dir)

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                self.assertTrue(manager.run("Smoke-test rollback resume handling.", venue="neurips_2025"))

            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            self.assertIn("Invocation marker: 1", read_text(paths.stage_file(STAGE_05)))
            self.assertIn("Invocation marker: 1", read_text(paths.stage_file(STAGE_06)))

            with patch.object(manager, "_ask_choice", return_value="5"):
                resumed = manager.resume_run(run_root, rollback_stage=STAGE_05, venue="neurips_2025")

            self.assertTrue(resumed)
            self.assertIn("Invocation marker: 2", read_text(paths.stage_file(STAGE_05)))
            self.assertIn("Invocation marker: 2", read_text(paths.stage_file(STAGE_06)))
            self.assertEqual(operator.invocations[STAGE_05.slug], 2)
            self.assertEqual(operator.invocations[STAGE_06.slug], 2)
            self.assertIn("Invocation marker: 1", read_text(paths.stage_file(STAGES[3])))

    def test_manager_abort_marks_run_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, _, manager = self._build_manager(tmp_dir)

            with self._auto_approve_intake(manager, final_choice="6"), patch.object(manager, "_ask_choice", return_value="6"):
                success = manager.run("Smoke-test abort handling.", venue="neurips_2025")

            self.assertFalse(success)
            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            self.assertEqual(manifest.run_status, "cancelled")
            self.assertEqual(manifest.current_stage_slug, INTAKE_STAGE.slug)
            self.assertIsNone(manifest.completed_at)

    def test_project_bootstrap_carries_forward_prior_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, operator, manager = self._build_manager(tmp_dir)
            project_root = Path(tmp_dir) / "existing_project"
            project_root.mkdir()
            for name in ["main.py", "model.py", "train.py", "data.py", "utils.py", "eval.py"]:
                (project_root / name).write_text("# existing project code\n", encoding="utf-8")
            (project_root / "requirements.txt").write_text("torch\n", encoding="utf-8")

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                success = manager.run(
                    "Adopt an existing project into AutoR.",
                    venue="neurips_2025",
                    project_root=project_root,
                )

            self.assertTrue(success)
            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            manifest = load_run_manifest(paths.run_manifest)
            self.assertIsNotNone(manifest)
            assert manifest is not None
            for stage in STAGES[:4]:
                entry = next(item for item in manifest.stages if item.slug == stage.slug)
                self.assertTrue(entry.approved)
                self.assertTrue(paths.stage_file(stage).exists())
            self.assertNotIn(STAGE_01.slug, operator.invocations)
            self.assertIn(STAGE_05.slug, operator.invocations)
            memory_text = read_text(paths.memory)
            self.assertIn("Stage 00: Research Intake", memory_text)
            self.assertIn("Stage 01: Literature Survey", memory_text)
            self.assertIn("Stage 04: Implementation", memory_text)
            self.assertNotIn("Stage -1: Project Repo Bootstrap", memory_text)

    def test_project_bootstrap_uses_corrected_stage_assessments_for_entry_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir = Path(tmp_dir) / "runs"
            corrected = [
                StageAssessment(1, "Literature Survey", "complete", "medium", ["bootstrap-approved"]),
                StageAssessment(2, "Hypothesis Generation", "complete", "medium", ["bootstrap-approved"]),
                StageAssessment(3, "Study Design", "not_started", "high", ["design gap remains"]),
                StageAssessment(4, "Implementation", "complete", "high", ["implementation exists"]),
                StageAssessment(5, "Experimentation", "not_started", "medium", ["no reliable experiment results"]),
                StageAssessment(6, "Analysis", "not_started", "medium", ["no reliable analysis"]),
                StageAssessment(7, "Writing", "not_started", "medium", ["no usable manuscript"]),
                StageAssessment(8, "Dissemination", "not_started", "medium", ["no dissemination artifacts"]),
            ]
            operator = BootstrapAdjustingSmokeOperator(corrected)
            manager = ResearchManager(
                project_root=REPO_ROOT,
                runs_dir=runs_dir,
                operator=operator,
                output_stream=io.StringIO(),
            )
            project_root = Path(tmp_dir) / "existing_project"
            project_root.mkdir()
            for name in ["main.py", "model.py", "train.py", "eval.py"]:
                (project_root / name).write_text("# existing project code\n", encoding="utf-8")
            (project_root / "requirements.txt").write_text("torch\n", encoding="utf-8")

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                success = manager.run(
                    "Adopt an existing project with a bootstrap correction.",
                    venue="neurips_2025",
                    project_root=project_root,
                )

            self.assertTrue(success)
            self.assertIn(STAGES[2].slug, operator.invocations)
            self.assertNotIn(STAGE_01.slug, operator.invocations)
            self.assertNotIn(STAGES[1].slug, operator.invocations)

    def test_paper_corpus_bootstrap_injects_profile_into_downstream_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_dir, operator, manager = self._build_manager(tmp_dir)
            corpus_root = Path(tmp_dir) / "paper_corpus"
            corpus_root.mkdir()
            (corpus_root / "paper.tex").write_text(
                (
                    "\\title{Prior Work}\n"
                    "\\begin{document}\n"
                    "\\begin{abstract}We study reasoning workflows.\\end{abstract}\n"
                    "\\section{Introduction}Prior text.\n"
                    "\\end{document}\n"
                ),
                encoding="utf-8",
            )
            (corpus_root / "refs.bib").write_text(
                (
                    "@article{cot2022,\n"
                    "  title={Chain-of-Thought Prompting},\n"
                    "  author={Wei et al.},\n"
                    "  year={2022},\n"
                    "  journal={NeurIPS}\n"
                    "}\n"
                ),
                encoding="utf-8",
            )

            with self._auto_approve_intake(manager), patch.object(manager, "_ask_choice", return_value="5"):
                success = manager.run(
                    "Use my prior papers to align the new project.",
                    venue="neurips_2025",
                    paper_corpus=corpus_root,
                )

            self.assertTrue(success)
            run_root = self._run_roots(runs_dir)[0]
            paths = build_run_paths(run_root)
            self.assertIn("bootstrap", operator.invocations)
            self.assertTrue((paths.profile_dir / "research_profile.json").exists())
            self.assertTrue((paths.profile_dir / "style_profile.json").exists())
            stage01_prompt = operator.prompts[STAGE_01.slug][0]
            self.assertIn("Researcher Profile (from paper corpus bootstrap)", stage01_prompt)
            self.assertIn("Seed papers for literature search", stage01_prompt)
            memory_text = read_text(paths.memory)
            self.assertNotIn("Stage -1", memory_text)


if __name__ == "__main__":
    unittest.main()
